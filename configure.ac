#                                               -*- Autoconf -*-
# Process this file with autoconf to produce a configure script.

AC_PREREQ(2.61)
AC_INIT(SPINIC, 0.1.2)  # should always be .1 greater than last tag, unless this is a tag
#AC_CONFIG_HEADER([src/config.h])
AC_CONFIG_MACRO_DIR([m4])
dnl AC_PROG_LIBTOOL

AM_INIT_AUTOMAKE([-Wno-portability])

# Check for C and C++ compilers
dnl #AC_PROG_CXX
dnl #AC_PROG_CC

# Checks for header files.
dnl #AC_HEADER_STDC
dnl #AC_CHECK_HEADERS([arpa/inet.h stdlib.h string.h sys/ioctl.h unistd.h linux/videodev2.h])

# Checks for typedefs, structures, and compiler characteristics.
dnl #AC_HEADER_STDBOOL
dnl #AC_C_CONST
dnl #PKG_PROG_PKG_CONFIG

dnl #AC_PROG_GCC_TRADITIONAL
dnl #AC_CHECK_FUNCS([inet_ntoa memset socket])

AC_MSG_CHECKING(whether to enable debugging)
AC_ARG_ENABLE([debug], [
  --enable-debug  debug symbols, build test programs, stricter compile ],, 
        enable_debug=yes)

AC_MSG_WARN([${ac_prefix}])
# Checks for library functions.

dnl check for python
AM_PATH_PYTHON([2.5])

# GNU help2man creates man pages from --help output; in many cases, this
# is sufficient, and obviates the need to maintain man pages separately.
# However, this means invoking executables, which we generally cannot do
# when cross-compiling, so we test to avoid that (the variable
# "cross_compiling" is set by AC_PROG_CC).
if test $cross_compiling = no; then
    AM_MISSING_PROG(HELP2MAN, help2man)
else
    HELP2MAN=:
fi

# Check for python modules, if second arg is non-empty,
# configure exits with an error (NOTE: it will not print this argument!)

AX_PYTHON_MODULE([twisted], [Fatal])
AX_PYTHON_MODULE([gtk], [Fatal])
# AX_PYTHON_MODULE([lunch], [Fatal])
# AX_PYTHON_MODULE([txosc], [Fatal])

AM_CONDITIONAL([PROJ_DEBUG],test "x${enable_debug}" = "xyes")

# FIXME
AS_AC_EXPAND(LIBDIR, $libdir)
AC_MSG_NOTICE(Storing library files in $LIBDIR)

AS_AC_EXPAND(DATADIR, $datadir)
AC_MSG_NOTICE(Storing library data in $DATADIR)

dnl PIXMAPS_DIR=$DATADIR/scenic/pixmaps
dnl AC_SUBST(PIXMAPS_DIR)

AS_AC_EXPAND(PKGLIBDIR, $pkglibdir)
AC_MSG_NOTICE(Storing package files in $PKGLIBDIR)

AC_CONFIG_FILES([scripts/spinic], [chmod +x scripts/spinic])

AC_CONFIG_FILES([
Makefile
data/Makefile
doc/Makefile
spinic/Makefile
scripts/Makefile
man/Makefile
])

AC_OUTPUT
