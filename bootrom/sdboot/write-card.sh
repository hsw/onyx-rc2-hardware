#!/bin/bash
# SPDX-License-Identifier: MIT
# Write an sdboot card image (mkcard.py) to a microSD card in a USB card reader, then read it back. macOS only
# (diskutil, /dev/rdiskN, newfs_msdos). Raw writes to removable disks need a terminal that macOS privacy settings allow
# (Terminal.app). Uses only macOS built-ins and python3 with the standard library.
#
# usage: sudo ./write-card.sh [--yes] diskN <dir with sdcard.img + manifest.json> [--boot-area | --rootfs | --format-data]
#        ./write-card.sh --check diskN [<card dir> [mode]]
#   default      the whole image. Data layout (mkcard.py --data-partition): the image is boot area + partition 1 (first
#                320 MiB); the MBR's p2 length is set from the card size (whole 32 KiB units), then p2 is formatted on
#                the card: FAT32 RC2DATA (formatdata.py, newfs_msdos), fsck_msdos -n. ERASES RC2DATA (books, settings).
#                Single layout or --data-img: the full card image (manifest image_bytes; the 2 GB card: 1 977 614 336
#                bytes, ~2-3 min each way). The only mode that may change the card's partition layout
#   --boot-area  only the first 64 MiB (MBR, IDB, boot table, kernel, ramdisk, waveform); the partitions stay as they are
#   --rootfs     data layout only: the first 320 MiB = boot area + partition 1 (ext4 rc2root); p2 (FAT32 RC2DATA: books,
#                KOReader settings) stays as it is
#   --format-data  data layout only: reformat p2 as an empty RC2DATA (erases it); nothing else is written
#   --check      run every guard (and the image checks when a card dir is given), print the verdict, exit 0 (would write)
#                or 1 (refused); never unmounts, writes or reads the raw disk. No sudo needed
#   --yes        skip typing the disk id back (the confirmation prompt)
# Disk guards (diskguard.py, from diskutil info -plist): whole-disk id (^disk[0-9]+$), Internal false, BusProtocol USB,
# RemovableMedia or Ejectable, not the boot disk (ParentWholeDisk or APFS physical store of /), no volume at / or under
# /System or /Volumes/Macintosh HD and no APFS container/store on it, image size <= disk size <= 32 GiB. Environment:
# RC2_CARD_MAX_BYTES raises the 32 GiB cap; RC2_CARD_BYTES pins the exact disk size (pass both through sudo:
# sudo RC2_CARD_BYTES=1977614336 ./write-card.sh ...).
# Image checks: size = manifest image_bytes = file size, a multiple of 32 KiB; sha256 = manifest (of the unpatched image).
# Partial modes: the card's MBR partition table (bytes 446..511) must equal the image's (mbrguard.py); in the data layout
# p2 is compared by type and start only, and the card's p2 length is kept. Data layout readback: the card must hold the
# image with only the p2 sector count (MBR bytes 474..477) changed. Then the disk id must be typed back. Writes in 32 KiB
# blocks from offset 0 (never per sector: the card's 32 KiB alignment).
# The built-in Mac SD reader timed out on every raw read and write in our tests: use a USB reader.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CHECK=; YES=; MODE=; POS=()
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --yes) YES=1 ;;
    --boot-area|--rootfs|--format-data) [ -z "$MODE" ] || { echo "REFUSE: two modes ($MODE, $arg)"; exit 1; }; MODE=$arg ;;
    -*) echo "REFUSE: unknown mode '$arg'"; exit 1 ;;
    *) POS+=("$arg") ;;
  esac
done
[ ${#POS[@]} -ge 1 ] && [ ${#POS[@]} -le 2 ] \
  || { echo "REFUSE: usage: write-card.sh [--check] [--yes] diskN [card dir] [--boot-area | --rootfs | --format-data]"; exit 1; }
D=${POS[0]}; DIR=${POS[1]:-}
[ -n "$DIR" ] || [ -n "$CHECK" ] || { echo "REFUSE: no card dir (only --check may go without one)"; exit 1; }
BOOT=67108864; BS=32768; IMG_BYTES=0; FOW=
if [ -n "$DIR" ]; then
  IMG=$DIR/sdcard.img; MAN=$DIR/manifest.json
  [ -r "$IMG" ] && [ -r "$MAN" ] || { echo "REFUSE: $IMG or $MAN missing"; exit 1; }
  mval() { python3 -I -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else v)' "$MAN" "$1"; }
  want_img=$(mval sdcard_img_sha256)
  want_boot=$(mval boot_area_sha256)
  want_rootfs=$(mval rootfs_area_sha256)
  rootfs_bytes=$(mval rootfs_area_bytes)
  layout=$(mval layout)
  table_hex=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mbr", {}).get("table_hex", ""))' "$MAN")
  FOW=$(python3 -I -c 'import json,sys; p=json.load(open(sys.argv[1])).get("partitions", []); print(1 if len(p) > 1 and p[1].get("format_on_write") else "")' "$MAN")
  file_bytes=$(stat -f %z "$IMG")
  IMG_BYTES=$(mval image_bytes); IMG_BYTES=${IMG_BYTES:-$(mval card_bytes)}; IMG_BYTES=${IMG_BYTES:-$file_bytes}
  [[ $IMG_BYTES =~ ^[0-9]+$ ]] || { echo "REFUSE: manifest image_bytes '$IMG_BYTES' is not a number"; exit 1; }
  [ "$file_bytes" = "$IMG_BYTES" ] || { echo "REFUSE: sdcard.img is $file_bytes bytes, manifest image_bytes $IMG_BYTES"; exit 1; }
  [ $((IMG_BYTES % BS)) = 0 ] && [ "$IMG_BYTES" -ge "$BOOT" ] || { echo "REFUSE: image size $IMG_BYTES is not a multiple of $BS or < $BOOT"; exit 1; }
  case "$MODE" in
    --rootfs)
      [ -n "$want_rootfs" ] && [ -n "$rootfs_bytes" ] || { echo "REFUSE: --rootfs needs a data-layout image (mkcard.py --data-partition)"; exit 1; }
      [ $((rootfs_bytes % BS)) = 0 ] || { echo "REFUSE: rootfs area $rootfs_bytes is not a multiple of $BS"; exit 1; } ;;
    --format-data) [ "$layout" = data ] || { echo "REFUSE: --format-data needs a data-layout card dir (mkcard.py --data-partition)"; exit 1; } ;;
  esac
  if [ -n "$FOW" ]; then
    [ "$IMG_BYTES" = "$rootfs_bytes" ] || { echo "REFUSE: data-layout image is $IMG_BYTES bytes, not the rootfs area $rootfs_bytes"; exit 1; }
  fi
  if { [ -n "$MODE" ] || [ -n "$FOW" ]; } && [ -z "$table_hex" ]; then echo "REFUSE: manifest.json has no mbr.table_hex (rebuild with mkcard.py)"; exit 1; fi
elif [ -n "$MODE" ]; then
  echo "REFUSE: $MODE needs a card dir"; exit 1
fi

[[ $D =~ ^disk[0-9]+$ ]] || { echo "REFUSE: '$D' is not a whole-disk id like disk7 (partitions such as disk7s1 are refused)"; exit 1; }
guard() { python3 -I "$HERE/diskguard.py" "$D" --image-bytes "$IMG_BYTES"; }
echo "== disk guards for /dev/$D (image $IMG_BYTES bytes)"
guard || exit 1
P2=
if [ -n "$DIR" ]; then
  echo "== sha256 of the image (whole file)"
  [ "$(shasum -a 256 "$IMG" | cut -d' ' -f1)" = "$want_img" ] || { echo "REFUSE: image sha256 != manifest"; exit 1; }
  if [ -n "$FOW" ] && [ -z "$MODE" ]; then
    disk_bytes=$(python3 -I "$HERE/diskguard.py" "$D" --print-size)
    P2=$(python3 -I "$HERE/mbrguard.py" p2-for-disk "$disk_bytes") || { echo "$P2"; exit 1; }
    echo "data layout: p2 = LBA 655360 + $P2 sectors (disk $disk_bytes bytes, rounded down to 32 KiB), formatted on the card"
  fi
fi
if [ -n "$CHECK" ]; then
  if [ -n "$DIR" ]; then echo "CHECK OK: would write ${MODE:-the whole image} of $DIR to /dev/$D (nothing written)"
  else echo "CHECK OK: /dev/$D passes the disk guards (nothing written; give a card dir to check the image too)"; fi
  exit 0
fi
if [ "$MODE" = --format-data ] || { [ -n "$FOW" ] && [ -z "$MODE" ]; }; then
  echo "WARNING: this erases partition 2 (RC2DATA: books, KOReader settings) on /dev/$D"
fi
if [ -z "$YES" ]; then
  answer=
  read -r -p "Overwrite /dev/$D? Type the disk id ($D) to continue: " answer </dev/tty \
    || { echo; echo "REFUSE: no answer (no terminal? --yes skips the prompt)"; exit 1; }
  [ "$answer" = "$D" ] || { echo "REFUSE: typed '$answer', not $D"; exit 1; }
fi
guard >/dev/null || { echo "REFUSE: /dev/$D no longer passes the disk guards (card swapped?)"; exit 1; }
case "$MODE" in
  --boot-area) n=$((BOOT / BS)); want=$want_boot; what="first $BOOT bytes (boot area)" ;;
  --rootfs) n=$((rootfs_bytes / BS)); want=$want_rootfs; what="first $rootfs_bytes bytes (boot area + partition 1)" ;;
  --format-data) n=0; want=; what= ;;
  *) n=$((IMG_BYTES / BS)); want=$want_img; what="whole image ($IMG_BYTES bytes)" ;;
esac
tmpd=$(mktemp -d)
trap 'rm -rf "$tmpd"' EXIT

diskutil unmountDisk "/dev/$D"
if [ -n "$MODE" ]; then
  echo "== MBR guard: the card's partition table must equal the image's"
  dd if="/dev/r$D" of="$tmpd/card-head" bs=$BS count=1 2>/dev/null
  if [ -n "$FOW" ]; then
    python3 -I "$HERE/mbrguard.py" "$tmpd/card-head" "$IMG" "$table_hex" --p2-any-length || exit 1
    P2=$(python3 -I "$HERE/mbrguard.py" card-p2 "$tmpd/card-head")
  else
    python3 -I "$HERE/mbrguard.py" "$tmpd/card-head" "$IMG" "$table_hex" || exit 1
  fi
fi
if [ "$n" -gt 0 ]; then
  if [ -n "$FOW" ]; then
    # data layout: the first 32 KiB block carries the MBR with the p2 length of this card. It goes last: macOS rereads
    # the partition table as soon as the MBR changes and holds the disk busy for a moment (EBUSY on the next dd)
    python3 -I "$HERE/mbrguard.py" patch "$IMG" "$tmpd/head" "$P2"
    want=$(python3 -I "$HERE/mbrguard.py" sha "$IMG" "$tmpd/head" $((n * BS)))
    echo "== write $what: $n x 32 KiB, offset 32 KiB to the end first, then the first block (MBR p2 length $P2 sectors)"
    dd if="$IMG" of="/dev/r$D" bs=$BS skip=1 seek=1 count=$((n - 1)) conv=notrunc
    dd if="$tmpd/head" of="/dev/r$D" bs=$BS count=1 conv=notrunc
  else
    echo "== write $what: $n x 32 KiB from offset 0"
    dd if="$IMG" of="/dev/r$D" bs=$BS count="$n" conv=notrunc
  fi
  sync
  echo "== read back $what"
  diskutil unmountDisk "/dev/$D" >/dev/null 2>&1 || true
  if [ -n "$FOW" ]; then
    got=$(dd if="/dev/r$D" bs=$BS count="$n" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
    [ "$got" = "$want" ] || { echo "READBACK MISMATCH: $got != $want (image with p2 = $P2 sectors)"; exit 2; }
    dd if="/dev/r$D" of="$tmpd/card-head" bs=$BS count=1 2>/dev/null
    python3 -I "$HERE/mbrguard.py" written "$tmpd/card-head" "$IMG" "$P2" || exit 2
    echo "READBACK OK $got"
  elif [ -z "$MODE" ] && [ -n "$want_rootfs" ]; then
    # Full data-layout image (--data-img): macOS automounts the new FAT32 RC2DATA (p2) as soon as dd closes the disk and
    # writes its own files there (.fseventsd, the volume dirty flag), so a whole-card hash cannot match (seen on
    # three writes to two cards). Verify [0, end of p1) strictly; p2 must either match the image or pass fsck_msdos -n.
    nr=$((rootfs_bytes / BS))
    got=$(dd if="/dev/r$D" bs=$BS count="$nr" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
    [ "$got" = "$want_rootfs" ] || { echo "READBACK MISMATCH (boot area + partition 1): $got != $want_rootfs"; exit 2; }
    echo "READBACK OK boot area + partition 1 $got"
    want_p2=$(python3 -I -c 'import json,sys; print([p["sha256"] for p in json.load(open(sys.argv[1]))["partitions"] if p.get("label")=="RC2DATA"][0])' "$MAN")
    got_p2=$(dd if="/dev/r$D" bs=$BS skip="$nr" count=$(((IMG_BYTES - rootfs_bytes) / BS)) 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
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
fi
if [ "$MODE" = --format-data ] || { [ -n "$FOW" ] && [ -z "$MODE" ]; }; then
  echo "== format partition 2: FAT32 RC2DATA (newfs_msdos), then fsck_msdos -n"
  diskutil unmountDisk "/dev/$D" >/dev/null 2>&1 || true
  python3 -I "$HERE/formatdata.py" "$D" || exit 2
  fsck_msdos -n "/dev/r${D}s2" || { echo "FORMAT FAIL: fsck_msdos -n on partition 2"; exit 2; }
  echo "FORMAT OK: partition 2 is an empty FAT32 RC2DATA"
fi
diskutil eject "/dev/$D"
echo "done: card ejected, take it out of the reader"
