SUBDIRS = doc spinic scripts data man

#TESTS_ENVIRONMENT = LANG=en_CA.UTF-8 PYTHONPATH=../:$(PYTHONPATH) trial
#TESTS = spinic/test/test_spinic.py 

desktopdir = $(datadir)/applications
desktop_DATA = spinic.desktop
pixmapsdir = $(datadir)/pixmaps
pixmaps_DATA = spinic.png
EXTRA_DIST = $(pixmaps_DATA) $(desktop_DATA) spinic.png RELEASE

clean-local:
	rm -rf _trial_temp

