#!/usr/bin/env python
"""
Manages JACK routing configuration with jack.plumbing
"""

import os
from lunch import logger
from twisted.internet import defer
from twisted.internet import reactor
from twisted.python import procutils
from twisted.internet import utils

if __name__ == "__main__":
    log = logger.start(name="plumberjack", to_stdout=True, level="debug")
else:
    log = logger.start(name="plumberjack")

def jack_disconnect(source, sink):
    """
    Calls jack_disconnect with the given arguments.
    Returns a Deferred
    """
    deferred = defer.Deferred()
    def _cb(result):
        if type(result) != int:
            lor.error("The result of calling jack_disconnect should be an int.")
        log.info("jack_disconnect result: " + str(result))
        if result == 0:
            deferred.callback(True)
        else:
            deferred.callback(False)
    
    exec_name = "jack_disconnect"
    try:
        executable = procutils.which(exec_name)[0]
    except IndexError:
        log.error("Could not find executable %s" % (exec_name))
        return defer.succeed(False)
    else:
        args = [source, sink]
        log.info("$ %s %s" % (executable, " ".join(list(args))))
        d = utils.getProcessValue(executable, args, os.environ, '.', reactor)
        d.addCallback(_cb)
        return deferred

class Rule(object):
    """
    A single rule for jack.plumbing
    """
    def __init__(self, name, text):
        self.name = name
        self.text = text

class PlumberJack(object):
    """
    Writes rules to the ~/.jack.plumbing configuration file.
    """
    def __init__(self, backup_enabled=False, auto_write_enabled=False):
        self.backup_enabled = backup_enabled
        self.auto_write_enabled = auto_write_enabled
        self.config_file_path = os.path.expanduser("~/.jack.plumbing")
        self.rules = [] # order matters, so we use a list, not a dict
        self._previous_config_file_contents = None
        if self.backup_enabled:
            self._backup_original()
    
    def add_rule(self, name, text):
        """
        Adds a rule.
        """
        rule = self.get_rule(name)
        add_it = True
        if rule is not None:
            if rule.text == text:
                log.debug("The exact same rule was already there.")
                add_it = False
            else:
                self.remove_rule(name)
        if add_it:
            log.info("Adding rule %s: %s" % (name, text))
            self.rules.append(Rule(name, text))
            if self.auto_write_enabled:
                self.write_config_to_file()
    
    def get_rule(self, name):
        """
        Returns the rule for a given name, or None.
        """
        index = self.get_rule_index(name)
        if index is not None:
            log.debug("Found rule %s" % (name))
            return self.rules[index]
        else:
            return None
    
    def get_rule_index(self, name):
        """
        Returns the index for a given rule name, or None.
        """
        index = 0
        found_it = False
        for rule in self.rules:
            if rule.name == name:
                found_it = True
                break
            else:
                index += 1
        if found_it:
            return index
        else:
            return None 
    
    def remove_rule(self, name):
        """
        Removes the rule for a given name.
        """
        index = self.get_rule_index(name)
        if index is not None:
            log.info("Removing rule %s" % (name))
            del self.rules[index]
            if self.auto_write_enabled:
                self.write_config_to_file()
        else:
            log.warning("Did not find rule %s. Cannot delete it." % (name))

    def _backup_original(self):
        """
        Reads the original contents of the ~/.jack.plumbing file
        """
        file_path = self.config_file_path
        if not os.path.exists(file_path):
            log.debug("Did not find any original jack.plumbing config file.")
            return
        elif not os.path.isfile(file_path):
            raise RuntimeError("The config file %s should be a file." % (file_path))
        log.info("Making a backup of the original %s" % (file_path))
        _file = open(file_path, "r")
        text = _file.read()
        _file.close()
        self._previous_config_file_contents = text

    def _restore_original(self):
        """
        Writes back the original contents to the ~/.jack.plumbing file
        """
        if self._previous_config_file_contents is not None:
            text = self._previous_config_file_contents
            self._previous_config_file_contents = None
            file_path = self.config_file_path
            log.info("Restoring original contents of %s" % (file_path))
            _file = open(file_path, "w")
            _file.write(text)
            _file.close()

    def write_config_to_file(self):
        """
        Writes the current rules to the ~/.jack.plumbing config file.
        """
        file_path = self.config_file_path
        if not os.path.exists(file_path):
            log.info("No jack.plumbing config file found. Will create one.")
        elif not os.path.isfile(file_path):
            raise RuntimeError("The file %s should be a file." % (file_path))
        log.info("Writing current rules to %s" % (file_path))
        text = self._create_text_to_write()
        _file = open(file_path, "w")
        _file.write(text)
        _file.close()

    def _create_text_to_write(self):
        """
        @return: Content of the config file to write for the current rules.
        """
        txt = ""
        for rule in self.rules:
            txt += rule.text + "\n"
        return txt

    def __del__(self):
        """
        Destructor.
        Restores the original config file, if backup is enabled.
        """
        if self.backup_enabled:
            self._restore_original()

if __name__ == "__main__":
    plumber = PlumberJack()
    rules = {
        "one": """(connect-exclusive "pure_data_.*:output0" "system:playback_1")""",
        "two": """(connect-exclusive "pure_data_.*:output1" "system:playback_2")""",
        }
    for name, rule in rules.iteritems():
        plumber.add_rule(name, rule)
    plumber.write_config_to_file()
    del plumber
    
    def _cb(result):
        log.info("Stopping the reactor.")
        reactor.stop()
    
    def _later():
        log.info("Disconnect capture from playback")
        d = jack_disconnect("system\\:capture_1", "system\\:playback_1")
        d.addCallback(_cb)

    reactor.callLater(0.01, _later)
    reactor.run()
    
