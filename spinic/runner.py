#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Spinic SPIN + Lunch + Scenic integration.
"""
import socket
import os
import sys
import gc
import warnings
# HACK to raise an exception when we get a GtkWarning
def custom_show_warning(message, category, filename, lineno, file=None, line=None):
        """ 
        Override warnings.showwarning to raise an exception if GTK cannot open the DISPLAY.
        open the display.
        """
        sys.stdout.write(warnings.formatwarning(message, category, filename, lineno))
        if "could not open display" in message:
            raise RuntimeError("Error: Could not open display. Spinic needs a $DISPLAY.")

warnings.showwarning = custom_show_warning
try:
    from twisted.internet import gtk2reactor
    gtk2reactor.install()
    import gtk
except RuntimeError, e:
    print(str(e))
    sys.exit(1)
if not os.environ.has_key("DISPLAY"):
    print("Error: Could not open display. Spinic needs a $DISPLAY.")
    sys.exit(1)
from twisted.internet import reactor
from twisted.internet import defer
from spinic import spindefaults

DEFAULT_CAMERAS_CONFIG_FILE = "~/.spinic.json"

class Configuration(object):
    """
    Settings for the whole application. (except those in the config file)
    """
    def __init__(self): 
        self.verbose = False
        self.debug = False
        self.user_id = socket.gethostname()
        self.data_directory = None
        self.info_port = 54320 # Those are our defaults, but we parse spinDefaults.h to override them
        self.info_multicast_group = "239.0.0.1"
        self.cameras_config_file = DEFAULT_CAMERAS_CONFIG_FILE
        self.default_scene_id = None
        self.show_puredata_gui = False
        self.clear_old_shared_memory_files = True
        self.enable_firereset = True
        self.banner_image_file = None

class Application(object):
    """
    Application singleton which contains all the important objects.
    """
    def __init__(self, config):
        # attributes:
        self.config = config
        self.gui = None
        self.osc_interface = None
        self.launcher = None
        self.cameras_manager = None
        self.audio_connector = None
        
        # action!
        self._start()
    
    def _start(self):
        """
        Called only once at startup.
        """
        from spinic.launching import ProcessLauncher
        try:
            self.launcher = ProcessLauncher(app=self)
            # Logging has started in lunch after this point.
        except RuntimeError, e: # an other lunch master with the same id is running
            _exit_with_error(str(e))
        #XXX Importing those modules starts their logging.
        # it must be done once lunch master's logging has been set up
        from lunch import logger
        log = logger.start(name="spinic.runner")
        from spinic.osc import SpinicOscInterface
        from spinic.gui import Gui
        from spinic import cameras
        from spinic import audioconnector
        if self.config.enable_firereset:
            from lunch import gui
            log.warning("Calling firereset")
            deferred = gui.run_once("firereset")
        
        cameras.clear_all_dev_shm(self.config.clear_old_shared_memory_files)
        self.gui = Gui(app=self)
        self.osc_interface = SpinicOscInterface(app=self)
        try:
            self.cameras_manager = cameras.CamerasManager(self)
        except RuntimeError, e:
            _exit_with_error(str(e))
        self.audio_connector = audioconnector.AudioConnector(self)

    def __del__(self):
        """
        Destructor.
        
        Clears again the /dev/shm/spinic files
        """
        from spinic import cameras
        cameras.clear_all_dev_shm(app.config.clear_old_shared_memory_files)

def _exit_with_error(error_message):
    """
    Exits with an error dialog
    """
    from lunch import dialogs
    deferred = defer.Deferred()
    def _cb(result):
        reactor.stop()
    deferred.addCallback(_cb)
    error_dialog = dialogs.ErrorDialog(deferred, error_message)
    reactor.run()
    sys.exit(1)


def run(datadir=None, version=None):
    """
    Reads the command-line options, instanciates the application and runs the reactor.
    """
    # Instanciate the Configuration object:
    #FIXME:2010-07-28:aalex:Should not print anything before parsing command-line options
    config = Configuration()
    # parse command-line options:
    import optparse
    parser = optparse.OptionParser(usage="%prog", version=version, description=__doc__)
    parser.add_option("-p", "--info-port", type="int", help="SPIN info channel port to listen on")
    parser.add_option("-g", "--info-multicast-group", type="string", help="Multicast group to listen on for the SPIN info channel")
    parser.add_option("-v", "--verbose", action="store_true", help="Makes the logging output verbose.")
    parser.add_option("-d", "--debug", action="store_true", help="Makes the logging output very verbose.")
    parser.add_option("-u", "--user-id", type="string", help="SPIN user ID for the spinviewer it launches. Defaults to the host name.")
    parser.add_option("-c", "--config-file", type="string", help="Path to the config file for the cameras. Defaults to %s." % (DEFAULT_CAMERAS_CONFIG_FILE))
    parser.add_option("-s", "--scene-id", type="string", help="SPIN scene ID to automatically connect to.")
    parser.add_option("-P", "--show-puredata-gui", action="store_true", help="Enables the Pure Data GUI")
    parser.add_option("-C", "--disable-shared-memory-deletion", action="store_true", help="If not provided, Spinic clears old /dev/shm/spinic-* files at startup")
    parser.add_option("-F", "--disable-firereset", action="store_true", help="If not provided, Spinic calls firereset at startup")
    parser.add_option("-b", "--banner", type="string", help="Provides a path to an image file to be displayed as a banner.")
    (options, args) = parser.parse_args()
    
    defaults = spindefaults.read_spin_defaults()
    print("Welcome to Spinic!")
    if defaults is None:
        print("Could not read SPIN defaults.")
    else:
        print("Found SPIN defaults: %s" % (defaults))
        config.info_port = defaults["INFO_UDP_PORT"]
        config.info_multicast_group = defaults["MULTICAST_GROUP"]
    
    # store it in the Configuration object:
    if options.user_id:
        config.user_id = options.user_id
    if options.config_file:
        config.cameras_config_file = options.config_file
    if options.scene_id:
        print("Setting the default scene ID to %s" % (options.scene_id))
        config.default_scene_id = options.scene_id
    if options.banner:
        if os.path.exists(options.banner):
            config.banner_image_file = options.banner
        else:
            print("No such file: %s" % (options.banner))
    config.verbose = options.verbose
    config.data_directory = datadir
    config.debug = options.debug
    if options.info_port:
        config.info_port = options.info_port
    if options.info_multicast_group:
        config.info_multicast_group = options.info_multicast_group
    config.show_puredata_gui = options.show_puredata_gui
    config.clear_old_shared_memory_files = not options.disable_shared_memory_deletion
    config.enable_firereset = not options.disable_firereset
    
    # instanciate the application. (might exit with error)
    app = Application(config)
    
    # run the reactor:
    reactor.run()
    del app
    #FIXME:2010-07-28:aalex:For some reason, the destructor is never called.
    gc.collect() # Forcing garbage collection to try to call the desctructor
    print("\nGoodbye.")
    sys.exit(0)

