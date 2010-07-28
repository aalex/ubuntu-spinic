#!/usr/bin/env python
"""
The Spinic GUI
"""
import os
import sys
import tempfile
if __name__ == "__main__": # just a reminder
    from twisted.internet import gtk2reactor
    gtk2reactor.install()
from twisted.internet import reactor
import gtk
from lunch import logger

log = logger.start(name='spinic_gui')

PACKAGE_DATA = "./data"
APP_NAME = "spinic"
GLADE_FILE_NAME = "spinic.glade"

def set_model_from_list(cb, items):
    """
    Set up a ComboBox or ComboBoxEntry based on a list of strings.
    
    @type cb: L{gtk.ComboBox}
    @type items: C{list}
    """
    model = gtk.ListStore(str)
    for i in items:
        model.append([i])
    cb.set_model(model)
    if type(cb) == gtk.ComboBoxEntry:
        cb.set_text_column(0)
    elif type(cb) == gtk.ComboBox:
        cell = gtk.CellRendererText()
        cb.pack_start(cell, True)
        cb.add_attribute(cell, 'text', 0)

def _get_combobox_value(widget):
    """
    Returns the current value of a GTK ComboBox widget.
    """
    index = widget.get_active()
    tree_model = widget.get_model()
    try:
        tree_model_row = tree_model[index]
    except IndexError:
        raise RuntimeError("Cannot get ComboBox's value. Its tree model %s doesn't have row number %s." % (widget, index))
    return tree_model_row[0] 

def _set_combobox_choices(widget, choices=[]):
    """
    Sets the choices in a GTK combobox.
    """
    #XXX: combo boxes in the glade file must have a space as a value to have a tree iter
    #TODO When we change a widget value, its changed callback is called...
    try:
        previous_value = _get_combobox_value(widget)
    except RuntimeError, e:
        log.error(str(e))
        previous_value = " "
    tree_model = gtk.ListStore(str)
    for choice in choices:
        tree_model.append([choice])
    widget.set_model(tree_model)
    if previous_value != " ": # we put empty spaces in glade as value, but this is not a real value, and we get rid of it.
        _set_combobox_value(widget, previous_value)

def _set_combobox_value(widget, value=None):
    """
    Sets the current value of a GTK ComboBox widget.
    """
    #XXX: combo boxes in the glade file must have a space as a value to have a tree iter
    tree_model = widget.get_model()
    index = 0
    got_it = False
    for i in iter(tree_model):
        v = i[0]
        if v == value:
            got_it = True
            break # got it
        index += 1
    if got_it:
        #widget.set_active(-1)  NONE
        widget.set_active(index)
    else:
        widget.set_active(0) # FIXME: -1)
        msg = "ComboBox widget %s doesn't have value \"%s\"." % (widget, value)
        log.debug(msg)

class MilhouseWatcher(object):
    """
    Sets up a command line to watch the running milhouse processes.
    """
    def __init__(self):
        temp_dir = "/tmp/spinic/watchfiles"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        self.fd, self.fname = tempfile.mkstemp(dir=temp_dir)
        cmd = """ps -fp $(pgrep milhouse || echo 65537) \n"""
        log.info("MilhouseWatcher: Writing %s to %s" % (cmd, self.fname))
        os.write(self.fd, cmd)
        os.close(self.fd)
    
    def get_command(self):
        path = self.fname
        cmd = "watch sh %s" % (path)
        return cmd
        
    def __del__(self):
        try:
            os.unlink(self.fname)
        except OSError, e:
            log.error(str(e))

class Gui(object):
    """
    Main application (arguably God) class
     * Contains the main GTK window
    """
    def __init__(self, app=None):
        self.app = app
        self.milhouse_watcher = MilhouseWatcher()
        global PACKAGE_DATA
        global GLADE_FILE_NAME
        PACKAGE_DATA = self.app.config.data_directory
        gtkbuilder_file = os.path.join(PACKAGE_DATA, GLADE_FILE_NAME)
        log.info("GtkBuilder file: %s" % (gtkbuilder_file))
        self.app.osc_interface = None
        if not os.path.isfile(gtkbuilder_file):
            print "Could not find the glade file."
            sys.exit(1)
        self.process_launcher = app.launcher
        self.builder = gtk.Builder()
        self.builder.add_from_file(gtkbuilder_file)
        self.builder.connect_signals(self)
        self.window = self.builder.get_object("main_window")
        if self.window is None:
            raise RuntimeError("Could not get the window widget.")
        from lunch import gui
        if not os.path.exists(gui.ICON_FILE):
            log.warning("Could not find icon file %s." % (gui.ICON_FILE))
        else:
            large_icon = gtk.gdk.pixbuf_new_from_file(gui.ICON_FILE)
            self.window.set_icon_list(large_icon)
        self.window.connect('delete-event', self.on_main_window_deleted)
        self.spin_scene_widget = self.builder.get_object("spin_scene")
        self.spin_connect_widget = self.builder.get_object("spin_connect")
        self.spin_connected_widget = self.builder.get_object("spin_connected")
        self.cameras_text_view_widget = self.builder.get_object("cameras_text_view")
        self.nodes_text_view_widget = self.builder.get_object("nodes_text_view")
        self.banner_widget = self.builder.get_object("banner")
        if self.app.config.banner_image_file is not None:
            log.info("Loading image for banner: %s" % (self.app.config.banner_image_file))
            self.banner_widget.set_from_file(self.app.config.banner_image_file) # does not raise errors
                
        self._populate_spin_scenes()
        self.menu_accel_group = self.builder.get_object('accelgroup1')
        self._setup_shortcuts()
        reactor.callLater(0.01, self._start)

    def _start(self):
        self.window.show()
        self.spin_connect_widget.set_sensitive(False)
        cameras_txt = "\n".join(self.app.cameras_manager.get_my_cameras())
        self.update_cameras_text(cameras_txt)
        self.update_nodes_text("TODO")

    def _setup_shortcuts(self):
        pass
        #not working yet
        #accel_key = gtk.keysyms.q
        #accel_mods = gtk.gdk.CONTROL_MASK
        #accel_flags = 0
        #callback = self.on_quit_menu_item_activated
        #self.menu_accel_group.connect_group(accel_key, accel_mods, accel_flags, callback)

    def update_server_list(self, servers):
        log.debug("update_server_list")
        _set_combobox_choices(self.spin_scene_widget, servers)

    def choose_server_and_click_connect(self, scene_id):
        """
        Called from the OSC interface if the user has set a default scene ID from the command line interface. 
        """
        log.debug("choose_server_and_click_connect %s" % (scene_id))
        _set_combobox_value(self.spin_scene_widget, scene_id)
        self.on_spin_connect_clicked()
    
    def on_spin_scene_changed(self, *args):
        log.debug("on_spin_scene_changed")
        if self.app.osc_interface is None:
            log.debug("No OSC interface set yet.")
            self.spin_connect_widget.set_sensitive(False)
        else:
            value = _get_combobox_value(self.spin_scene_widget)
            if self.app.osc_interface.current_server_id == value:
                self.spin_connect_widget.set_sensitive(False)
            else:
                self.spin_connect_widget.set_sensitive(True)

    def on_spin_connect_clicked(self, *args):
        """
        Clicked on the spin_connect button 
        """
        log.debug("on_spin_connect_clicked")
        value = _get_combobox_value(self.spin_scene_widget)
        log.debug("Will change SPIN scene to %s" % (value))
        if self.app.osc_interface is None:
            log.error("Cannot switch server. No OSC interface set yet.")
        else:
            self.app.osc_interface.choose_server(value)
            self.spin_connect_widget.set_sensitive(False)

    def on_about_menu_item_activated(self, *args):
        self.process_launcher.lunch_gui.show_about_dialog()

    def on_help_menu_item_activated(self, *args):
        pass

    def update_connected_state(self, connected=False):
        """
        Updates the image.
        """
        # TODO: set button here too
        if connected:
            self.spin_connected_widget.set_from_stock(gtk.STOCK_YES, 4)
        else:
            self.spin_connected_widget.set_from_stock(gtk.STOCK_NO, 4)

    def on_quit_menu_item_activated(self, *args):
        log.info("The user chose the quit menu item.")
        self.process_launcher.lunch_gui.confirm_and_quit()

    def _populate_spin_scenes(self):
        scenes = ["default"]
        # #list_store = gtk.ListStore(str)
        # list_store = self.spin_scene_widget.get_model()
        # for name in scenes:
        #     list_store.append([name])
        # #self.spin_scene_widget.set_model(list_store)
        
        set_model_from_list(self.spin_scene_widget, scenes)
        self.spin_scene_widget.set_active(0)
   
    def on_launch_ps_aux_clicked(self, *args):
        from lunch import gui
        #cmd = "ps aux | grep -v grep | grep -v lunch-slave | grep --color=auto milhouse"
        cmd = self.milhouse_watcher.get_command()
        full_cmd = "xterm", "-geometry", "150x20", "-e", cmd
        log.info("$ %s" % (" ".join(full_cmd)))
        gui.run_once(*full_cmd)
        
    def on_main_window_deleted(self, *args):
        """
        Destroy method causes appliaction to exit
        when main window closed
        """
        return self.process_launcher.lunch_gui.confirm_and_quit()
        #reactor.stop()

    def on_rotate_right_clicked(self, *args):
        log.debug("on_rotate_right_clicked")
        self.app.osc_interface.rotate_right()

    def on_rotate_left_clicked(self, *args):
        log.debug("on_rotate_left_clicked")
        self.app.osc_interface.rotate_left()
    
    def on_send_refresh_clicked(self, *args):
        log.debug("on_send_refresh_clicked")
        self.app.osc_interface.send_refresh()
    
    def on_send_clear_clicked(self, *args):
        log.debug("on_send_clear_clicked")
        self.app.osc_interface.send_clear()
    
    def update_nodes_text(self, text):
        #TODO
        self.nodes_text_view_widget.get_buffer().set_text(unicode(text))
    
    def update_cameras_text(self, text):
        #TODO
        self.cameras_text_view_widget.get_buffer().set_text(unicode(text))
    
    def on_send_create_grid_clicked(self, *args):
        log.debug("on_send_create_grid_clicked")
        self.app.osc_interface.send_create_grid()

