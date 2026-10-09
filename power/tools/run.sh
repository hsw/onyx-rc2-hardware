#!/bin/bash
# SPDX-License-Identifier: MIT
# Regenerate the power-management listings of the stock RC2 kernel Image.
# Usage: run.sh IMAGE KALLSYMS OUTDIR
#   IMAGE     raw (uncompressed) stock RC2 kernel Image, 2017-11-07 build (sha256 checked below)
#   KALLSYMS  symbol list written by ../../kernel/extract_kallsyms.py IMAGE KALLSYMS
#   OUTDIR    output directory (listings derived from vendor code: keep them local)
# Env: OBJDUMP (GNU objdump with ARM support; default: objdump on PATH).
# Needs: GNU binutils, python3. The Image is only read, never executed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ $# -ne 3 ]; then
  echo "usage: $0 IMAGE KALLSYMS OUTDIR" >&2
  exit 2
fi
IMG="$1"
SYMS="$2"
OUT="$3"
echo "47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af  $IMG" | shasum -a 256 -c -
mkdir -p "$OUT/fn"
grep -v '^#' "$HERE/pm.list" | while read -r f; do
  [ -n "$f" ] && python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" "$f" > "$OUT/fn/$f.s"
done
python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" --callers get_suspend_state suspend_irqwake_set pm_irqwake_enable \
  irq_set_irq_wake register_early_suspend hym8563_disable_alarm cw_disable_batt_low_irq rk28_send_wakeup_key \
  rk30_adc_ebc_battery_check act8931_charge_init act8931_charge_set_vbus_status act8931_charge_set_usb_status \
  act8931_charge_charge_level_set act8931_charge_charge_level_get act8931_charge_level_reset \
  rk_soc_pm_ctr_bits_prepare sram_gpio_init ddrfreq_set_sys_status > "$OUT/callers.txt"
python3 -I "$HERE/sram_extract.py" "$IMG" "$OUT"
# tables resolved through literal pools: pm_states[], rk3026 platform_suspend_ops, rk_soc_pm_helps[], sram_io_desc, key table
python3 -I "$HERE/kwords.py" "$IMG" c08c4be8:4 c0a6e0e4:9 c0a6e108:20 c042bc98:8 c0a7167c:66 > "$OUT/tables.txt"
echo "outputs in $OUT"
