#!/bin/bash
# SPDX-License-Identifier: MIT
# Write an sdboot card image (mkcard.py) to the 2 GB test microSD in a USB card reader, then read it back. macOS only
# (diskutil, /dev/rdiskN). Raw writes to removable disks need a terminal that macOS privacy settings allow (Terminal.app).
#
# usage: sudo write-card.sh diskN <dir with sdcard.img + manifest.json> [--boot-area | --rootfs]
#   default      whole image: all 1 977 614 336 bytes (MBR, IDB, boot table, blobs, all partitions), ~2-3 min each way.
#                The only mode that may change the card's partition layout (e.g. single -> data partition)
#   --boot-area  only the first 64 MiB (MBR, IDB, boot table, kernel, ramdisk, waveform); the partitions stay as they are
#   --rootfs     data-layout image only: the first 320 MiB = boot area + partition 1 (ext4 rc2root); partition 2 (FAT32
#                RC2DATA: user data) stays as it is
# Refuses: a disk that is not exactly 1 977 614 336 bytes, not on USB, not removable; an image whose size or sha256 does
# not match manifest.json; for --boot-area and --rootfs a card whose MBR partition table (bytes 446..511) differs from the
# image's (mbrguard.py). Writes in 32 KiB blocks from offset 0 (never per sector: the card's 32 KiB alignment).
# The built-in Mac SD reader timed out on every raw read and write in our tests: use a USB reader.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
D=${1:?disk id, e.g. disk7}; DIR=${2:?card dir}; MODE=${3:-}
IMG=$DIR/sdcard.img; MAN=$DIR/manifest.json
CARD=1977614336; BOOT=67108864; BS=32768
case "$MODE" in ''|--boot-area|--rootfs) ;; *) echo "REFUSE: unknown mode '$MODE'"; exit 1 ;; esac
[ -r "$IMG" ] && [ -r "$MAN" ] || { echo "REFUSE: $IMG or $MAN missing"; exit 1; }
mval() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$MAN" "$1"; }
want_img=$(mval sdcard_img_sha256)
want_boot=$(mval boot_area_sha256)
want_rootfs=$(mval rootfs_area_sha256)
rootfs_bytes=$(mval rootfs_area_bytes)
table_hex=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mbr", {}).get("table_hex", ""))' "$MAN")
if [ "$MODE" = --rootfs ]; then
  [ -n "$want_rootfs" ] && [ -n "$rootfs_bytes" ] || { echo "REFUSE: --rootfs needs a data-layout image (mkcard.py --data-partition)"; exit 1; }
  [ $((rootfs_bytes % BS)) = 0 ] || { echo "REFUSE: rootfs area $rootfs_bytes is not a multiple of $BS"; exit 1; }
fi
if [ -n "$MODE" ] && [ -z "$table_hex" ]; then echo "REFUSE: manifest.json has no mbr.table_hex (rebuild with mkcard.py)"; exit 1; fi

info=$(diskutil info "$D")
size=$(awk -F'[()]' '/Disk Size/{print $2}' <<<"$info" | awk '{print $1}')
proto=$(awk -F': *' '/Protocol/{print $2}' <<<"$info")
removable=$(awk -F': *' '/Removable Media/{print $2}' <<<"$info")
echo "target /dev/$D: $size bytes, protocol '$proto', removable '$removable'"
[ "$size" = "$CARD" ] || { echo "REFUSE: disk size is not $CARD (the 2 GB SanDisk SDSU02G test card)"; exit 1; }
[ "$proto" = USB ] || { echo "REFUSE: not on USB (the built-in SD reader times out; use a USB card reader)"; exit 1; }
grep -qiE "removable|yes" <<<"$removable" || { echo "REFUSE: not removable media"; exit 1; }
[ "$(stat -f %z "$IMG")" = "$CARD" ] || { echo "REFUSE: image size is not $CARD"; exit 1; }
echo "== sha256 of the image (whole file)"
[ "$(shasum -a 256 "$IMG" | cut -d' ' -f1)" = "$want_img" ] || { echo "REFUSE: image sha256 != manifest"; exit 1; }
case "$MODE" in
  --boot-area) n=$((BOOT / BS)); want=$want_boot; what="first $BOOT bytes (boot area)" ;;
  --rootfs) n=$((rootfs_bytes / BS)); want=$want_rootfs; what="first $rootfs_bytes bytes (boot area + partition 1)" ;;
  *) n=$((CARD / BS)); want=$want_img; what="whole card" ;;
esac

diskutil unmountDisk "/dev/$D"
if [ -n "$MODE" ]; then
  echo "== MBR guard: the card's partition table must equal the image's"
  head_file=$(mktemp)
  trap 'rm -f "$head_file"' EXIT
  dd if="/dev/r$D" of="$head_file" bs=$BS count=1 2>/dev/null
  python3 -I "$HERE/mbrguard.py" "$head_file" "$IMG" "$table_hex" || exit 1
fi
echo "== write $what: $n x 32 KiB from offset 0"
dd if="$IMG" of="/dev/r$D" bs=$BS count="$n" conv=notrunc
sync
echo "== read back $what"
if [ -z "$MODE" ] && [ -n "$want_rootfs" ]; then
  # Data layout, whole card: macOS automounts the new FAT32 RC2DATA (p2) as soon as dd closes the disk and writes its
  # own files there (.fseventsd, the volume dirty flag), so a whole-card hash cannot match (seen on three writes to two
  # cards). Verify [0, end of p1) strictly; p2 must either match the image or pass fsck_msdos -n.
  diskutil unmountDisk "/dev/$D" >/dev/null 2>&1 || true
  nr=$((rootfs_bytes / BS))
  got=$(dd if="/dev/r$D" bs=$BS count="$nr" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
  [ "$got" = "$want_rootfs" ] || { echo "READBACK MISMATCH (boot area + partition 1): $got != $want_rootfs"; exit 2; }
  echo "READBACK OK boot area + partition 1 $got"
  want_p2=$(python3 -I -c 'import json,sys; print([p["sha256"] for p in json.load(open(sys.argv[1]))["partitions"] if p.get("label")=="RC2DATA"][0])' "$MAN")
  got_p2=$(dd if="/dev/r$D" bs=$BS skip="$nr" count=$(((CARD - rootfs_bytes) / BS)) 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
  if [ "$got_p2" = "$want_p2" ]; then echo "READBACK OK partition 2 $got_p2 (whole card = $want)"
  else
    echo "partition 2 differs from the image ($got_p2): macOS mounted RC2DATA after the write; checking it with fsck_msdos -n"
    if fsck_msdos -n "/dev/r${D}s2"; then echo "READBACK OK: boot area + partition 1 exact, partition 2 changed by macOS only (fsck clean)"
    else echo "READBACK FAIL: partition 2 does not pass fsck_msdos"; exit 2; fi
  fi
else
  got=$(dd if="/dev/r$D" bs=$BS count="$n" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
  if [ "$got" = "$want" ]; then echo "READBACK OK $got"; else echo "READBACK MISMATCH: $got != $want"; exit 2; fi
fi
diskutil eject "/dev/$D"
echo "done: card ejected, take it out of the reader"
