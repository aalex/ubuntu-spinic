man_MANS = spinic.1
EXTRA_DIST = $(man_MANS)
MAINTAINERCLEANFILES = $(man_MANS)

# The man pages depend on the --help strings and the version number.
common_mandeps = $(top_srcdir)/configure.ac

spinic.1: $(top_srcdir)/spinic/runner.py $(top_srcdir)/scripts/spinic.in $(common_mandeps) $(top_srcdir)/man/man-spinic.txt
	$(HELP2MAN) --include=$(top_srcdir)/man/man-spinic.txt --name="SPIN Scenic launcher" --no-info $(top_builddir)/scripts/spinic -o $@
