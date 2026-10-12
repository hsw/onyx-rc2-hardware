#!/bin/bash
# SPDX-License-Identifier: MIT
# Host checks of ramdisk-sd/init: POSIX syntax, shellcheck, no storage access in the script, and the stage2-log decoder
# (s2log) run against the 4 KiB log that test_stage2.py dumped from the emulated DDR, with a fake busybox devmem
# (SKIP when there is no such log: test_stage2.py needs the BootROM dump).
# usage: tests/test_ramdisk_init.sh <card dir with trace/stage2-log.{bin,txt}>
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
init=$here/ramdisk-sd/init
trace=${1:?card dir}/trace
fail=0
ok() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }
if sh -n "$init"; then ok "init: sh -n"; else bad "init: sh -n"; fi
if shellcheck -s sh -e SC2016,SC3045 "$init"; then ok "init: shellcheck"; else bad "init: shellcheck"; fi
# no storage: no insmod/modprobe, no mount of anything but proc/sysfs/devtmpfs/tmpfs, no block devices, no mtd
if grep -nE 'insmod|modprobe|/dev/(block|mtd|mmcblk)|rk30xxnand|switch_root|losetup' "$init" | grep -v '^[0-9]*:#'; then
  bad "init: storage-related command above"
else ok "init: no insmod, no block device, no mtd, no switch_root"; fi
mounts=$(grep -oE 'mount -t [a-z]+' "$init" | sort -u | tr '\n' ' ')
if [ "$mounts" = "mount -t devtmpfs mount -t proc mount -t sysfs mount -t tmpfs " ]; then ok "init: mounts only $mounts"
else bad "init: unexpected mounts: $mounts"; fi
# s2log against the emulated log
if [ ! -r "$trace/stage2-log.bin" ]; then
  echo "SKIP init: s2log decoder (no emulated stage2 log in $trace: needs the BootROM dump)"
  echo "RESULT $([ $fail = 0 ] && echo PASS || echo FAIL)"
  exit $fail
fi
tmp=$(mktemp -d)
cat >"$tmp/bb" <<EOS
#!/bin/bash
# fake busybox: devmem ADDR 32 -> word from the dumped log at 0x7fff0000
if [ "\$1" = devmem ]; then
  off=\$(( \$2 - 0x7fff0000 ))
  printf '0x%08X\n' "\$(od -An -tu4 -j "\$off" -N4 "$trace/stage2-log.bin" | tr -d ' ')"
else shift; exec "\$@"; fi
EOS
chmod +x "$tmp/bb"
sed -n '/^s2log() {/,/^}/p' "$init" >"$tmp/s2log.sh"
B=$tmp/bb bash -c ". $tmp/s2log.sh; s2log" >"$tmp/out.txt"
head -1 "$tmp/out.txt"
if diff <(tail -n +2 "$tmp/out.txt") <(cat "$trace/stage2-log.txt"; echo) >/dev/null; then
  ok "init: s2log decodes the emulated stage2 log byte-identical ($(wc -l <"$trace/stage2-log.txt") lines)"
else
  bad "init: s2log output differs"; diff <(tail -n +2 "$tmp/out.txt") "$trace/stage2-log.txt" | head
fi
if grep -q 'stage2 log: stage 0x0000004A fail 0x00000000' "$tmp/out.txt"; then ok "init: s2log header line"
else bad "init: header"; fi
rm -rf "$tmp"
echo "RESULT $([ $fail = 0 ] && echo PASS || echo FAIL)"
exit $fail
