# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.10"
# dependencies = ["unicorn==2.1.4"]
# ///
"""Step 2 evidence: run the BootROM's own SD code (init 0x1728 -> 0x15ac, read 0x168c) on the ROM dump against an
emulated SDMMC0 + card, and record every controller register access for a 1-sector and a multi-sector read.

usage: RC2_BOOTROM=<rom dump> uv run --script tests/test_rom_sd.py <sdcard.img> [trace-out-dir]
Without RC2_BOOTROM it prints SKIP and exits 0.
Checks: init leaves IMEM+0x40 class 8 (SDSC) / 4 (SDHC), +0x44 = 0 (SDMMC0), +0x46 = RCA; read(sector, buf, bytes)
returns 0 and the buffer equals the card; 1 sector = CMD17, more = CMD18 + CMD12; addressing sector<<9 (SDSC) or
sector (SDHC); a data CRC error returns 1; only ROM read-only commands; eMMC/SDIO/NAND controllers never touched;
the read path works from the 0x10100000 alias too and needs only IMEM+0 (delay), +0x40, +0x44.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rc2emu import Card, Emu, IMEM, skip_without_rom  # noqa: E402

skip_without_rom('BootROM SD read path')

img = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else None
fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def imem(e, off, n=4):
    b = bytes(e.uc.mem_read(IMEM + off, n))
    return int.from_bytes(b, 'little')


def fmt_cmds(cmds):
    return ' '.join((f'ACMD{k[1]}' if isinstance(k, tuple) else f'CMD{k}') + f'({a:#x})' for k, a, v, pc in cmds)


traces = []
for kind, cls in (('sdsc', 0x08), ('sdhc', 0x04)):
    card = Card(img, kind)
    e = Emu(card)
    e.uc.mem_write(IMEM, struct.pack('<I', 24))          # delay factor before PLL setup
    e.uc.mem_write(IMEM + 0xc, struct.pack('<I', 0))     # non-secure
    r = e.call(0x1728)
    check(r == 0 and not e.violations, f'{kind}: ROM SD init 0x1728 returns 0 ({r:#x}) {e.violations}')
    check(imem(e, 0x40) == cls, f'{kind}: IMEM+0x40 class {imem(e, 0x40):#x} == {cls:#x}')
    check(imem(e, 0x44, 1) == 0, f'{kind}: IMEM+0x44 controller id 0 (SDMMC0)')
    check(imem(e, 0x46, 2) == card.rca, f'{kind}: IMEM+0x46 RCA {imem(e, 0x46, 2):#x}')
    init_cmds = list(e.mmc.cmds)
    traces.append((f'{kind} init', init_cmds, list(e.mmc.accesses)))
    print(f'  {kind} init commands: {fmt_cmds(init_cmds)}')
    for sector, nbytes, fn in ((64, 512, 0x168c), (8192, 0x800, 0x168c), (16384, 64 * 512, 0x1010168c)):
        e.mmc.cmds.clear(); e.mmc.accesses.clear()
        buf = 0x60000000 + sector * 16
        r = e.call(fn, (sector, buf, nbytes))
        got = bytes(e.uc.mem_read(buf, nbytes))
        want = card.read(sector, nbytes // 512)
        exp_arg = sector << 9 if kind == 'sdsc' else sector
        cmds = [(k, a) for k, a, v, pc in e.mmc.cmds]
        exp = [(17, exp_arg)] if nbytes == 512 else [(18, exp_arg), (12, 0)]
        check(r == 0 and got == want and cmds == exp and not e.violations,
              f'{kind}: read({sector}, {buf:#x}, {nbytes}) via {fn:#x} -> {r}, data ok {got == want}, cmds {cmds}')
        traces.append((f'{kind} read sector {sector} bytes {nbytes} via {fn:#x}', list(e.mmc.cmds),
                       list(e.mmc.accesses)))
    # a data CRC error on the second sector of a multi-sector read
    card.fail_lbas = {16385}
    e.mmc.cmds.clear()
    r = e.call(0x168c, (16384, 0x60200000, 4 * 512))
    check(r == 1, f'{kind}: CRC error -> read returns 1 ({r}), commands {[k for k, a, v, pc in e.mmc.cmds]}')
    card.fail_lbas = set()
    r = e.call(0x168c, (64, 0x60200000, 512))
    check(r == 0, f'{kind}: next read after the error works ({r})')
    # the read path state: only IMEM+0, +0x40, +0x44 matter; wipe the rest of IMEM state and read again
    saved = bytes(e.uc.mem_read(IMEM, 0x800))
    e.uc.mem_write(IMEM, b'\xa5' * 0x800)
    e.uc.mem_write(IMEM, saved[:4])
    e.uc.mem_write(IMEM + 0x40, saved[0x40:0x48])
    r = e.call(0x168c, (64, 0x60300000, 512), sp=0x60f00000)
    check(r == 0 and bytes(e.uc.mem_read(0x60300000, 512)) == card.read(64, 1),
          f'{kind}: read with IMEM 0..0x7ff garbage except +0, +0x40..0x47, stack in DDR -> {r}')
    check(not e.violations, f'{kind}: no violations {e.violations}')

if out:
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'rom-sd-trace.txt'), 'w') as f:
        f.write('# BootROM SD path on the ROM dump, emulated SDMMC0 (tests/test_rom_sd.py). Register offsets from 0x10214000.\n'
                '# FIFO (0x200) reads: first and last word only; RINTSTS/STATUS polls (0x44/0x48 reads) omitted.\n')
        for title, cmds, acc in traces:
            f.write(f'\n== {title}\ncommands: {fmt_cmds(cmds)}\n')
            for rw, off, v in acc:
                f.write(f'  {rw} +{off:#05x} {v:#010x}\n')
    print('trace written to', os.path.join(out, 'rom-sd-trace.txt'))
print('RESULT', 'FAIL' if fails else 'PASS', f'({len(fails)} failures)')
sys.exit(1 if fails else 0)
