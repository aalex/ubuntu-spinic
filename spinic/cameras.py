#!/usr/bin/env python
"""
Tools to parse the config file. (for the cameras)
"""
import os
import json
assert(json.loads) # need Python >= 2.6
import glob
from lunch import logger
from spinic import audioconnector

log = logger.start(name="cameras")

SHM_PREFIX = "spinic-"

class CamerasConfig(object):
    """
    System-wide configuration for the cameras, as read in the cameras config file.
    """
    def __init__(self):
        # default values:
        self.receiveraddress = "127.0.0.1"
        self.videosource = "videotestsrc" # "dc1394src"
        self.videocodec = "h263"
        self.videobitrate = 75000
        self.framerate = 15
        self.grayscale = True
        self.height = 480
        self.width = 640
        self.display = ":0.0"
        self.user_audio_src = 1 # as seen by pd [adc] Must be unique for each spinics in a scene.
        self.audio_outputs_layout = "stereo" # How speakers are set up
        self.send_audio_port = 10000
        self.cameras = [] # list of 00000000000000@10.10.10.111:10000 which are <camera_id>@<sending_address>:<sending_port>
    
def parse_camera_scheme(txt):
    """
    Cameras are defined as strings like this: <camera ID>@<hostname>:<sender port>
    
    Might raise a RuntimeError
    
    Returns a tuple like this: (camera_id, hostname, sender_port)
    
    @param txt: Camera setting.
    @type txt: C{str}
    @rtype: C{tuple}
    """
    camera_id = None
    hostname = None
    sender_port = None
    
    try:
        camera_id = txt.split("@")[0]
    except IndexError, e:
        raise RuntimeError(str(e) + " for camera scheme %s" % (txt))
    try:
        hostname = txt.split("@")[1].split(":")[0]
    except IndexError, e:
        raise RuntimeError(str(e) + " for camera scheme %s" % (txt))
    try:
        sender_port = int(txt.split("@")[1].split(":")[1])
    except IndexError, e:
        raise RuntimeError(str(e) + " for camera scheme %s" % (txt))
    except ValueError, e:
        raise RuntimeError(str(e) + " for camera scheme %s" % (txt))
    # log.debug("Camera %s on %s sends on port %d" % (camera_id, hostname, sender_port))
    return (camera_id, hostname, sender_port)

def get_commands_to_launch_for_pair(local_config, remote_config, user_id):
    """
    Returns a dict of commands to launch locally for the given remote camera config.

    Keys are their identifier.
    
    @param local_config: Local config
    @type local_config: L{CamerasConfig}
    @param remote_config: Remote config
    @type remote_config: L{CamerasConfig}
    @rtype: C{dict}
    """
    def _get_milhouse_options_for_sender(config):
        """
        @param config: Local config.
        @type config: L{spinic.cameras.CamerasConfig}
        """
        ret = "milhouse -s --videosource %(videosource)s --width %(width)d --height %(height)d --videobitrate %(videobitrate)d --videocodec %(videocodec)s --framerate %(framerate)d" % {
                "videosource": config.videosource,
                "width": int(config.width),
                "height": int(config.height), 
                "videobitrate": int(config.videobitrate), 
                "videocodec": config.videocodec, 
                "framerate": int(config.framerate),
            }
        if config.grayscale:
            ret += " --grayscale"
        return ret
            
    def _get_milhouse_options_for_receiver(config):
        """
        @param config: Remote config.
        @type config: L{spinic.cameras.CamerasConfig}
        """
        return "milhouse -r --width %(width)d --height %(height)d --videocodec %(videocodec)s" % {
                "width": int(config.width),
                "height": int(config.height), 
                "videocodec": config.videocodec,
            }
    
    def _get_audio_sender_for_peer(config):
        """
        @param config: Local config.
        @type config: L{spinic.cameras.CamerasConfig}
        """
        audioport = config.send_audio_port
        sender_cmd = "milhouse -s --numchannels 1 --audioport %(audioport)d --audiocodec raw --audiosource jackaudiosrc --disable-jack-autoconnect --jack-client-name %(jackclientname)s" % {
                "audioport": int(audioport),
                "jackclientname": audioconnector.create_jack_client_name(user_id, "sender"),
            }
        return sender_cmd

    def _get_audio_receiver_for_peer(config):
        """
        @param config: Remote config.
        @type config: L{spinic.cameras.CamerasConfig}
        """
        audioport = config.send_audio_port
        receiver_cmd = "milhouse -r --numchannels 1 --audioport %(audioport)d --audiocodec raw --audiosink jackaudiosink --disable-jack-autoconnect --jack-client-name %(jackclientname)s" % {
                "audioport": int(audioport),
                "jackclientname": audioconnector.create_jack_client_name(user_id, "receiver"),
            }
        return receiver_cmd
        
    ret = {}
    # ------------------------------ LOCAL SENDER -----------
    # senders are very likely to be on a different host
    cam_number = 1 # incrementing this XXX
    for local_cam in local_config.cameras:
        key = "send_%s_%d" % (user_id, cam_number)
        txt = _get_milhouse_options_for_sender(local_config)
        camera_id, sender_hostname, sender_port = parse_camera_scheme(local_cam)
        #TODO: give it the camera ID
        txt += " --address %(address)s --videoport %(port)d" % {"address": remote_config.receiveraddress, "port": sender_port}
        if local_config.videosource == "dc1394src":
            txt += " --camera-guid %s" % (camera_id)
        # add it to the dict and increment cam_number:
        ret[key] = {
            "command": txt, 
            "host": sender_hostname 
            }
        cam_number += 1
        
    # ------------------------------ LOCAL RECEIVER -----------
    # XXX receivers are always on the same host as spinic
    cam_number = 1 # resetting this
    for remote_cam in remote_config.cameras:
        key = "recv_%s_%d" % (user_id, cam_number)
        txt = _get_milhouse_options_for_receiver(remote_config)
        camera_id, sender_hostname, sender_port = parse_camera_scheme(remote_cam)
        txt += " --address %(address)s --videoport %(port)d" % {"address": sender_hostname, "port": sender_port}
        shared_video_id = get_texture_id_from_camera_codename(remote_cam)
        txt += " --videosink sharedvideosink --shared-video-id %s" % (shared_video_id)
        txt += " --text-overlay \"%s %d\"" % (user_id, cam_number)
        txt += " --flip-video vertical-flip"  # GStreamer texture are upside-down
        # add it to the dict and increment cam_number:
        ret[key] = {
            "command": txt, 
            "host": None
            # TODO: add username
            }
        cam_number += 1

    # and now, the audio!
    ret["send_%s_AUDIO" % (user_id)] = {
        "command": _get_audio_sender_for_peer(local_config) + " --address %s" % (remote_config.receiveraddress),
        "host": None
        }
    ret["recv_%s_AUDIO" % (user_id)] = {
        "command": _get_audio_receiver_for_peer(remote_config) + " --address %s" % (remote_config.receiveraddress),
        "host": None
        }
    return ret

def get_texture_id_from_camera_codename(camera):
    """
    Given a camera codename, returns the shvid texture id for it.
    
    @param camera: id@host:port
    @type camera: C{str}
    @rtype: C{str}
    @return: ID for the shared video memory
    @rtype: C{str}
    """
    camera_id, hostname, sender_port = parse_camera_scheme(camera)
    return "%s%s@%s" % (SHM_PREFIX, camera_id, hostname)

def clear_all_dev_shm(delete_them=True):
    # TODO:2010-07-28:aalex:We could clear only those started by this spinic
    files = glob.glob("/dev/shm/%s*" % (SHM_PREFIX))
    if len(files) != 0:
        log.warning("Found %d shared memory files that should be deleted: %s" % (len(files), " ".join(files)))
        if delete_them:
            for f in files:
                try:
                    os.remove(f)
                except os.OSError, e:
                    log.error("An error occurred while deleting %s: %s" % (f, e))
                else:
                    log.warning("Deleted %s" % (f))

def create_camera_config_for_user_node_info(user_node_info):
    """
    @param user_node_info: L{spinic.osc.UserNodeInfo}
    @rtype:  L{CamerasConfig}
    """
    ret = CamerasConfig()
    def _read_param(key):
        if user_node_info.params.has_key(key):
            value = user_node_info.params[key]
            ret.__dict__[key] = value
    # XXX: these are super important!
    #TODO: should be automatic
    _read_param("receiveraddress")
    _read_param("videosource")
    _read_param("videobitrate")
    _read_param("framerate")
    _read_param("grayscale")
    _read_param("width")
    _read_param("height")
    _read_param("send_audio_port")
    _read_param("user_audio_src")
    
    cam_number = 1
    has_more = True
    while has_more:
        key = "cameras[%d]" % (cam_number)
        if user_node_info.params.has_key(key):
            value = user_node_info.params[key]
            ret.cameras.append(value)
            cam_number += 1
        else:
            has_more = False
    return ret

class CamerasManager(object):
    """
    Manages the list of cameras.
    """
    def __init__(self, app):
        # attributes:
        self.app = app
        self.cameras_config = CamerasConfig()
        
        # take action:
        self.cameras_config.receiveraddress = self.app.config.user_id # FIXME
        self.parse_config_file(self.app.config.cameras_config_file)

    def get_my_cameras(self):
        """
        Returns the list of my user's camera codename. 
        It's made of the camera ID, origin hostname and destination port.
        @rtype: C{list}
        """
        return self.cameras_config.cameras

    def launch_streamers_with_peer(self, user_node_info):
        log.info("CamerasManager.launch_streamers_with_peer(%s)" % (user_node_info.name))
        #TODO: set the same shared texture id in SPIN
        if user_node_info.streaming_is_on:
            log.warning("Streamers are already running for %s" % (user_node_info.name))
        else:
            remote_config = create_camera_config_for_user_node_info(user_node_info)
            local_config = self.cameras_config
            all_commands = get_commands_to_launch_for_pair(local_config, remote_config, user_node_info.name)
            display = local_config.display 
            user_node_info.streaming_is_on = True
            for identifier, data in all_commands.iteritems():
                command_txt = data["command"]
                host = data["host"] # receivers are on the same host. sender might very well be on a different host.
                self.app.launcher.add_command_on_host(command_txt, identifier, hostname=host, display=display)

    def stop_streamers_with_peer(self, user_node_info):
        log.info("CamerasManager.stop_streamers_with_peer(%s)" % (user_node_info.name))
        if not user_node_info.streaming_is_on:
            log.warning("Streamers are not running for %s" % (user_node_info.name))
        else:
            remote_config = create_camera_config_for_user_node_info(user_node_info)
            local_config = self.cameras_config
            all_commands = get_commands_to_launch_for_pair(local_config, remote_config, user_node_info.name)
            user_node_info.streaming_is_on = False
            for identifier, data in all_commands.iteritems():
                command = data["command"]
                self._remove_command(identifier)

    def _remove_command(self, identifier):
        self.app.launcher.remove_command(identifier)

        
    def parse_config_file(self, file_path=None):
        """
        Reads the JSON config file and return the list of cameras found there.
        Returns None if the file is not found.
        @param file_path: Path to the config file.
        @type file_path: str
        @rtype: list
        """
        if file_path is None:
            raise RuntimeError("You must specify a path for the config file.")
        file_name = os.path.expanduser(file_path)
        if not os.path.exists(file_name):
            log.warning("Could not find any spinic config file.")
            return None
        if not os.path.isfile(file_name):
            raise RuntimeError("The config file %s should be a file." % (file_name))
        log.info("Reading JSON file %s" % (file_path))
        config_file = open(file_name, "r")
        text = config_file.read()
        config_file.close()
        #log.debug("Found text %s" % (text))
        try:
            data = json.loads(text)
        except ValueError, e:
            raise RuntimeError("Found an error in the JSON config file %s: %s" % (file_path, e))
        if type(data) != dict:
            raise RuntimeError("The JSON config file should contain a dict.")
        log.debug("Found data %s" % (data))
        
        # Now, let's set the attributes of our CamerasConfig instance.
        for key, former_value in self.cameras_config.__dict__.iteritems():
            if key != "cameras": # special case
                if not data.has_key(unicode(key)):
                    log.warning("The configuration file should contain key %s" % (key))
                else:
                    cast = type(former_value)
                    try:
                        value = cast(data[unicode(key)])
                    except ValueError, e:
                        log.error("Error with key %s in the config file: %s" % (key, str(e)))
                    else:
                        log.info("Found config %s = %s" % (key, value))
                        self.cameras_config.__dict__[key] = value

        if not data.has_key(unicode("cameras")):
            log.error("The config file should have a \"cameras\" field.")
        else:
            if type(data[unicode("cameras")]) is not list:
                log.warning("Wrong type for the cameras attribute.")
            else:
                if len(data[unicode("cameras")]) == 0:    
                    log.warning("The list of cameras is empty.")
                else:
                    for camera in data[unicode("cameras")]:
                        if type(camera) != str and type(camera) != unicode:
                            log.error("Camera should be a string in the config file:  %s"  % (camera))
                        else:
                            log.info("Found local camera %s" % (camera))
                            self.cameras_config.cameras.append(str(camera))
        
        # just to validate the camera settings:
        self.get_params_for_my_user_node()

    def get_params_for_my_user_node(self):
        """
        VERY IMPORTANT. Sets the params for the UserNode of this spinic.
        That's where we multicast the info on our cameras.
        
        @rtype: C{dict}
        """
        ret = {}
        number_of_cameras = 0
        for key, value in self.cameras_config.__dict__.iteritems():
            if key != "cameras":
                ret[key] = value
        camera_number = 1 # Camera indices start at 1
        for camera in self.cameras_config.cameras:
            key = "cameras[%d]" % (camera_number)
            ret[key] = camera
            # just to validate the camera settings:
            parse_camera_scheme(camera)
            # increment camera number:
            camera_number += 1
            number_of_cameras += 1

        ret["number_of_cameras"] = number_of_cameras
        return ret

