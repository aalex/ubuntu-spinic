
"""
Audio connections manager for Spinic.

Uses plumberjack.py
"""
from spinic import plumberjack
from lunch import logger
from twisted.internet import defer

log = logger.start(name="audioconnector")

class AudioConnector(object):
    """
    Manages audio connections with JACK for spinic. (SPIN and Milhouse)
    """
    def __init__(self, app):
        self.app = app
        self.plumber = plumberjack.PlumberJack()
        
        self._plug_input_to_every_sender()
        self._plug_pd_outputs()
        self._connect_signals()

    def _connect_signals(self):
        self.app.osc_interface.connected_to_scene_signal.connect(self.on_connected_to_scene)
        self.app.osc_interface.start_streaming_with_user_signal.connect(self.on_start_streaming_with_user)
        self.app.osc_interface.stopped_streaming_with_user_signal.connect(self.on_stopped_streaming_with_user)

    def _plug_input_to_every_sender(self):
        name = "to_all_milhouse" 
        text = """(connect-exclusive "system.*:capture_1" "milhouse.*:in.*" )""" # ; all use the same
        self.plumber.add_rule(name, text)
        self.plumber.write_config_to_file()

    def _plug_pd_outputs(self):
        #TODO: figure out how many outputs we have.
        rules = [        
            """(connect-exclusive "pure_data.*:output0" "system:playback_1")""",
            """(connect-exclusive "pure_data.*:output1" "system:playback_2")""",
            """(connect-exclusive "pure_data.*:output2" "system:playback_3")""",
            """(connect-exclusive "pure_data.*:output3" "system:playback_4")""",
            """(connect-exclusive "pure_data.*:output4" "system:playback_5")""",
            """(connect-exclusive "pure_data.*:output5" "system:playback_6")""",
            """(connect-exclusive "pure_data.*:output6" "system:playback_7")""",
            ]
        count = 0
        for rule in rules:
            name = "pd_out_%d" % (count)
            count += 1
            self.plumber.add_rule(name, rule)
        self.plumber.write_config_to_file()

#    def create_jack_plumbing_command(self):
#        return "jack.plumbing"
        
    def disconnect_pd_and_system(self):
        """
        Pd auto-connects itself to the system audio sources and sinks. 
        This attemps to disconnect it.
        
        Should be called right after we start pd, from the L{spinic.lauching.ProcessLauncher}
        """
        deferreds = []
        src_sinks = [
            ["system:capture_1", "pure_data_0:input0"],
            ["system:capture_2", "pure_data_0:input1"],
            ["system:capture_3", "pure_data_0:input2"],
            ["system:capture_4", "pure_data_0:input3"],
            ["system:capture_5", "pure_data_0:input4"],
            ["system:capture_6", "pure_data_0:input5"],
            ["system:capture_7", "pure_data_0:input6"],
            ["system:capture_8", "pure_data_0:input7"],
            ]
        for src, sink in src_sinks:
            deferreds.append(plumberjack.jack_disconnect(src, sink))
        return defer.DeferredList(deferreds)

    def on_connected_to_scene(self, scene_id):
        """
        Slot for the L{spinic.osc.SpinicOscInterface.connected_to_scene_signal} signal.
        """
        log.debug("on_connected_to_scene")
    
    def on_start_streaming_with_user(self, scene_id, user_id):
        """
        Slot for the L{spinic.osc.SpinicOscInterface.start_streaming_with_user_signal} signal.
        """
        #FIXME: it seems like this is never called!
        log.debug("on_start_streaming_with_user")
        name = "from_%s" % (user_id)
        milhouse_jack_client_name = create_jack_client_name(user_id, "receiver")
        param_name = "user_audio_src"
        pd_adc_number = self.app.osc_interface.get_param_value_for_user(user_id, param_name) # in the range [1,n]
        if pd_adc_number is None:
            log.error("Could not determine pd audio input number for user %s so we cannot set the JACK routing for it." % (user_id))
        elif pd_adc_number == "0":
            log.error("An audio input number of 0 is impossible for user %s" % (user_id))
        else:
            text = """(connect-exclusive "milhouse.*:out_%s*.*" "pure_data.*:input%d")""" % (milhouse_jack_client_name, int(pd_adc_number) - 1)
            self.plumber.add_rule(name, text)
            self.plumber.write_config_to_file()
    
    def on_stopped_streaming_with_user(self, scene_id, user_id):
        """
        Slot for the L{spinic.osc.SpinicOscInterface.stopped_streaming_with_user_signal} signal.
        """
        #FIXME: it seems like this is never called!
        log.debug("on_stopped_streaming_with_user")
        name = "from_%s" % (user_id)
        if self.plumber.get_rule(name) is not None:
            self.plumber.remove_rule(name)
            self.plumber.write_config_to_file()
        else:
            log.error("Could not find a jack.plumbing rule for %s" % (name))

    def __del__(self):
        """
        Might restore the original config file... But we don't enable it right now.
        """
        del self.plumber

def create_jack_client_name(user_id, role=None):
    """
    @param role: Either "sender" or "receiver"
    @type role: C{str}
    @rtype: C{str}
    """
    prefix = ""
    if role == "sender":
        prefix = "s_"
    elif role == "receiver":
        prefix = "r_"
    else:
        raise RuntimeError("You must provide either the sender or receiver role.")
    return "%s%s" % (prefix, user_id)

