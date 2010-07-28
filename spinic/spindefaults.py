#!/usr/bin/env python
"""
Tools to parse the SPIN framework config file.
"""
import os
from lunch import logger

if __name__ == "__main__":
    log = logger.start(name="spindefaults", to_stdout=True, level="debug")
else:
    class DummyLogger(object):
        def debug(self, s):
            pass
            # print("Debug:" + str(s))
        def info(self, s):
            pass
            # print("info:" + str(s))
        def error(self, s):
            print("Error:" + str(s))
    log = DummyLogger() # FIXME: that's bad! The logging does not work in this module, since we need to start it before starting the main logging in lunch. This should be fixed.

def read_spin_defaults():
    """
    Returns a dict of defaults parameters for spinframework.
    (ports number and multicast group)
    """
    file_name = "spinFramework/spinDefaults.h"
    prefixes = ["/usr/local", "/usr"]
    is_found = False
    for prefix in prefixes:
        full_path = os.path.join(prefix, "include", file_name)
        log.debug("Trying to find %s" % (full_path))
        if os.path.exists(full_path):
            log.info("Found %s" % (full_path))
            is_found = True
            break
    if not is_found:
        log.error("Could not find the %s header." % (file_name))
        return None
    else:
        try:
            f = open(full_path, "r")
        except os.OSError, e:
            log.error(str(e))
            return None
        else:
            ret = {
                "MULTICAST_GROUP": "",
                "INFO_UDP_PORT": 0
                }
            for line in f.readlines():
                if "INFO_UDP_PORT" in line:
                    word = line.split("\"")[1]
                    log.debug("Parsed INFO_UDP_PORT %s" % (word))
                    ret["INFO_UDP_PORT"] = int(word)
                elif "MULTICAST_GROUP" in line:
                    word = line.split("\"")[1]
                    log.debug("Parsed MULTICAST_GROUP %s" % (word))
                    ret["MULTICAST_GROUP"] = str(word)
            f.close()
            return ret
        
if __name__ == "__main__":
    defaults = read_spin_defaults()
    log.debug("Results: " + str(defaults))
