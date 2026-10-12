#!/bin/bash
# SPDX-License-Identifier: MIT
# Build a prefilled data-partition image (FAT32 RC2DATA, exactly partition 2 of the card) for
#   mkcard.py --data-partition [--card-bytes N] --data-img OUT.img
# The empty volume comes from fat32.py (deterministic FAT32, 4 KiB clusters); the contents of DIR are copied into its root
# recursively with mtools (mcopy -s -m: long names, modification times kept), then fsck.fat -n must be clean.
# The result is not reproducible (file times, directory order): pin it by the sha256 that mkcard.py records.
# Needs mtools and dosfstools (Homebrew on macOS, packages on Linux). Dot files at the top of DIR are skipped.
#
# usage: mkdata.sh OUT.img DIR [CARD_BYTES]   (CARD_BYTES: the mkcard.py --card-bytes; default the 2 GB card)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
OUT=${1:?output image, e.g. data.img}; SRC=${2:?directory with books, fonts, ...}
[ -d "$SRC" ] || { echo "REFUSE: $SRC is not a directory"; exit 1; }
tool() { command -v "$1" 2>/dev/null || { for d in /opt/homebrew/bin /opt/homebrew/sbin /usr/sbin /sbin; do
  [ -x "$d/$1" ] && { echo "$d/$1"; return; }; done; echo "REFUSE: $1 not found (brew install mtools dosfstools)" >&2; exit 1; }; }
MCOPY=$(tool mcopy); MDIR=$(tool mdir); FSCK=$(tool fsck.fat)
shopt -s nullglob
items=("$SRC"/*)
[ ${#items[@]} -gt 0 ] || { echo "REFUSE: $SRC is empty"; exit 1; }
if [ -n "${3:-}" ]; then python3 -I "$here/fat32.py" "$OUT" --card-bytes "$3"; else python3 -I "$here/fat32.py" "$OUT"; fi
export MTOOLS_SKIP_CHECK=1
"$MCOPY" -s -m -i "$OUT" "${items[@]}" ::/
"$FSCK" -n "$OUT"
"$MDIR" -i "$OUT" ::/
shasum -a 256 "$OUT" 2>/dev/null || sha256sum "$OUT"
