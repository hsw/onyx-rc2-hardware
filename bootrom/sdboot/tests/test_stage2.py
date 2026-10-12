# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.10"
# dependencies = ["unicorn==2.1.4"]
# ///
"""Host test of stage2 on the real BootROM code (Unicorn) against a card image built by mkcard.py.

usage: RC2_BOOTROM=<rom dump> uv run --script tests/test_stage2.py <card dir with sdcard.img + manifest.json>
           <stage2 dir with stage2.bin + .sym> [--quick] [--expect-halt]
Without RC2_BOOTROM it prints SKIP and exits 0.
Scenarios:
  chain-sdsc   ROM SD init (0x1728) + ROM IDB loader (0x1820) from card LBA 64: RC4 header, FlashData (stubbed: its
               sha256 is checked against the manifest; returns 0 like the real DDR init), stage2 loaded to 0x60000000 by
               the ROM, stage2 runs to the kernel entry. Checks registers, ATAGs, memory, log, peripheral writes, SD
               commands. Needs a card whose IDB is encrypted with the real Rockchip key (checked with the ROM's own
               S-box); otherwise it is skipped and direct-sdsc (stage2 started directly) does the same end checks.
  direct-sdhc  stage2 started directly (ROM state as after an SDHC boot: block addressing), same end checks.
  failures     bad magic, bad table CRC, kernel CRC mismatch, read error on the table / ramdisk, controller id != 0,
               HALT flag: stage2 must stop in fail(code, blob, val) / the halt loop and never reach the kernel.
--quick skips the two full runs that copy the whole kernel (chain-sdsc stays).
--expect-halt: a card built with mkcard.py --halt: the chain must load and verify every blob, then stop in the halt loop
without the remap write and without reaching the kernel.
"""
import hashlib, json, os, struct, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from rc2emu import (Card, Emu, IMEM, UC_ARM_REG_R4, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_CPSR,  # noqa: E402
                    UC_ARM_REG_PC, set_cpsr_svc, rom_path, skip_without_rom)
import rkidb  # noqa: E402

skip_without_rom('stage2 on the BootROM (Unicorn)')

card_dir, s2_dir = sys.argv[1], sys.argv[2]
quick = '--quick' in sys.argv
expect_halt = '--expect-halt' in sys.argv
IMG = os.path.join(card_dir, 'sdcard.img')
man = json.load(open(os.path.join(card_dir, 'manifest.json')))
stage2 = open(os.path.join(s2_dir, 'stage2.bin'), 'rb').read()
sym = {}
for line in open(os.path.join(s2_dir, 'stage2.sym')):
    a, t, n = line.split()
    sym[n] = int(a, 16)
FLASHDATA_SHA, FLASHDATA_LEN = man['idb']['flashdata_sha256'], 8 * 512
ROM = open(rom_path(), 'rb').read()
KENTRY, ATAGS, MACHINE = 0x60408000, 0x60000800, 3066
LOG = 0x7fff0000
fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def blob_bytes(card, b):
    return card.read(b['lba'], -(-b['size'] // 512))[:b['size']]


def table_overlay(card, mutate, fix_crc=True):
    t = bytearray(card.read(8192, 2))
    mutate(t)
    if fix_crc:
        struct.pack_into('<I', t, 0x3fc, zlib.crc32(bytes(t[:0x3fc])) & 0xffffffff)
    return {8192: bytes(t[:512]), 8193: bytes(t[512:])}


def make_emu(card):
    e = Emu(card)
    e.events = []                                   # ('progress', n) / ('fail', code, blob, val) / ('halt',)
    e.failing = False
    e.s2_start_writes = None

    def on_progress(e):
        e.events.append(('progress', e.reg(UC_ARM_REG_R0)))

    def on_fail(e):                                 # stop at its first delay: the log is written by then
        e.events.append(('fail', e.reg(UC_ARM_REG_R0), e.reg(UC_ARM_REG_R1), e.reg(UC_ARM_REG_R2)))
        e.failing = True

    def on_blink(e):
        if e.reg(UC_ARM_REG_R0) == 2500:            # only the HALT loop uses 2.5 s
            e.events.append(('halt',))
            e.stop('halt')

    def on_delay(e):
        if e.failing:
            e.stop('fail')
        e.ret()

    def on_kernel(e):
        e.stop('kernel')

    def on_s2(e):
        if e.s2_start_writes is None:
            e.s2_start_writes = len(e.periph_writes)
            e.s2_start_cmds = len(e.mmc.cmds)
    e.hook_at(sym['progress'], on_progress)
    e.hook_at(sym['fail'], on_fail)
    e.hook_at(sym['blink'], on_blink)
    e.hook_at(sym['delay_loops'], on_delay)
    e.hook_at(KENTRY, on_kernel)
    e.hook_at(0x60000000, on_s2)
    e.rom_targets = []

    def on_blx(e):                                  # the one indirect call: must always be the ROM SD read
        e.rom_targets.append(e.reg(UC_ARM_REG_R4))
    off = sym['rom_call'] - 0x60080000
    blx = next(off + k for k in range(0, 0x40, 4) if stage2[off + k:off + k + 4] == bytes.fromhex('34ff2fe1'))
    e.hook_at(0x60080000 + blx, on_blx)
    return e


def run_direct(card, sd_class=0x08, ctl=0):
    e = make_emu(card)
    e.rom_state(sd_class, ctl)
    e.uc.mem_write(0x60000000, stage2)
    set_cpsr_svc(e.uc)
    e.run(0x60000000, IMEM + 0x760, count=400_000_000)
    return e


def run_chain(card):
    e = make_emu(card)
    e.uc.mem_write(IMEM, struct.pack('<I', 24))
    e.uc.mem_write(IMEM + 0xc, struct.pack('<I', 0))
    e.flashdata_ok = None

    def on_flashdata(e):                            # the ROM calls the init stage with blx 0x10080804
        got = bytes(e.uc.mem_read(0x10080800, FLASHDATA_LEN))
        e.flashdata_ok = hashlib.sha256(got).hexdigest() == FLASHDATA_SHA
        e.ret(0)
    e.hook_at(0x10080804, on_flashdata)
    set_cpsr_svc(e.uc)
    mode = e.call(0x1728)
    e.init_mode = mode
    e.call(0x1820, (0, mode), count=600_000_000)
    return e


def log_text(e):
    magic, ver, ln, stage, fail, farg, fval = struct.unpack('<7I', bytes(e.uc.mem_read(LOG, 28)))
    txt = bytes(e.uc.mem_read(LOG + 32, ln)).decode('ascii', 'replace')
    return dict(magic=magic, stage=stage, fail=fail, fail_arg=farg, fail_val=fval, text=txt)


def end_checks(name, e, card):
    check(e.stop_reason == 'kernel' and not e.violations,
          f'{name}: reached kernel entry ({e.stop_reason}) without violations {e.violations}')
    if e.stop_reason != 'kernel':
        print(log_text(e)['text'])
        return
    r0, r1, r2 = e.reg(UC_ARM_REG_R0), e.reg(UC_ARM_REG_R1), e.reg(UC_ARM_REG_R2)
    cpsr, pc = e.reg(UC_ARM_REG_CPSR), e.reg(UC_ARM_REG_PC)
    check((pc, r0, r1, r2) == (KENTRY, 0, MACHINE, ATAGS),
          f'{name}: pc {pc:#x} r0 {r0} r1 {r1} r2 {r2:#x} == entry 0x60408000, 0, 3066, 0x60000800')
    check(cpsr & 0x1f == 0x13 and cpsr & 0xc0 == 0xc0 and not cpsr & 0x20,
          f'{name}: CPSR {cpsr:#x}: SVC, IRQ+FIQ masked, ARM state')
    try:
        sctlr = e.sctlr()
        check(sctlr & 0x1805 == 0, f'{name}: SCTLR {sctlr:#x}: MMU, D-cache, I-cache, branch prediction off')
    except Exception as ex:                                  # noqa: BLE001
        print(f'note: SCTLR not readable in this Unicorn ({ex})')
    for b in man['blobs']:
        load = int(b['load'], 16)
        got = bytes(e.uc.mem_read(load, b['size']))
        check(got == blob_bytes(card, b), f"{name}: {b['kind']} in DDR at {load:#x} equals the card blob ({b['size']} B)")
    words = struct.unpack('<7I', bytes(e.uc.mem_read(ATAGS, 28)))
    check(words[:5] == (5, 0x54410001, 0, 0, 0), f'{name}: ATAG_CORE size 5 flags 0 pagesize 0 rootdev 0: {words[:5]}')
    cl = man['boot_table']['cmdline']
    check(words[5] == (len(cl) + 13) >> 2 and words[6] == 0x54410009,
          f'{name}: ATAG_CMDLINE size {words[5]} tag {words[6]:#x}')
    got_cl = bytes(e.uc.mem_read(ATAGS + 28, len(cl) + 1))
    check(got_cl == cl.encode() + b'\0', f'{name}: cmdline in ATAG == manifest cmdline')
    end = ATAGS + 20 + words[5] * 4
    check(struct.unpack('<2I', bytes(e.uc.mem_read(end, 8))) == (0, 0), f'{name}: ATAG_NONE at {end:#x}, no other tags')
    lg = log_text(e)
    check(lg['magic'] == 0x474c3253 and lg['stage'] == 0x4a and lg['fail'] == 0 and 'jump' in lg['text'],
          f"{name}: stage2 log at 0x7fff0000: magic, stage 'J', no fail, ends with jump")
    w = e.periph_writes[e.s2_start_writes:]
    first3 = [(a, v) for a, v, pc in w[:3]]
    check(first3[0] == (0x200080b8, 0x00300000) and first3[1][0] == 0x20080000 and first3[1][1] & 4
          and first3[2][0] == 0x20080004 and first3[2][1] & 4,
          f'{name}: first stage2 peripheral writes = power hold GPIO1_A2 (iomux, DR, DDR): {[(hex(a), hex(v)) for a, v in first3]}')
    soc = [(i, v) for i, (a, v, pc) in enumerate(w) if a == 0x20008140]
    cru = [v for a, v, pc in w if a == 0x20000110]
    check(soc == [(len(w) - 1, 0x10001000)] or (soc and soc[-1][1] == 0x10001000 and all(
        a in (0x20084000,) for a, v, pc in w[soc[-1][0] + 1:])),
        f'{name}: GRF_SOC_CON0 = 0x10001000 (remap) written once, last (only LED writes may follow)')
    check(cru == [0x00100010], f'{name}: CRU_SOFTRST_CON0 = 0x00100010 (CPU1 held in reset, as stock): {cru}')
    cmds = e.mmc.cmds[e.s2_start_cmds:]
    kinds = {k for k, a, v, pc in cmds}
    check(kinds <= {12, 17, 18} and all(not v & 0x400 for k, a, v, pc in cmds),
          f'{name}: stage2 issued only CMD17/18/12 without the write bit ({len(cmds)} commands, kinds {sorted(map(str, kinds))})')
    leds = [(a, v) for a, v, pc in w if a == 0x20084000]
    check(any(v & 0x8000 for a, v in leds), f'{name}: status LED GPIO2_B7 was driven ({len(leds)} writes)')
    check(e.rom_targets and set(e.rom_targets) == {0x168c},
          f'{name}: every ROM call from stage2 went to the SD read 0x168c ({len(e.rom_targets)} calls)')
    prog = [x[1] for x in e.events if x[0] == 'progress']
    check(prog == list(range(1, 3 + len(man['blobs']))), f'{name}: progress codes {prog}')


# ---- chain on an SDSC card: ROM -> IDB -> FlashData (stub) -> stage2 -> kernel
card = Card(IMG, 'sdsc')
hdr = rkidb.rc4_sbox(card.read(64, 1), ROM[0x2e34:0x2e34 + 256])   # the ROM's own S-box, not our key
chain = struct.unpack_from('<I', hdr)[0] == rkidb.IDB_MAGIC
if chain:
    e = run_chain(card)
    main_run = 'chain-sdsc'
else:
    print('SKIP chain-sdsc: the card IDB is not encrypted with the key behind the ROM S-box (a test fixture key?); '
          'running direct-sdsc instead')
    e = run_direct(card)
    main_run = 'direct-sdsc'
if expect_halt:
    prog = [x[1] for x in e.events if x[0] == 'progress']
    lg = log_text(e)
    check(e.stop_reason == 'halt' and not e.violations, f'halt card: stopped in the halt loop ({e.stop_reason}) {e.violations}')
    check(prog == list(range(1, 3 + len(man['blobs']))), f'halt card: all blobs loaded and verified first: {prog}')
    check(lg['stage'] == 0x48 and 'HALT flag' in lg['text'], "halt card: log stage 'H'")
    check(not any(a == 0x20008140 for a, v, pc in e.periph_writes), 'halt card: no remap write, no jump')
    print('RESULT', 'FAIL' if fails else 'PASS', f'({len(fails)} failures)')
    sys.exit(1 if fails else 0)
if chain:
    check(e.init_mode == 0, f'chain-sdsc: ROM SD init mode {e.init_mode}')
    check(e.flashdata_ok is True, 'chain-sdsc: the ROM decrypted and called the FlashData from the card IDB')
    idb_reads = [r for r in e.mmc.reads[:e.s2_start_cmds or None] if r[0] < 8192]
    check(idb_reads and idb_reads[0] == (64, 1), f'chain-sdsc: ROM read the IDB header at LBA 64 first: {idb_reads[:3]}')
end_checks(main_run, e, card)
lg = log_text(e)
os.makedirs(os.path.join(card_dir, 'trace'), exist_ok=True)
open(os.path.join(card_dir, 'trace', 'stage2-log.txt'), 'w').write(lg['text'])
open(os.path.join(card_dir, 'trace', 'stage2-log.bin'), 'wb').write(bytes(e.uc.mem_read(LOG, 0x1000)))
print(f'--- stage2 log ({main_run}) ---\n' + lg['text'] + '---')

if not quick:
    card = Card(IMG, 'sdhc')
    end_checks('direct-sdhc', run_direct(card, sd_class=0x04), card)
    kb0 = man['blobs'][0]
    card = Card(IMG, 'sdsc', fail_once={8193, kb0['lba'] + 1000})
    e = run_direct(card)
    end_checks('transient read errors (table, kernel)', e, card)
    retries = struct.unpack('<I', bytes(e.uc.mem_read(LOG + 28, 4)))[0]
    check(retries == 2 and log_text(e)['text'].count('read error lba') == 2,
          f'transient read errors: stage2 retried each failed chunk once ({retries} retries logged)')

# ---- failure paths (stage2 started directly; must stop in fail() and never reach the kernel)
kb = man['blobs'][0]
rb = man['blobs'][1]
scenarios = [
    ('bad magic', dict(overlay=lambda c: table_overlay(c, lambda t: t.__setitem__(0, 0x00))), ('fail', 1, 0, 1)),
    ('bad table CRC', dict(overlay=lambda c: table_overlay(c, lambda t: t.__setitem__(0x100, ord('X')), fix_crc=False)),
     ('fail', 1, 0, 3)),
    ('blob over partition 1', dict(overlay=lambda c: table_overlay(
        c, lambda t: struct.pack_into('<I', t, 0x40 + 32 + 4, 131000))), ('fail', 1, 0, 29)),
    ('ramdisk onto stage2', dict(overlay=lambda c: table_overlay(
        c, lambda t: struct.pack_into('<I', t, 0x40 + 32 + 12, 0x60080000))), ('fail', 1, 0, 37)),
    ('read error on the table', dict(fail_lbas={8193}), ('fail', 2, 0, 8192)),
    ('read error in the ramdisk', dict(fail_lbas={rb['lba'] + 5}), ('fail', 2, 2, rb['lba'])),
    ('controller id 2 (eMMC)', dict(ctl=2), ('fail', 4, 0, 2)),
    ('HALT flag', dict(overlay=lambda c: table_overlay(c, lambda t: struct.pack_into('<I', t, 0xc, 1))), ('halt',)),
]
if not quick:
    scenarios.append(('kernel CRC mismatch', dict(overlay=lambda c: {kb['lba'] + 100: b'\x55' * 512}), ('fail', 3, 1, None)))
for name, cfg, want in scenarios:
    card = Card(IMG, 'sdsc', fail_lbas=cfg.get('fail_lbas', ()))
    if 'overlay' in cfg:
        card.overlay = cfg['overlay'](card)
    e = run_direct(card, ctl=cfg.get('ctl', 0))
    got = e.events[-1] if e.events else None
    ok = got is not None and got[0] == want[0] and all(w is None or g == w for g, w in zip(got[1:], want[1:]))
    ok = ok and e.stop_reason != 'kernel' and not e.violations
    lg = log_text(e)
    if want[0] == 'fail':
        ok = ok and lg['fail'] == want[1]
    check(ok, f'failure path "{name}": {got} (expected {want}), log fail {lg["fail"]}, violations {e.violations}')
    cmds = {k for k, a, v, pc in e.mmc.cmds}
    check(cmds <= {12, 17, 18}, f'failure path "{name}": only read commands {sorted(map(str, cmds))}')

print('RESULT', 'FAIL' if fails else 'PASS', f'({len(fails)} failures)')
sys.exit(1 if fails else 0)
