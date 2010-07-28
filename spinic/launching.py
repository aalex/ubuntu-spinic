#!/usr/bin/env python
"""
Spinic uses lunch master as a library to launch spinviewer and milhouse.
"""
if __name__ == "__main__": # just a reminder
    from twisted.internet import gtk2reactor
    gtk2reactor.install() # has to be done before importing reactor
from twisted.internet import reactor
from twisted.internet import task
from lunch import master
from lunch import gui
from lunch import logger

log = None

class ProcessLauncher(object):
    """
    Process launching with Lunch + a window.

    Might raise a RuntimeError
    """
    def __init__(self, app=None, scene_id="default", spinviewer_fps=30):
        global log
        self.app = app
        self.user_id = self.app.config.user_id
        self.scene_id = scene_id
        self.has_ever_started_viewer = False
        self.spinviewer_fps = spinviewer_fps
        unique_master_id = "spinic"
        log_dir = master.DEFAULT_LOG_DIR
        log_level = 'warning'
        if self.app.config.verbose:
            log_level = 'info'
        if self.app.config.debug:
            log_level = 'debug'
        master.start_logging(log_level=log_level)
        log = logger.start(name="launching")
        pid_file = master.write_master_pid_file(identifier=unique_master_id, directory=log_dir)
        # might raise a RuntimeError:
        self.lunch_master = master.Master(log_dir=log_dir, pid_file=pid_file, verbose=True)
        self.lunch_gui = gui.start_gui(self.lunch_master)
        self._start()
    
    def _start(self):
        """
        Sets up the initial command to launch right away at startup.
        More are added later somewhere else.
        """
        # commands must not be imported before starting the lunch logging
        from lunch import commands
        _command = self._prepare_spin_viewer_command_line()
        self.lunch_master.add_command(commands.Command("ps aux | grep milhouse | grep -v grep", identifier="list_milhouse", respawn=False))
        # self.lunch_master.add_command(commands.Command("rm /dev/shm/spinic-*@*", identifier="clean_shm", respawn=False))
        self.lunch_master.add_command(commands.Command(_command, identifier="spinviewer", enabled=False))
        self.lunch_master.add_command(commands.Command("pd -jack", identifier="puredata", enabled=False)) # this command is changed later on, when we connect to a server
        #self.lunch_master.add_command(commands.Command("spinserver --scene-id %s" % (scene_id), identifier="spinserver"))
        self.lunch_master.add_command(commands.Command("jack.plumbing", identifier="jack_plumbing")) 
    
    def add_command_on_host(self, command_txt, identifier, hostname=None, display=None):
        """
        Use None for localhost.
        """
        from lunch import commands
        env = {}
        if display is not None:
            env["DISPLAY"] = display
        if hostname is None:
            self.lunch_master.add_command(commands.Command(command_txt, identifier=identifier, env=env))
        else:
            self.lunch_master.add_command(commands.Command(command_txt, identifier=identifier, host=hostname, env=env))
        # TODO: allow to remove commands as well...
        # TODO: convert hostname to IP if it is not already an IP.

    def remove_command(self, identifier):
        """
        Wraps the remove_command method of L{lunch.master.Master}
        """
        self.lunch_master.remove_command(identifier)
    
    def _prepare_spin_viewer_command_line(self):
        """
        @rtype: C{str}
        """
        _command = "spinviewer --scene-id %s --framerate %d" % (self.scene_id, self.spinviewer_fps)
        _command += " --user-id %s" % (self.user_id)
        log.info("$ %s" % (_command))
        return _command

    def _prepare_pd_command_line(self):
        patch_name = "spinic.pd"
        inchannels = 8
        outchannels = 4 # TODO: use the info from the config file.
        nogui = not self.app.config.show_puredata_gui
        enable_dsp = True
        # Now, let's prepare the command to launch pd
        user_audio_src = self.app.cameras_manager.cameras_config.user_audio_src
        audio_outputs_layout = self.app.cameras_manager.cameras_config.audio_outputs_layout
        messages = [
            "from_spinic sceneID %s" % (self.scene_id),
            "from_spinic userID %s" % (self.user_id),
            "from_spinic user_audio_src %d" % (user_audio_src),
            "from_spinic audio_outputs_layout %s" % (audio_outputs_layout),
            ]
        if enable_dsp:
            messages.append("pd dsp 1")
        msg_str = "; ".join(messages)
        _command = "pd -jack -inchannels %d -outchannels %d -send \"%s\"" % (inchannels, outchannels, msg_str)
        if nogui:
            _command += " -nogui"
        message = ""
        _command += " %s" % (patch_name)
        log.info("$ %s" % (_command))
        return _command
        
    def switch_to_scene(self, scene_id):
        if scene_id != self.scene_id or not self.has_ever_started_viewer:
            self.has_ever_started_viewer = True
            self.scene_id = scene_id
            # TODO: should be re-launched when we choose a scene in the GUI.

            #FIXME: we should add a method in lunch.commands.Command to update the command line
            #XXX: if those are now running, we'll need to stop and restart them. Right now, we use the hack below. 
            self.lunch_master.commands["spinviewer"].command = self._prepare_spin_viewer_command_line()
            self.lunch_master.commands["spinviewer"].enabled = True # Done by calling restart_all() anyways.
            self.lunch_master.commands["puredata"].command = self._prepare_pd_command_line()
            self.lunch_master.commands["puredata"].enabled = True # Done by calling restart_all() anyways.
            #TODO:2010-07-28:aalex:Should only restart the spinviewer and pd when we switch scene
            self.lunch_master.restart_all()

