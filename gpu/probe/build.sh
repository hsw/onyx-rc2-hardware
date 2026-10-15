#!/bin/sh
# SPDX-License-Identifier: MIT
# Build egl_probe for armeabi-v7a (a PIE executable for Android 4.1 and later).
#
# The extension -> entry point table is generated at build time from the EGL/GLES extension headers
# (gen_procs.py + extra_procs.txt), so the set of probed names follows the headers you build against.
# The output in ../egl-probe-output.txt was made with the headers of an Android 4.4 source tree
# (frameworks/native/opengl/include) and GCC 4.7 with the NDK r9 android-18 sysroot.
#
# Environment:
#   CC          C cross compiler for 32-bit ARM Android (required). For example:
#                 older NDK, GCC:   $NDK/toolchains/arm-linux-androideabi-4.9/prebuilt/<host>/bin/arm-linux-androideabi-gcc
#                 newer NDK, clang: $NDK/toolchains/llvm/prebuilt/<host>/bin/armv7a-linux-androideabi19-clang
#   SYSROOT     platform sysroot, passed as --sysroot when set (older NDK: $NDK/platforms/android-18/arch-arm;
#               leave unset for the clang wrappers of a newer NDK, which know their sysroot)
#   GL_INCLUDE  directory holding EGL/eglext.h, GLES/glext.h and GLES2/gl2ext.h (default: $SYSROOT/usr/include;
#               newer NDK: $NDK/toolchains/llvm/prebuilt/<host>/sysroot/usr/include; an Android source tree:
#               frameworks/native/opengl/include)
#   OUT         output file (default: ./egl_probe)
#
# Usage:
#   CC=... SYSROOT=... ./build.sh
#   adb push egl_probe /data/local/tmp/
#   adb shell /data/local/tmp/egl_probe --tsv /data/local/tmp/egl-probe-tsv > egl-probe-output.txt
#   adb pull /data/local/tmp/egl-probe-tsv
# Run it as the shell user (or root); it needs read/write access to the GPU device nodes.
# --skip-maxtex skips the 64 MiB texture allocation check; --list prints the jobs; --only JOB runs one.
set -eu
: "${CC:?set CC to an ARM Android C compiler (see the comment at the top)}"
SYSROOT=${SYSROOT:-}
if [ -n "$SYSROOT" ]; then
  GL_INCLUDE=${GL_INCLUDE:-$SYSROOT/usr/include}
  SYSROOT_FLAG="--sysroot=$SYSROOT"
else
  : "${GL_INCLUDE:?set GL_INCLUDE (or SYSROOT) to the directory with EGL/ GLES/ GLES2/ headers}"
  SYSROOT_FLAG=
fi
OUT=${OUT:-egl_probe}
HERE=$(cd "$(dirname "$0")" && pwd)
GEN=$(mktemp -d)
trap 'rm -rf "$GEN"' EXIT
python3 -I "$HERE/gen_procs.py" "$GL_INCLUDE" "$HERE/extra_procs.txt" "$GEN/egl_probe_procs.h"
# shellcheck disable=SC2086
"$CC" $SYSROOT_FLAG -std=gnu99 -O2 -Wall -Wextra -Wno-unused-parameter -Wno-missing-field-initializers \
  -march=armv7-a -mfloat-abi=softfp -fPIE -pie -I"$GEN" \
  -o "$OUT" "$HERE/egl_probe.c" -lEGL -lGLESv2 -ldl
echo "$OUT"
