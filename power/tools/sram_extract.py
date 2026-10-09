#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract and disassemble the SRAM suspend code of the stock RC2 kernel Image (raw ARM, VA = file offset + 0xc0408000).

rk29_sram_init (0xc040edd8) memcpy's the __sramfunc code from LMA 0xc0b6e000 to SRAM VA 0xfef00010..0xfef01b28 (6936 B) and
the __sramdata from LMA 0xc0b6fb18 to 0xfef01b28..0xfef01d14 (492 B); dmesg prints the same ranges ("CPU SRAM: copied sram
code from c0b6e000 to fef00010 - fef01b28"). There are no kallsyms for SRAM, so the labels below come from this analysis
(see ../README.md section 1.2; [STRONG] unless noted). The Image is only read, never executed.

usage: python3 -I sram_extract.py IMAGE OUTDIR   -> OUTDIR/sram-code.bin, sram-data.bin, sram-code.s (labelled), sram-data.txt
IMAGE: raw stock RC2 kernel Image, 2017-11-07 build (sha256 checked). Env: OBJDUMP (GNU objdump, default 'objdump').
The outputs are extracts of vendor code: keep them local.
"""
import hashlib
import os
import re
import struct
import subprocess
import sys

SHA = '47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af'
BASE = 0xc0408000
CODE_LMA, CODE_VMA, CODE_LEN = 0xc0b6e000, 0xfef00010, 0x1b18
DATA_LMA, DATA_VMA, DATA_LEN = 0xc0b6fb18, 0xfef01b28, 0x1ec
OBJDUMP = os.environ.get('OBJDUMP', 'objdump')   # GNU objdump with ARM support

LABELS = {  # SRAM VA -> name (rychly mach-rk3026/pm.c, i2c_sram.c, mach-rk2928/ddr.c names)
    0xfef00a4c: 'ddr_suspend',
    0xfef00b80: 'ddr_resume',
    0xfef01110: 'rk_pm_soc_sram_clk_gating',
    0xfef01194: 'rk_pm_soc_sram_clk_ungating',
    0xfef011ec: 'rk_pm_soc_sram_uart_suspend',
    0xfef01214: 'rk_pm_soc_sram_uart_resume',
    0xfef01238: 'rk_pm_soc_sram_sys_clk_suspend',
    0xfef01264: 'rk_pm_soc_sram_sys_clk_resume',
    0xfef01288: 'sram_printch',
    0xfef01364: 'rk_pm_soc_sram_volt_suspend',
    0xfef0139c: 'rk_pm_soc_sram_volt_resume',
    0xfef013d0: 'rk3026_sram_suspend',
    0xfef014f0: 'onyx_sram_sleep_gpios(0=suspend,1=resume)  [GPIO0_A3 pmu_gpio/VSEL?, GPIO2_B4 lcd_d10]',
    0xfef0152c: 'sram_i2c_init',
    0xfef01584: 'sram_i2c_deinit',
    0xfef01740: 'sram_i2c_write(addr,reg,val)',
    0xfef01794: 'sram_i2c_read(addr,reg)',
    0xfef017f0: 'rk30_suspend_voltage_set  (board, ACT8931 @0x5b)',
    0xfef01888: 'rk30_suspend_voltage_resume  (board, ACT8931 @0x5b)',
    0xfef01940: 'rk30_pwm_logic_suspend_voltage (weak, empty)',
    0xfef01944: 'rk30_pwm_logic_resume_voltage (weak, empty)',
    0xfef01948: 'board_pmu_suspend (weak, empty)',
    0xfef0194c: 'board_pmu_resume (weak, empty)',
    0xfef019fc: 'sram_printascii',
    0xfef01a24: 'sram_printhex',
}
DATA = {
    0xfef01cd0: 'rk_soc_pm_ctr_flags_sram (= 0; rk_soc_pm_ctr_bits_prepare has no caller)',
    0xfef01cd4: 'sram_pm_state (written by rk3026_pm_enter: 2 = idle, 3 = mem)',
    0xfef01cec: 'ONYX: ACT8931 LDO1 (touch) off-in-mem enable (1; onyx_pcb_ver_setup clears it for pcb_ver=3)',
}


def main():
    img_path, out = sys.argv[1], sys.argv[2]
    img = open(img_path, 'rb').read()
    if hashlib.sha256(img).hexdigest() != SHA:
        sys.exit('not the stock RC2 kernel Image (sha256 mismatch)')
    os.makedirs(out, exist_ok=True)
    code = img[CODE_LMA - BASE:CODE_LMA - BASE + CODE_LEN]
    data = img[DATA_LMA - BASE:DATA_LMA - BASE + DATA_LEN]
    open(os.path.join(out, 'sram-code.bin'), 'wb').write(code)
    open(os.path.join(out, 'sram-data.bin'), 'wb').write(data)
    lst = subprocess.run([OBJDUMP, '-D', '-b', 'binary', '-m', 'arm', '--adjust-vma=0x%x' % CODE_VMA,
                          os.path.join(out, 'sram-code.bin')], capture_output=True, text=True, check=True).stdout
    with open(os.path.join(out, 'sram-code.s'), 'w') as f:
        for line in lst.splitlines():
            m = re.match(r'\s*([0-9a-f]+):', line)
            if m and int(m.group(1), 16) in LABELS:
                f.write('\n%s <%s>:\n' % (m.group(1), LABELS[int(m.group(1), 16)]))
            m2 = re.search(r'\b(bl|blx|b)\s+0x([0-9a-f]+)', line)
            if m2 and int(m2.group(2), 16) in LABELS:
                line += '   <%s>' % LABELS[int(m2.group(2), 16)].split()[0]
            f.write(line + '\n')
    with open(os.path.join(out, 'sram-data.txt'), 'w') as f:
        for va in range(DATA_VMA, DATA_VMA + DATA_LEN, 4):
            v, = struct.unpack_from('<I', data, va - DATA_VMA)
            f.write('%08x: %08x %s\n' % (va, v, DATA.get(va, '')))
    print('SRAM code %d B @0x%08x (LMA 0x%08x, file 0x%x), data %d B @0x%08x -> %s'
          % (CODE_LEN, CODE_VMA, CODE_LMA, CODE_LMA - BASE, DATA_LEN, DATA_VMA, out))


if __name__ == '__main__':
    main()
