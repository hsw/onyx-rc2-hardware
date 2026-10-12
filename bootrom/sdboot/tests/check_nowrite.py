# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.10"
# dependencies = ["capstone==5.0.7"]
# ///
"""Static guard: stage2 has no storage write path and no eMMC access.

usage: uv run --script tests/check_nowrite.py <stage2.bin> [<bootrom dump>]   (default dump: $RC2_BOOTROM)
Without a ROM dump only check 1 and the indirect-call count run; the ROM checks print SKIP.
1. stage2.bin: every 32-bit word, every movw/movt pair and every ARM modified immediate is checked; none may point into
   the eMMC controller (0x1021c000), SDIO (0x10218000), NAND controller (0x10500000), SPI (0x20074000) or the SD
   controller itself (0x10214000; stage2 never drives it, only the ROM does).
2. stage2.bin: the only BootROM routine it can call is the SD read 0x168c: no other ROM function entry (bl targets of
   the ROM) appears as a constant, and there is exactly one indirect call (blx in rom_call).
3. ROM read closure (0x168c and every function it reaches): the SD command values it can write are only CMD17 0x2351,
   CMD18 0x2352 and CMD12 0x1414c (DW "write" bit 0x400 clear); the controller base is chosen only between SDMMC0 and
   the eMMC controller by IMEM+0x44, which stage2 checks (== 0) before the first call.
"""
import os, struct, sys
import capstone
from capstone import arm_const

FORBIDDEN = [(0x1021c000, 0x4000, 'eMMC controller'), (0x10218000, 0x4000, 'SDIO controller'),
             (0x10500000, 0x8000, 'NAND controller'), (0x20074000, 0x4000, 'SPI0'),
             (0x10214000, 0x4000, 'SD controller (stage2 must not drive it itself)')]
fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def forbidden(v):
    return [n for b, s, n in FORBIDDEN if b <= v < b + s]


s2 = open(sys.argv[1], 'rb').read()
rom_path = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('RC2_BOOTROM')
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
md.detail = True
md.skipdata = True

# ---- 1. constants in stage2
consts = set(struct.unpack_from('<%dI' % (len(s2) // 4), s2))
insns = list(md.disasm(s2, 0x60080000))
movw = {}
blx = []
for i in insns:
    if i.id == arm_const.ARM_INS_MOVW:
        movw[i.operands[0].reg] = i.operands[1].imm & 0xffff
        consts.add(i.operands[1].imm & 0xffff)
    elif i.id == arm_const.ARM_INS_MOVT and i.operands[0].reg in movw:
        consts.add(movw.pop(i.operands[0].reg) | ((i.operands[1].imm & 0xffff) << 16))
    elif i.id in (arm_const.ARM_INS_MOV, arm_const.ARM_INS_ORR, arm_const.ARM_INS_ADD):
        for op in i.operands:
            if op.type == arm_const.ARM_OP_IMM:
                consts.add(op.imm & 0xffffffff)
    if i.id == arm_const.ARM_INS_BLX and i.operands[0].type == arm_const.ARM_OP_REG:
        blx.append(i.address)
bad = sorted((hex(v), forbidden(v)) for v in consts if forbidden(v))
check(not bad, f'stage2: no constant points into a storage controller ({len(consts)} constants scanned) {bad}')

check(len(blx) == 1, f'stage2: exactly one indirect call (rom_call): {[hex(a) for a in blx]}')
if not rom_path:
    print('SKIP ROM checks (the only ROM routine is 0x168c; the ROM read closure sends only CMD17/18/12): '
          'no BootROM dump (argument or RC2_BOOTROM)')
    print('RESULT', 'FAIL' if fails else 'PASS', f'({len(fails)} failures, ROM checks skipped)')
    sys.exit(1 if fails else 0)
rom = open(os.path.expanduser(rom_path), 'rb').read()

# ---- 2. ROM routines referenced by stage2
rom_insns = list(md.disasm(rom, 0))
rom_funcs = {i.operands[0].imm for i in rom_insns if i.id == arm_const.ARM_INS_BL and i.operands[0].type ==
             arm_const.ARM_OP_IMM}
rom_funcs |= {0x168c, 0x1714, 0x1728, 0x1730, 0x15ac}           # table entries reached through pointers
refs = sorted(v for v in consts if v in rom_funcs or (0x10100000 <= v < 0x10104000 and v - 0x10100000 in rom_funcs))
check(refs == [0x168c], f'stage2: the only ROM routine constant is the SD read 0x168c: {[hex(r) for r in refs]}')

# ---- 3. the ROM read closure and its command values
todo, seen = [0x168c], set()
by_addr = {i.address: i for i in rom_insns}
starts = sorted(rom_funcs | {0xd8, 0x168c, 0x1714, 0x171c, 0x1728, 0x1730, 0x1738, 0x176c, 0x17a8})
cmd_values = set()
while todo:                                     # a routine spans [entry, next routine entry): conservative
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    end = next((x for x in starts if x > f), len(rom))
    for a in range(f, end, 4):
        i = by_addr.get(a)
        if i is None:
            continue
        if i.id in (arm_const.ARM_INS_BL, arm_const.ARM_INS_B) and i.operands[0].type == arm_const.ARM_OP_IMM \
                and not f <= i.operands[0].imm < end:
            todo.append(i.operands[0].imm)
        if i.id in (arm_const.ARM_INS_MOVW, arm_const.ARM_INS_MOV) and len(i.operands) > 1 and \
                i.operands[1].type == arm_const.ARM_OP_IMM:
            cmd_values.add(i.operands[1].imm & 0xffffffff)
        if i.id == arm_const.ARM_INS_LDR and i.operands[1].type == arm_const.ARM_OP_MEM and \
                i.operands[1].mem.base == arm_const.ARM_REG_PC:
            cmd_values.add(struct.unpack_from('<I', rom, i.address + 8 + i.operands[1].mem.disp)[0])
mmc_cmds = sorted(v for v in cmd_values if 0x40 <= v <= 0x7ffff and (v & 0x3f) in (12, 17, 18, 24, 25, 32, 33, 38)
                  and v & 0x40)
check({v & 0x3f for v in mmc_cmds} == {12, 17, 18} and all(not v & 0x400 for v in mmc_cmds),
      f'ROM read closure {sorted(hex(x) for x in seen)}: command values {[hex(v) for v in mmc_cmds]} '
      f'= CMD17/18/12 only, write bit clear')
check(0x1021c000 in cmd_values and 0x10214000 in cmd_values,
      'ROM read closure selects SDMMC0 or the eMMC controller (IMEM+0x44): stage2 must and does check it is 0')
print('RESULT', 'FAIL' if fails else 'PASS', f'({len(fails)} failures)')
sys.exit(1 if fails else 0)
