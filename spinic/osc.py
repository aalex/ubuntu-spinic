#!/usr/bin/env python
"""
Receives and sends OSC messages from and to a SPIN server.

The SPIN Framework is designed so multiple processes can share state over a network via OpenSoundControl (OSC) messages. By default, these messages are sent using multicast UDP to the address of 239.0.0.1. Most network interfaces are already members of this multicast group, so a typical client application need only to start a UDP listener on the appropriate port to discover messages related to SPIN.

Lexicon:
 * Node: a ode in the scene graph
 * UserNode: a SPIN node for a kiosk
 * Context: which user can see a node.
 * StateSet: set of states for a node.

When spinic sees two user nodes with cameras, he launches a Milhouse sender for his user nodes cameras to the other user's reciver host and port.
"""
#TODO: Clear servers that are dead. (after a timeout of 30 s)
#TODO: Stop streamers when I leave a scene.
#TODO: restart spinviewer when we choose another server

import sys
import math
from twisted.internet import reactor
from twisted.internet import defer
from twisted.internet import error
from twisted.python import log
from twisted.internet import task
from txosc import osc
from txosc import dispatch
from txosc import async
from lunch import logger
from spinic import cameras
from lunch import sig

log = logger.start(name="osc")

class ServerInfo(object):
    """
    Info about a SPIN server / scene
    """
    #TODO: use kwargs instead of args.
    def __init__(self, scene_id, server_recv_addr, server_recv_port, server_send_addr, server_send_port, server_tcp_recv_port):
        self.scene_id = scene_id
        # Server receives:
        self.server_recv_addr = server_recv_addr
        self.server_recv_port = int(server_recv_port)
        # Server send:
        self.server_send_addr = server_send_addr
        self.server_send_port = int(server_send_port)
        # Other receive ports:
        #self.sync_port = sync_port
        self.server_tcp_recv_port = int(server_tcp_recv_port)
        
        log.info("ServerInfo: ID: %s. Server recv: %s:%s. Server send: %s:%s. TCP port: %s" % ( scene_id, server_recv_addr, server_recv_port, server_send_addr, server_send_port, server_tcp_recv_port))

class UserNodeInfo(object):
    """
    Information regarding a user node in the SPIN scene graph.
    """
    # TODO: not used yet!
    def __init__(self, name):
        self.name = name
        self.position = [0.0, 0.0, 0.0] # x y z
        self.orientation = [0.0, 0.0, 0.0] # roll pitch yaw
        self.current_camera = None # str
        self.params = {} # list of params. The cameras are in the form cameras[1]: <camera_id>@<from_address>
        self.streaming_is_on = False

class SceneInfo(object):
    """
    Information regarding a SPIN scene graph.
    """
    def __init__(self):
        self.all_nodes = {} # nodeType: list of node names
        self.user_nodes = {} #TODO: not used yet.
    
class SpinicOscInterface(object):
    """
    Communicates with SPIN with UDP OSC messages.
    """
    def __init__(self, app=None):
        # The GUI:
        self.app = app
        self.gui = self.app.gui
        
        # signals/slots
        self.connected_to_scene_signal = sig.Signal() # args: scene_id
        self.start_streaming_with_user_signal = sig.Signal() # args: scene_id, user_id
        self.stopped_streaming_with_user_signal = sig.Signal() # args: scene_id, user_id
        
        # Info channel:
        self._info_datagram_protocol = None
        self.info_multicast_group = self.app.config.info_multicast_group
        self.info_port_number = self.app.config.info_port
        self.info_receiver = None
        
        # Scene channel:
        self._scene_receiver_protocol = None
        self._scene_sender_protocol = None
        self.scene_receiver = None
        self.scene_sender = None

        # Tracking SPIN scenes/servers:
        self.servers = {} # keys are their names. Values are ServerInfo instances.
        self.scenes = {} # keys are their names. Values are SceneInfo instances.
        self.current_server_id = None # str
        self.my_user_id = self.app.config.user_id # ID of the user for the spinviewer
        
        # Tracking the position of everyone in the scene:
        self.my_yaw = 0.0 # to change our user position
        self.scenes_info = {}
        
        # Cameras IDs
        # TODO: we need to store my user's camera id, 
        # and the textures for each user nodes.
        self.cameras = ["north", "east", "south", "west"] # FIXME: we will use the camera ids later on
        
        # Start taking action:
        self._start_info_listener()
        self._looping_print = task.LoopingCall(self._print_debug_infos)
        self._looping_print.start(2.0, now=False)
        self._looping_ping = task.LoopingCall(self._keep_user_alive)
        self._looping_ping.start(15.0, now=False)

    def _keep_user_alive(self):
        if self.current_server_id is not None:
            self.send_to_node_in_scene(self.my_user_id, "ping")
    
    def _print_debug_infos(self):
        """
        Updates the text views in the GUI with the list of nodes in the scene.
        """
        #TODO: rename this.
        known_user_nodes = sorted(self.get_current_scene().user_nodes.keys())
        #log.debug("Known user nodes: %s" % (known_user_nodes))
        txt = ""
        try:
            if len(known_user_nodes) != 0:
                txt = "UserNode nodes:\n"
                for n in known_user_nodes:
                    txt += " * %s\n" % (n)
            for node_type, nodes in self.get_current_scene().all_nodes.iteritems():
                if node_type == "UserNode":
                    pass
                else:
                    if len(nodes) != 0:
                        txt += "%s nodes:\n" % (node_type)
                        for node in nodes:
                            txt += " * %s\n" % (node)
        except KeyError, e:
            log.warning(str(e))
        if len(known_user_nodes) != 0:
            txt += "UserNode params:\n"
            for name, user in sorted(self.get_current_scene().user_nodes.items()):
                txt += " * %s: {\n" % (name)
                for key, value in user.params.iteritems():
                    txt += "     %s: %s\n" % (key, value)
                txt += " }\n"
        self.gui.update_nodes_text(txt)

    def _start_info_listener(self):
        """
        Starts the listener for the info channel.
        
        Exits (!!!) in case of error.
        """
        self.info_receiver = dispatch.Receiver()
        server_protocol = async.MulticastDatagramServerProtocol(self.info_receiver, multicast_addr=self.info_multicast_group)
        try:
            self._info_datagram_protocol = reactor.listenMulticast(self.info_port_number, server_protocol, listenMultiple=True) 
        except error.CannotListenError, e:
            print(e)
            print("Giving up!")
            sys.exit(1)
        log.info("Listening on osc.udp://localhost:%s" % (self.info_port_number))
        # adding callbacks:
        self.info_receiver.addCallback("/SPIN/__server__", self.recv_spin_server)
        self.info_receiver.addCallback("/SPIN/__user__", self.spin_user_handler) 
        self.info_receiver.setFallback(self.info_channel_fallback)
    
    def recv_spin_server(self, message, address):
        """
        Handles /SPIN/__server__ messages from the info channel.
        
        id rxAddr rxPort txAddr txPort syncPort tcpPort
        /SPIN/ default 239.0.0.1 54324 239.0.0.1 54323 224.0.0.1 54321 54322

        Expected arguments:
         * string Scene ID
         * string Server receiving  address
         * int Server receiving port
         * int Server receiving TCP port (for important messages)
         * string Server sending address
         * int Server sending port
         * int Sync port
        """
        # log.debug("recv_spin_server: Got %s from %s" % (message, address))
        arguments = message.getValues()
        #log.debug("args: %s" % (arguments))
        # We care about the server sending/receiving ports and addresses
        scene_id = arguments[0]
        server_recv_addr = arguments[1]
        server_recv_port = arguments[2]
        server_tcp_recv_port = arguments[3]
        
        server_send_addr = arguments[4]
        server_send_port = arguments[5]
        #server_sync_port = arguments[6]
        
        # If the address changed, we delete the previous entry we had:
        if self.servers.has_key(scene_id) and self.servers[scene_id].server_recv_addr != server_recv_addr: 
            #self._stop_communication_with_server(scene_id)
            log.info("Scene %s has changed its receiving address to %s." % (scene_id, server_recv_addr))
            del self.servers[scene_id]
        # If the entry is not already tracked, we add it:
        if scene_id not in self.servers.keys():
            log.info("Scene %s has receiving address %s." % (scene_id, server_recv_addr))
            self.servers[scene_id] = ServerInfo(scene_id, server_recv_addr, server_recv_port, server_send_addr, server_send_port, server_tcp_recv_port)
            #self._start_communication_with_server(scene_id)
            # We now need to update the list of server
            self._server_list_updated()
    
    def _server_list_updated(self):
        """
        Time to update the list of servers.
        
        We got a /SPIN/__server__ from a new server ID.
        It's time to subscribe to a SPIN server.
        
        Calling gui.update_server_list might in turn call self.choose_server
        """
        log.info("Servers: %s" % (" ".join(self.servers.keys())))
        self.gui.update_server_list(self.servers.keys())

        if self.current_server_id is None and self.app.config.default_scene_id is not None:
            if self.app.config.default_scene_id in self.servers.keys():
                log.info("Connecting to the scene %s since the user has set it to default and we are detecting it for the first time." % (self.app.config.default_scene_id))
                self.gui.choose_server_and_click_connect(self.app.config.default_scene_id)

    def on_connected_to_spin_server(self):
        """
        Does what need to be done in this class when we connect to a SPIN server.
         * Set the params of my spinviewer's UserNode (which tells everyone what's my cameras setup)
         * Create the statesets that everyone will use to identify the sharedvideotexture they see from my user.
        """
        self._set_params_for_my_user_node()
        self._create_statesets_for_my_user_and_cameras()
        self.connected_to_scene_signal(self.current_server_id)

    def choose_server(self, server_id):
        """
        The user wants to connect to a given server ID. 

        Called from the GUI. (the user chooses an new element in the combobox menu)
        We must then connect to that server. Listen to it and send messages to it.
        @rettype: L{twisted.internet.defer.Deferred}
        """
        deferred = defer.Deferred()
        
        def _on_started_again(result):
            # called when we are done.
            # FIXME: this is quite temporary!!
            #self.proto_create_some_nodes()
            self.gui.update_connected_state(True) # FIXME
            self.gui.process_launcher.switch_to_scene(server_id) # FIXME: we should add an application class.
            self.on_connected_to_spin_server()
            deferred.callback(None)
        
        def _on_disconnected(result):
            if self.current_server_id is not None:
                self._stop_streaming_with_all_user()
                self._delete_all_nodes()
            self.current_server_id = server_id
            deferred3 = self._start_scene_listener()
            self._start_scene_sender()
            deferred3.addCallback(_on_started_again)
            
        if self.current_server_id == server_id:
            log.error("Server %s was already chosen." % (server_id))
            return defer.succeed(None) #FIXME
        elif server_id not in self.servers.keys():
            log.error("Server %s is not in our server list. %s" % (server_id, self.servers))
            return defer.succeed(None) # FIXME
        else:
            log.info("Changing server to %s." % (server_id))
            disconnection_deferred = self.disconnect_from_current_server()
            if disconnection_deferred is None:
                _on_disconnected(None)
            disconnection_deferred.addCallback(_on_disconnected)
            return deferred
    
    def send_element(self, element):
        """
        @param element: OSC Bundle or Message.
        """
        if self.current_server_id is None:
            raise RuntimeError("You should choose a server first")
        send_addr = self.servers[self.current_server_id].server_recv_addr
        send_port = self.servers[self.current_server_id].server_recv_port
        if isinstance(element, osc.Bundle):
            for message in element.elements:
                log.debug("Sending " + str(message))
        else:
            log.debug("Sending " + str(element))
        self.scene_sender.send(element, (send_addr, send_port))

    def send_to_scene(self, *args):
        """
        Sends a message to /SPIN/<scene>
        """
        if self.current_server_id is None:
            raise RuntimeError("You should choose a server first")
        osc_path = "/SPIN/%s" % (self.current_server_id)
        self.send_element(osc.Message(osc_path, *args))

    def send_to_node_in_scene(self, node_name, *args):
        """
        Sends a message to /SPIN/<scene>/<node_name>
        """
        if self.current_server_id is None:
            raise RuntimeError("You should choose a server first")
        osc_path = "/SPIN/%s/%s" % (self.current_server_id, node_name)
        self.send_element(osc.Message(osc_path, *args))
        
    def _start_scene_listener(self):
        """
        Starts an OSC receiver for messages from a SPIN server
        @rettype: L{twisted.internet.defer.Deferred}
        """
        server_infos = self.servers[self.current_server_id]
        
        multicast_group = server_infos.server_send_addr
        recv_port = server_infos.server_send_port
        
        self.scene_receiver = dispatch.Receiver()
        server_protocol = async.MulticastDatagramServerProtocol(self.scene_receiver, multicast_addr=multicast_group)
        try:
            self._scene_receiver_protocol = reactor.listenMulticast(recv_port, server_protocol, listenMultiple=True) 
        except error.CannotListenError, e:
            log.error(str(e))
            self._scene_receiver_protocol = None
        else:
            log.info("Spinic is listening on osc.udp://%s:%d" % (multicast_group, recv_port))
            # adding callbacks:
            self.scene_receiver.addCallback("/SPIN/*", self.spin_any_handler)
            self.scene_receiver.addCallback("/SPIN/*/*", self.spin_any_any_handler)
            #self.info_receiver.addCallback("/SPIN/__server__", self.recv_spin_server)
            self.info_receiver.setFallback(self.scene_channel_fallback)
        return defer.succeed(None)

    def _start_scene_sender(self):
        """
        Starts an OSC sender to send messages to a SPIN server.
        @rettype: L{twisted.internet.defer.Deferred}
        """
        server_infos = self.servers[self.current_server_id]
        
        #send_addr = server_infos.server_recv_addr
        #send_port = server_infos.server_recv_port
        
        self.scene_sender = async.DatagramClientProtocol()
        self._scene_sender_protocol = reactor.listenMulticast(0, self.scene_sender)
        self._set_multicast_options_for_sender(self._scene_sender_protocol)
    
    def _set_multicast_options_for_sender(self, sender):
        """
        Sets the TTL, and stuff for a MulticastDatagramServerProtocol.
        See http://twistedmatrix.com/documents/10.1.0/api/twisted.internet.interfaces.IMulticastTransport.html
        """
        # print("Sender is a " + str(type(sender)) + ": " + str(dir(sender)))
        previous_ttl = sender.getTTL()
        #FIXME:2010-07-28:aalex: I think we don't need any TTL here at all.
        log.info("Previous TTL for the sender socket: %s" % (previous_ttl))
        log.info("We set the TTL to 3")
        sender.setTTL(3)

    def is_connected(self): 
        """
        @rtype: C{bool}
        """
        return self._scene_receiver_protocol is not None
    
    def disconnect_from_current_server(self):
        """
        @rtype: L{twisted.internet.defer.Deferred}
        """
        if not self.is_connected():
            return defer.succeed(None)
        else: 
            if self._scene_receiver_protocol is not None: #redondant
                deferred = self._scene_receiver_protocol.stopListening()
                self.gui.update_connected_state(False) # FIXME
                if deferred is None:
                    return defer.succeed(None)
                else:
                    return deferred
            else:
                return defer.succeed(None)
        return defer.succeed(None)
        
    def spin_any_handler(self, message, address):
        """
        Handles /SPIN/* messages from the scene channel
        """
        log.debug("spin_any: Got %s" % (message))
        tokens = message.address.split("/")
        scene_id = tokens[2]
        if scene_id == self.current_server_id:
            arguments = message.getValues()
            try:
                if arguments[0] == "nodeList":
                    node_type = arguments[1]
                    self._handle_node_list(node_type, arguments[2:])
                elif arguments[0] == "deleteNode":
                    node_id = arguments[1]
                    self._handle_delete_node(node_id)
                else:
                    log.debug("Received %s" % (message))
            except KeyError, e:
                log.error(str(e))
        else:
            #log.debug("spin_any: Got %s from %s. (for %s not for %s)" % (message, address, scene_id, self.current_server_id))
            pass

    def _handle_delete_node(self, node_id):
        """
        handles /SPIN/<scene> deleteNode <node_id>
        """
        DELETE_THEM = True # False
        log.warning("Node %s has been deleted." % (node_id))
        current_scene = self.get_current_scene()
        for node_type in current_scene.all_nodes.iterkeys():
            if node_id in current_scene.all_nodes[node_type]:
                if DELETE_THEM:
                    del current_scene.all_nodes[node_type]
                    log.debug("Stopped tracking %s since it has been deleted." % (node_id))
                break
        if node_id in current_scene.user_nodes and node_id != self.my_user_id:
            if DELETE_THEM:
                self._stop_streaming_with_user(node_id)
                del current_scene.user_nodes[node_id]
    
    def _stop_streaming_with_all_user(self):
        """
        in the current scene.
        """
        log.debug("Stopping to stream with all users!")
        current_scene = self.get_current_scene()
        for user_id in current_scene.user_nodes.iterkeys():
            if user_id != self.my_user_id:
                self._stop_streaming_with_user(user_id)

    def _delete_all_nodes(self):
        current_scene = self.get_current_scene()
        log.warning("Deleting all our nodes tracking !")
        current_scene.all_nodes = {}
        current_scene.user_nodes = {}
    
    def _stop_streaming_with_user(self, user_id):
        """
        Checks if streaming and stop if so.
        """
        log.debug("_stop_streaming_with_user %s" % (user_id))
        user_node_info = self.get_all_user_nodes()[user_id]
        if user_node_info.streaming_is_on:
            log.warning("Will stop streaming with %s." % (user_id))
            self.app.cameras_manager.stop_streamers_with_peer(user_node_info)
            self.stopped_streaming_with_user_signal(self.current_server_id, user_id)
        else:
            log.debug("We were not streaming with %s" % (user_id))
    
    def _handle_node_list(self, node_type, node_list):
        """
        Called from spin_any_handler for /SPIN/* nodeList 
        """
        #log.debug("Received list of %s nodes: %s" % (node_type, node_list))
        if node_list == ["NULL"]:
            node_list = []
        if node_type == "UserNode":
            self._store_user_nodes(node_list)
        else:
            self.get_current_scene().all_nodes[node_type] = node_list
            
            #scene_info = self.get_current_scene()
            # log.debug("TODO: store every node, just for info")
            
    def _store_user_nodes(self, user_nodes):
        """
        Called when there new user nodes that are detected.
        
        @param user_nodes: list of user node ID.
        @type user_nodes: C{list}
        """
        #TODO: remove the node if not listed anymore
        log.debug("User nodes: %s" % (str(user_nodes)))
        
        for user_node in user_nodes:
            if user_node not in self.get_current_scene().user_nodes.keys():
                if user_node != self.my_user_id: #Not able to see myself right now.
                    self._create_billboards_for_user_node(user_node)
                self.get_current_scene().user_nodes[user_node] = UserNodeInfo(user_node)

    def _create_billboards_for_user_node(self, other_node):
        """
        Create the video billboards for one user node

        The idea here is to be able to see someone by his four sides. 
        We stream video from 4 IIDC cameras with milhouse. (part of the Scenic software suite)
        We use a share video texture to put the resulting image into OSG.
        Now, the user has four billboards in OSG. We need to calculate the angle from which we see him.
        When we know it, we can switch the billboard texture ID, to see him from the right camera.

        @param other_node: user node ID.
        @type other_node: C{str}
        """
        # using_fake_images = False
        
        log.debug("calling _create_billboards_for_user_node(%s)" % (other_node))
        scene_path = "/SPIN/%s" % (self.current_server_id)
        billboard_name = self._get_shapenode_for_user(other_node)
        billboard_path = "%s/%s" % (scene_path, billboard_name)
        log.info("Creating a billboard seen by us for %s" % (other_node))
        # create it:
        bundle = osc.Bundle()
        self.send_element(osc.Message(scene_path, "createNode", other_node, "UserNode"))
        self.send_element(osc.Message(scene_path, "createNode", billboard_name, "ShapeNode"))
        self.send_element(bundle)
        # set its attributes:
        bundle = osc.Bundle()
        bundle.add(osc.Message(billboard_path, "setParent", other_node))
        bundle.add(osc.Message(billboard_path, "setTranslation", 0.0, 0.0, 1.5))
        bundle.add(osc.Message(billboard_path, "setOrientation", 0.0, 0.0, 180.0))
        bundle.add(osc.Message(billboard_path, "setBillboard", 0.0))
        bundle.add(osc.Message(billboard_path, "setScale", 2.666, 1.0, 2.0))
        bundle.add(osc.Message(billboard_path, "setShape", 6.0))
        bundle.add(osc.Message(billboard_path, "setLighting", 0.0))
        bundle.add(osc.Message(billboard_path, "setContext", self.my_user_id)) # XXX: Only seen by us!
        self.send_element(bundle)
        
#        if using_fake_images:
#            self._create_state_set_images(other_node)
#            # just a test:
#            state_set_name = "%s-%s" % (other_node, "north")
#            self.send_element(osc.Message(billboard_path, "setStateSet", state_set_name))
#        else:
#            pass
#            # self._create_state_set_sharedvideotextures(other_node)
#            # state_set_name = "%s-%s" % (billboard_name, "1")
#            # self.send_to_node_in_scene(billboard_name, "setStateSet", state_set_name)

    def spin_any_any_handler(self, message, address):
        """
        Handles the /SPIN/*/* messages from the scene channel
        
        Useful to handle the following first arguments:
         * global6DOF (calls handle_user_6dof)
        """
        log.debug("spin_any: Got %s" % (message))
        tokens = message.address.split("/")
        scene_id = tokens[2]
        obj_id = tokens[3]
        if scene_id == self.current_server_id:
            log.debug("Received %s" % (message))
            method = message.arguments[0].value
            if obj_id in self.get_all_user_nodes().keys():
                if method == "global6DOF":
                    self._handle_user_6dof(obj_id, message)
                elif method == "setParam":
                    self._handle_user_param(obj_id, message)
            else:
                pass
                #log.debug("Node ID %s is not in %s" % (obj_id, self.get_all_user_nodes()))
        else:
            pass 
            #log.debug("spin_any_any: Wrong scene %s. Our scene is %s. Got %s from %s." % (scene_id, self.current_server_id, message, address))

    def _handle_user_param(self, user_id, message):
        """
        Handles /SPIN/<scene>/<node> setParam <key> <value> for UserNode nodes
        """
        log.debug("_handle_user_param %s %s" % (user_id, message))
        all_user_nodes = self.get_all_user_nodes()
        
        key = message.arguments[1].value
        value = message.arguments[2].value
        if user_id in all_user_nodes.keys():
            if not all_user_nodes[user_id].params.has_key(key):
                log.debug("Got param %s=%s for UserNode %s" % (key, value, user_id))
                all_user_nodes[user_id].params[key] = value
            elif all_user_nodes[user_id].params[key] != value:
                all_user_nodes[user_id].params[key] = value
                log.info("Got new param value %s=%s for UserNode %s" % (key, value, user_id))
            else:
                log.debug("We already had that param")
            # start to stream with peer if ready:
            if user_id != self.my_user_id:
                self._start_streaming_if_ready(user_id)
    
        #if user_id != self.my_user_id:
        #    if user_id in all_user_nodes.keys():
        #        log.debug("This param is for user %s" % (user_id))
        #        
        #        
        #        #if key in self.app.config.__dict__.keys():
        #        #        
        #        #    if key != "cameras":
        #        #        cast = type(self.app.config.__dict__[key])
        #        #        casted_value = cast(value)
        #        #        if not all_user_nodes[user_id].params.has_key(key):
        #        #            all_user_nodes[user_id].params[key] = casted_value
        #        #        elif all_user_nodes[user_id].params[key] != casted_value:
        #        #            all_user_nodes[user_id].params[key] = casted_value
        #        #else:
        #        #    log.warning("Unknown param key %s with value %s" % (key, value))

    def _start_streaming_if_ready(self, user_id):
        """
        Checks if we got all params for a UserNode that we need to start streaming.
        If it's OK, ask the camera manager to start the streamers.
        """
        # TODO: set the shared video texture ID param
        user_node_info = self.get_all_user_nodes()[user_id]
        has_all_params = True
        keys = cameras.CamerasConfig().__dict__.keys()
        keys.append("number_of_cameras")
        for key in keys:
            if key == "cameras":
                pass
            else:
                if not user_node_info.params.has_key(key):
                    log.debug("UserNode %s does not have param %s set yet." % (user_id, key))
                    has_all_params = False

        if user_node_info.params.has_key("number_of_cameras"):
            number_of_cameras = int(user_node_info.params["number_of_cameras"])
            for number in range(number_of_cameras):
                key = "cameras[%d]" % (number + 1)
                if not user_node_info.params.has_key(key):
                    log.debug("UserNode %s does not have param %s." % (user_node_info.name, key))
                    has_all_params = False
                
        if has_all_params:
            if not user_node_info.streaming_is_on:
                log.info("Will start streaming. We have all params to stream with %s" % (user_id))
                self.start_streaming_with_user_signal(self.current_server_id, user_id)
                self.app.cameras_manager.launch_streamers_with_peer(user_node_info)
            else:
                log.debug("Already streaming with %s" % (user_id))
        else:
            log.debug("Not ready to stream with %s yet." % (user_id))
    
    def _handle_user_6dof(self, user_id, message):
        """
        Handles specifically the /SPIN/<scene ID>/<node ID> global6DOF method
        
        Called by spin_any_any_handler.
        """
        # /SPIN/spinicserver/dummy ,sffffff s:global6DOF  f:-0.0416663214564  f:-10.7916717529  f:0.5  f:0.0  f:-0.0  f:0.0 
        log.debug("6DOF message received for user %s" % (user_id))
        args = message.getValues()
        
        user_info = self.get_current_scene().user_nodes[user_id]
        #if user_info.current_camera is None and user_id != self.my_user_id:
        #    textures = self.get_textures_for_user(user_id)
        #    try:
        #        user_info.current_camera = textures[0] #self.cameras[0] # sets the camera for this user to the default one.
        #    except IndexError, e:
        #        log.error(str(e))
        position = args[1:4] # we don't need the first string
        orientation = args[4:7] # we don't need the first string
        user_info.position = position
        user_info.orientation = orientation
        # Now, let's do it:
        self._calculate_angles_between_each_user()

    def _calculate_angles_between_each_user(self):
        """
        Called by handle_user_6dof. (which is called by spin_any_any_handler)
        """
        my_user_pos = None
        try:
            my_user_pos = self.get_current_scene().user_nodes[self.my_user_id].position
        except KeyError, e:
            log.warning("We don't have our user's (%s) coordinates yet." % (self.my_user_id))
        else:
            my_x = my_user_pos[0]
            my_y = my_user_pos[1]
            for user_id, user_info in self.get_current_scene().user_nodes.iteritems():
                if user_id != self.my_user_id:
                    textures = self.get_textures_for_user(user_id)
                    num_cameras = len(textures)
                    if num_cameras == 0:
                        log.debug("User %s has no shared video textures!" % (user_id))
                    else:
                        angle_between_each_camera = 360.0 / num_cameras
                        pos = user_info.position
                        orientation = user_info.orientation
                        x = pos[0]
                        y = pos[1]
                        # z = pos[2]
                        # pitch  = orientation[0]
                        # roll = orientation[1]
                        yaw = orientation[2]
                        
                        angle = (math.degrees(math.atan2(my_y - y, my_x - x))  - 90 - yaw * -1 ) % 360
                        log.debug("The angle from which we see %s is %s" % (user_id, angle))
                        old_camera = user_info.current_camera
                        new_camera = None
                        offset = (angle_between_each_camera / 2) - 90
                        new_camera_number = int(((angle - offset) % 360.0) / angle_between_each_camera)
                        log.debug("Texture for %s is %d (%s)" % (user_id, new_camera_number, textures[new_camera_number]))
                        try:
                            new_camera = textures[new_camera_number]
                        except KeyError, e:
                            log.error("Bad camera number: %s" % (e))
                        else:
                            if new_camera != old_camera:
                                log.info("SWITCHING TO CAMERA %s for us looking at user %s ------------- " % (new_camera, user_id))
                                # save the new camera ID for that user node
                                user_info.current_camera = new_camera
                                # send the OSC messages
                                # self._switch_camera_for_user(new_camera, user_id)
                                self.choose_sharedvideotexture_for_user(user_id, new_camera)
    
#    def _switch_camera_for_user(self, camera_id, user_id):
#        """
#        Sends OSC messages to switch the state of the stateset for a UserNode in our context.
#        """
#        log.debug("_switch_camera_for_user %s %s" % (camera_id, user_id))
#        billboard_name = "%s-seenby-%s" % (user_id, self.my_user_id)
#        state_set_name = "%s-%s" % (user_id, camera_id)
#        self.send_to_node_in_scene(billboard_name, "setStateSet", state_set_name)

    def spin_user_handler(self, message, address):
        """
        Handles /SPIN/__user__ messages from the info channel. 
        
        OSC arguments: id rxAddr rxPort
        """
        # tokens = message.address.split("/")
        log.debug("spin_user_handler: Got %s from %s" % (message, address))
    
    def scene_channel_fallback(self, message, address):
        """
        Fallback for the scene channel.
        """
        log.debug("scene fallback: Got %s from %s" % (message, address))

    def info_channel_fallback(self, message, address):
        """
        Fallback for the info channel. 
        """
        log.debug("info fallback: Got %s from %s" % (message, address))

    def get_all_user_nodes(self):
        """
        Returns a dict of user node for the current scene ID.
        @rettype: C{dict}
        """
        return self.get_current_scene().user_nodes

    def get_param_value_for_user(self, user_id, param_name):
        """
        Returns a param value for a given user id.

        @return: None or the value as a C{str}.
        """
        try:
            user_node_info = self.get_all_user_nodes()[user_id]
        except KeyError, e:
            log.warning("We don't have user info for " + user_id + ": " + str(e))
            return None
        else:
            try:
                value = user_node_info.params[param_name]
            except KeyError, e:
                log.warning("We don't have param " + param_name + " for " + user_id + ": " + str(e))
                return None
            else:
                return value

    def _set_params_for_my_user_node(self):
        """
        Populate the server with my user node info.
        """
        log.debug("_set_params_for_my_user_node")
        # re-create it just in case
        self.send_to_scene("createNode", self.my_user_id, "UserNode")
        #FIXME: should we wait a bit here?
        # set the params
        params = self.app.cameras_manager.get_params_for_my_user_node()
        for key, value in params.iteritems():
            #FIXME: it seems like cameras are sent last...
            self.send_to_node_in_scene(self.my_user_id, "setParam", key, str(value))
    
    def _create_statesets_for_my_user_and_cameras(self):
        """
        Everyone creates their own statesets at init time.
        Those get sent to all other users.
        So, you don't create statesets for other users. only yourself.
        
        Those statesets store the camera ID and hostname from which it is sent.
        They are also the name of the shared memory ID for the shared video texture.
        
        We must send:
         * /SPIN/<scene>/alice-seenby-bob setStateSet 10002000300040@bob
         * /SPIN/<scene>/10002000300040@bob setTextureID 10002000300040@bob
        """
        _cameras = self.app.cameras_manager.get_my_cameras()
        for cam in _cameras:
            (camera_id, hostname, sender_port) = cameras.parse_camera_scheme(cam)
            stateset_id = cameras.get_texture_id_from_camera_codename(cam) #  "%s@%s" % (camera_id, hostname)
            self.send_to_scene("createStateSet", stateset_id, "SharedVideoTexture")
            self.send_to_node_in_scene(stateset_id, "setTextureID", stateset_id) # same as its own name!
        
    def choose_sharedvideotexture_for_user(self, user_id, texture_id):
        """
        Sets up the shared video texture for a given user ID.
         * Create a state set for each of the video streams we get from him
         * Set the texture ID 
        
        At this point:
        The ShapeNode alice-seenby-bob already exists. (and is in my context, so I am the only one to see it)
        (that is also given as a shared texture ID to milhouse receiver)
        
        After you create the stateset, you still have to setTextureID
        We cannot create stateSet at init time, but must wait after we know all the other user node's params.
        """
        self.send_to_node_in_scene(self._get_shapenode_for_user(user_id), "setStateSet", texture_id)
    
    def get_textures_for_user(self, user_id):
        ret = []
        try:
            user_node_info = self.get_all_user_nodes()[user_id]
        except KeyError, e:
            log.warning("We don't have user info yet for " + user_id + ": " + str(e))
        else:
            if user_node_info.streaming_is_on:
                for cam in cameras.create_camera_config_for_user_node_info(user_node_info).cameras:
                    ret.append(cameras.get_texture_id_from_camera_codename(cam))
            else:
                log.debug("get_textures_for_user: Not yet streaming with %s" % (user_id))
        return ret
                
    def _get_shapenode_for_user(self, user_id):
        """
        Those ID look like: alice-seenby-bob. (we are bob)
        @type user_id: C{str}
        """
        return "%s-seenby-%s" % (user_id, self.my_user_id)
    
#    def _create_state_set_images(self, user_id):
#        """
#        Create the ... state sets with the images
#        @type user_id: C{str}
#        (it will soon be cameras)
#        """
#        # For each image: Create state set, load image and create textures:
#        # create the state sets:
#        for name in self.cameras:
#            # TODO: give camera ID
#            stateset_id = "%s-%s" % (user_id, name)
#            self.send_to_scene("createStateSet", stateset_id, "ImageTexture") 
#            #TODO: create Texture ID (shared video memory location) : SPIN/scene/object setTextureID
#            #TODO: hostname:camera
#            #TODO: if my hostname doesn't match... I create it...
#
#        # load the image files:
#        for image_name in self.cameras:
#            node_id = "%s-%s" % (user_id, image_name)
#            self.send_to_node_in_scene(node_id, "setPath", "~/src/postures/trunk/prototypes/%s.jpg" % (image_name))
        
    def rotate_left(self):
        """
        Rotates our viewer to the left.
        """
        #log.debug("rotate_left")
        self._rotate(-5)
    
    def _rotate(self, how_much):
        """
        Actually sends the setOrientation method for our spinviewer user node.
        """
        self.my_yaw += how_much
        self.send_to_node_in_scene(self.my_user_id, "setOrientation", 0.0, 0.0, self.my_yaw)
        
    def rotate_right(self):
        """
        Rotates our viewer to the right.
        """
        #log.debug("rotate_right")
        self._rotate(5)

    def get_current_scene(self):
        """
        Returns the current SceneInfo object. Creates it if it doesn't exist.
        @rtype L{SceneInfo}
        """
        if not self.scenes.has_key(self.current_server_id):
            self.scenes[self.current_server_id] = SceneInfo()
        return self.scenes[self.current_server_id]
    
    def send_refresh(self):
        """
        Calls the scene's refresh method
        """
        self.send_to_scene("refresh")
    
    def send_clear(self):
        """
        Calls the scene's clear method
        """
        #TODO: remove this button
        self.send_to_scene("clear")

    def send_create_grid(self):
        self.send_to_scene("createNode", "grid", "GridNode")

#TODO: create another GUI for creating/moving one dummy model around. 
# it will be useful for prototypes.

