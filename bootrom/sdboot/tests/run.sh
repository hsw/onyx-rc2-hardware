#!/bin/bash
# SPDX-License-Identifier: MIT
# Build everything twice (reproducibility) and run all host tests. No device and no disk is touched.
# usage: tests/run.sh OUTDIR
# Produces OUTDIR/{stage2,inputs,ramdisk-sd,card-m0,card-m0-halt} and OUTDIR/test-report.txt.
#
# Optional inputs (environment); without them the tests use synthetic stand-ins (tests/fake_inputs.py) and skip what
# needs the real thing:
#   RC2_BOOTROM   your 16 KB RK3026 BootROM dump: enables the Unicorn tests (ROM SD path, stage2 end to end, ROM checks)
#   RK_RC4_KEY    the Rockchip IDBlock RC4 key (32 hex digits): with RC2_BOOTROM, enables the full ROM -> IDB -> stage2 chain
#   RC2_IDB, RC2_KERNEL, RC2_WAVEFORM   your stock IDB dump, kernel Image, ebc_waveform.bin (all three, plus RK_RC4_KEY):
#                 the cards are built from them instead of the stand-ins; RC2_LOADER (RKBOOT file) adds the FlashData check
#   RC2_BUSYBOX, RC2_EBC_CONSOLE   binaries for the m0 ramdisk (default: a placeholder busybox, no ebc-console)
# Tools: python3, uv (Unicorn/capstone scripts), LLVM clang + ld.lld, e2fsprogs; optional mtools, dosfstools, shellcheck.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
A=${1:?usage: tests/run.sh OUTDIR}
mkdir -p "$A"
A=$(cd "$A" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
rep=$A/test-report.txt
: >"$rep"
step() { echo "== $*" | tee -a "$rep"; }
same() { # same <what> <file1> <file2>
  if cmp -s "$2" "$3"; then echo "PASS reproducible: $1" | tee -a "$rep"; else echo "FAIL not reproducible: $1" | tee -a "$rep"; exit 1; fi
}
step "inputs"
python3 -I "$here/tests/fake_inputs.py" "$A/inputs" | tee -a "$rep"
if [ -n "${RC2_IDB:-}" ] && [ -n "${RC2_KERNEL:-}" ] && [ -n "${RC2_WAVEFORM:-}" ]; then
  [ -n "${RK_RC4_KEY:-}" ] || { echo "FAIL: RC2_IDB needs RK_RC4_KEY" | tee -a "$rep"; exit 1; }
  IN=(--idb "$RC2_IDB" --kernel "$RC2_KERNEL" --waveform "$RC2_WAVEFORM")
  [ -n "${RC2_LOADER:-}" ] && IN+=(--loader "$RC2_LOADER")
  WF=$RC2_WAVEFORM
  echo "stock inputs: your IDB dump, kernel and waveform" | tee -a "$rep"
else
  IN=(--idb "$A/inputs/idb.bin" --kernel "$A/inputs/kernel.bin" --waveform "$A/inputs/waveform.bin")
  WF=$A/inputs/waveform.bin
  RK_RC4_KEY=$(cat "$A/inputs/rc4key.txt")
  echo "stock inputs: synthetic stand-ins (tests/fake_inputs.py)" | tee -a "$rep"
fi
export RK_RC4_KEY
RDIN=(--busybox "${RC2_BUSYBOX:-$A/inputs/busybox}" --waveform "$WF")
[ -n "${RC2_EBC_CONSOLE:-}" ] && RDIN+=(--ebc-console "$RC2_EBC_CONSOLE")

step "stage2 build x2"
"$here/stage2/build.sh" "$A/stage2" | tee -a "$rep"
"$here/stage2/build.sh" "$tmp/stage2" >/dev/null
same stage2.bin "$A/stage2/stage2.bin" "$tmp/stage2/stage2.bin"
step "ramdisk-sd build x2"
python3 -I "$here/ramdisk-sd/mkramdisk-sd.py" --out "$A/ramdisk-sd" "${RDIN[@]}" | tee -a "$rep"
python3 -I "$here/ramdisk-sd/mkramdisk-sd.py" --out "$tmp/rd" "${RDIN[@]}" >/dev/null
same ramdisk-sd.cpio.gz "$A/ramdisk-sd/ramdisk-sd.cpio.gz" "$tmp/rd/ramdisk-sd.cpio.gz"
RD=$A/ramdisk-sd/ramdisk-sd.cpio.gz
step "card images (m0: boots the kernel; m0-halt: stage2 loads + verifies, never jumps)"
python3 -I "$here/mkcard.py" --name rc2-sdboot-m0 --stage2 "$A/stage2/stage2.bin" --ramdisk "$RD" "${IN[@]}" \
  --out "$A/card-m0" | tee -a "$rep"
python3 -I "$here/mkcard.py" --name rc2-sdboot-m0-halt --halt --stage2 "$A/stage2/stage2.bin" --ramdisk "$RD" "${IN[@]}" \
  --out "$A/card-m0-halt" | tee -a "$rep"
python3 -I "$here/mkcard.py" --name rc2-sdboot-m0 --stage2 "$tmp/stage2/stage2.bin" --ramdisk "$tmp/rd/ramdisk-sd.cpio.gz" \
  "${IN[@]}" --out "$tmp/card" >/dev/null
a=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sdcard_img_sha256"])' "$A/card-m0/manifest.json")
b=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sdcard_img_sha256"])' "$tmp/card/manifest.json")
if [ "$a" = "$b" ]; then echo "PASS reproducible: sdcard.img $a" | tee -a "$rep"
else echo "FAIL sdcard.img differs" | tee -a "$rep"; exit 1; fi
rm -f "$tmp/card/sdcard.img"
step "static no-write / no-eMMC check"
uv run -q --script "$here/tests/check_nowrite.py" "$A/stage2/stage2.bin" | tee -a "$rep"
step "BootROM SD read path on the ROM dump (Unicorn)"
uv run -q --script "$here/tests/test_rom_sd.py" "$A/card-m0/sdcard.img" "$A/card-m0/trace" | tee -a "$rep"
step "stage2 end to end (Unicorn): ROM -> IDB -> stage2 -> kernel entry, SDHC, failure paths"
uv run -q --script "$here/tests/test_stage2.py" "$A/card-m0" "$A/stage2" | tee -a "$rep"
step "stage2 HALT card"
uv run -q --script "$here/tests/test_stage2.py" "$A/card-m0-halt" "$A/stage2" --expect-halt | tee -a "$rep"
step "ramdisk init"
"$here/tests/test_ramdisk_init.sh" "$A/card-m0" | tee -a "$rep"
step "card layouts: --data-partition (ext4 256 MiB, p2 formatted on write) x2, rootfs resize, --card-bytes, --data-img, MBR guard"
python3 -I "$here/tests/test_card_layout.py" "$A/stage2/stage2.bin" "$RD" "$tmp/layout" "$A/card-m0" -- "${IN[@]}" \
  | tee -a "$rep"
step "write-card.sh disk guards: diskutil fixtures, --check refusals on this Mac (nothing unmounted or written)"
python3 -I "$here/tests/check_write_guard.py" "$A/card-m0" | tee -a "$rep"
step "data layout write path on sparse disk images (2 GB, 32 GiB): p2 length, readback, newfs_msdos RC2DATA, mount (macOS)"
python3 -I "$here/tests/test_format_data.py" "$tmp/format" | tee -a "$rep"
step "shellcheck"
if command -v shellcheck >/dev/null; then
  shellcheck "$here/write-card.sh" "$here/mkdata.sh" "$here/tests/run.sh" "$here/tests/test_ramdisk_init.sh" \
    "$here/stage2/build.sh" && echo "PASS shellcheck" | tee -a "$rep"
else echo "SKIP shellcheck: not installed" | tee -a "$rep"; fi
if grep -q '^FAIL\|RESULT FAIL' "$rep"; then echo "SOME TESTS FAILED (see $rep)"; exit 1; fi
echo "ALL PASS, $(grep -c '^SKIP' "$rep") SKIP lines (report $rep)"
