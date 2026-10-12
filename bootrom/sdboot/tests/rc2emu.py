# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.10"
# dependencies = ["unicorn==2.1.4"]
# ///
"""Unicorn model of the RK3026 boot path for sdboot: the real BootROM dump, an emulated DesignWare SD controller
(SDMMC0) with an SD card backed by a card image, IMEM, DDR, and logging stubs for GRF/CRU/GPIO.

The ROM dump is not in this repository (it is Rockchip code). Read your own (../../README.md "Method") and give its path
in the environment variable RC2_BOOTROM; it is only read. Without it the Unicorn tests print SKIP and exit 0.
Forbidden regions (eMMC controller, SDIO, NAND controller) are mapped as traps: any access is a test failure.
Any SD command other than the ROM's read-only set, and any command with the DW "write" bit, is a test failure.
"""
import hashlib, os, struct
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_PROT_ALL, \
    UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, \
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR, UC_ARM_REG_CP_REG, UC_CPU_ARM_CORTEX_A9

ROM_SHA = '18dda9330dd3c74901ccc335a38071f073f4d79897602d645eb359ec55b02d88'   # 16 KB, ../../README.md


def rom_path():
    """Path of the BootROM dump from $RC2_BOOTROM, or None (the caller skips)."""
    p = os.environ.get('RC2_BOOTROM')
    return os.path.expanduser(p) if p else None


def skip_without_rom(what):
    """Exit 0 with a SKIP line when no ROM dump is given."""
    if not rom_path():
        print(f'SKIP {what}: no BootROM dump (set RC2_BOOTROM to your 16 KB dump, sha256 {ROM_SHA[:16]}...)')
        print('RESULT SKIP')
        raise SystemExit(0)
    if not os.path.isfile(rom_path()):
        print(f'FAIL {what}: RC2_BOOTROM={rom_path()} is not a file')
        print('RESULT FAIL')
        raise SystemExit(1)
IMEM, SDMMC0, SDIO, EMMC, NANDC = 0x10080000, 0x10214000, 0x10218000, 0x1021c000, 0x10500000
STOP = 0x0dead000                       # return address that ends a ROM call
# commands the ROM's SD path may issue (../../README.md §2). ACMD42/ACMD6 change volatile card state only.
ROM_SD_CMDS = {0, 2, 3, 7, 8, 12, 16, 17, 18, 55, ('A', 41), ('A', 42), ('A', 6)}
READ_CMDS = {12, 17, 18}


class Violation(Exception):
    pass


class Card:
    """SD card backed by an image file; kind 'sdsc' (byte addresses, OCR 0x80FF8000) or 'sdhc' (block addresses)."""

    def __init__(self, path, kind='sdsc', overlay=None, fail_lbas=(), fail_once=()):
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        self.kind = kind
        self.ocr = 0x80FF8000 if kind == 'sdsc' else 0xC0FF8000
        self.overlay = dict(overlay or {})   # lba -> 512 bytes
        self.fail_lbas = set(fail_lbas)
        self.fail_once = set(fail_once)       # transient errors: each of these LBAs fails on its first read only
        self.rca = 0x1234

    def lba_of(self, arg):
        if self.kind == 'sdsc':
            if arg % 512:
                raise Violation(f'unaligned SDSC byte address {arg:#x}')
            return arg // 512
        return arg

    def read(self, lba, n):
        out = bytearray()
        for k in range(n):
            if lba + k in self.overlay:
                out += self.overlay[lba + k]
            else:
                self.f.seek((lba + k) * 512)
                b = self.f.read(512)
                out += b + b'\0' * (512 - len(b))
        return bytes(out)


class DWMMC:
    """Enough of the DesignWare MMC register model for the BootROM: commands complete at once, reads stream from a FIFO."""

    def __init__(self, emu, card):
        self.emu, self.card = emu, card
        self.r = {}
        self.rint = 0
        self.fifo, self.fpos = b'', 0
        self.app = False
        self.acmd41_polls = 0
        self.cmds = []            # (cmd index or ('A', n), arg, raw CMD register value, pc)
        self.reads = []           # (lba, nsec)
        self.accesses = []        # (rw, offset, value) for the trace file
        self.trace = True

    def rd(self, uc, off, size, ud):
        if off >= 0x200:
            if self.fpos + 4 > len(self.fifo):
                raise Violation('FIFO read while empty')
            v = struct.unpack_from('<I', self.fifo, self.fpos)[0]
            self.fpos += 4
            if self.fpos >= len(self.fifo):
                self.rint |= 0x8                  # DTO
            if self.trace and (self.fpos == 4 or self.fpos >= len(self.fifo)):
                self.accesses.append(('R', 0x200, v))
            return v
        if off == 0x44:
            v = self.rint
        elif off == 0x48:                          # STATUS: bit2 FIFO empty, bit9 data busy (never)
            v = 0x4 if self.fpos >= len(self.fifo) else 0
        elif off == 0x2c:
            v = self.r.get(0x2c, 0) & 0x7fffffff
        else:
            v = self.r.get(off, 0)
        if self.trace and off not in (0x44, 0x48):
            self.accesses.append(('R', off, v))
        return v

    def wr(self, uc, off, size, val, ud):
        if self.trace:
            self.accesses.append(('W', off, val))
        if off == 0x44:
            self.rint &= ~val
            return
        if off == 0x00:
            val &= ~0x7                            # resets self-clear
        self.r[off] = val
        if off == 0x2c and val & 0x80000000:
            if val & 0x00200000:                   # update clock registers only
                return
            self.command(val)

    def command(self, val):
        idx, arg = val & 0x3f, self.r.get(0x28, 0)
        pc = self.emu.uc.reg_read(UC_ARM_REG_PC)
        key = ('A', idx) if self.app else idx
        self.app = False
        self.cmds.append((key, arg, val, pc))
        if val & 0x400:
            raise Violation(f'CMD{idx} with the DW write bit, CMD reg {val:#x} at pc {pc:#x}')
        if key not in ROM_SD_CMDS:
            raise Violation(f'unexpected SD command {key} arg {arg:#x} reg {val:#x} at pc {pc:#x}')
        c = self.card
        self.rint |= 0x4                           # command done
        if key == 0:
            self.acmd41_polls = 0
        elif key == 8:
            self.r[0x30] = arg & 0xfff
        elif key == 55:
            self.r[0x30] = 0x120
            self.app = True
        elif key == ('A', 41):
            self.acmd41_polls += 1
            self.r[0x30] = c.ocr if self.acmd41_polls >= 3 else c.ocr & 0x7fffffff
        elif key == 2:
            self.r.update({0x30: 0x00a5fb00, 0x34: 0x29008063, 0x38: 0x55303247, 0x3c: 0x03534453})
        elif key == 3:
            self.r[0x30] = (c.rca << 16) | 0x0500
        elif key in (7, 16, 12, ('A', 42), ('A', 6)):
            self.r[0x30] = 0x900
            if key == 12:
                self.fifo, self.fpos = b'', 0
        elif key in (17, 18):
            if not val & 0x200:
                raise Violation('read command without data_expected')
            n = self.r.get(0x20, 0)
            if self.r.get(0x1c) != 512 or n % 512 or n == 0:
                raise Violation(f'bad BLKSIZ/BYTCNT {self.r.get(0x1c)} {n}')
            if (key == 17) != (n == 512):
                raise Violation(f'CMD{key} with {n} bytes')
            lba, ns = c.lba_of(arg), n // 512
            self.reads.append((lba, ns))
            once = {x for x in c.fail_once if lba <= x < lba + ns}
            c.fail_once -= once
            if once or any(lba <= x < lba + ns for x in c.fail_lbas):
                self.rint |= 0x80                  # data CRC error, no data
                self.fifo, self.fpos = b'', 0
                return
            self.fifo, self.fpos = c.read(lba, ns), 0
            self.r[0x30] = 0x900


class Emu:
    def __init__(self, card, ddr_extra=()):
        rom = open(rom_path(), 'rb').read()
        if hashlib.sha256(rom).hexdigest() != ROM_SHA:
            raise SystemExit(f'BootROM dump sha256 mismatch: these tests need the RK3026 ROM with sha256 {ROM_SHA}')
        self.rom = rom
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM, cpu=UC_CPU_ARM_CORTEX_A9)
        self.uc = uc
        uc.mem_map(0x0, 0x4000, UC_PROT_READ | UC_PROT_EXEC)
        uc.mem_write(0x0, rom)
        uc.mem_map(0x10100000, 0x4000, UC_PROT_READ | UC_PROT_EXEC)
        uc.mem_write(0x10100000, rom)
        uc.mem_map(IMEM, 0x8000)
        uc.mem_map(0x60000000, 0x4000000)          # first 64 MiB of DDR
        uc.mem_map(0x7ff00000, 0x100000)           # waveform window + stage2 log
        for a, n in ddr_extra:
            uc.mem_map(a, n)
        self.mmc = DWMMC(self, card)
        uc.mmio_map(SDMMC0, 0x4000, self.mmc.rd, None, self.mmc.wr, None)
        for base, name in ((EMMC, 'eMMC controller'), (SDIO, 'SDIO controller'), (NANDC, 'NAND controller')):
            uc.mmio_map(base, 0x4000, self._trap_rd(name), None, self._trap_wr(name), None)
        self.periph_writes = []                    # (addr, value, pc)
        self.periph = {}
        for base, n in ((0x20000000, 0x4000), (0x20004000, 0x4000), (0x20008000, 0x2000), (0x2000a000, 0x2000),
                        (0x2007c000, 0x4000), (0x20080000, 0x4000), (0x20084000, 0x4000), (0x20088000, 0x4000),
                        (0x20044000, 0x2000), (0x20068000, 0x4000), (0x20090000, 0x4000)):
            uc.mmio_map(base, n, self._prd(base), None, self._pwr(base), None)
        self.violations = []
        self.stop_reason = None
        self.code_hooks = {}
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)

    # ---- peripherals
    def _trap_rd(self, name):
        def f(uc, off, size, ud):
            self.violations.append(f'{name} read +{off:#x} at pc {uc.reg_read(UC_ARM_REG_PC):#x}')
            uc.emu_stop()
            return 0
        return f

    def _trap_wr(self, name):
        def f(uc, off, size, val, ud):
            self.violations.append(f'{name} write +{off:#x}={val:#x} at pc {uc.reg_read(UC_ARM_REG_PC):#x}')
            uc.emu_stop()
        return f

    def _prd(self, base):
        def f(uc, off, size, ud):
            return self.periph.get(base + off, 0)
        return f

    def _pwr(self, base):
        def f(uc, off, size, val, ud):
            a = base + off
            self.periph_writes.append((a, val, uc.reg_read(UC_ARM_REG_PC)))
            self.periph[a] = val
        return f

    def _unmapped(self, uc, access, addr, size, value, ud):
        self.violations.append(f'unmapped access {access} at {addr:#x} pc {uc.reg_read(UC_ARM_REG_PC):#x}')
        return False

    # ---- control
    def hook_at(self, addr, fn):
        self.code_hooks[addr] = fn
        self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, ud: fn(self), begin=addr, end=addr)

    def stop(self, reason):
        self.stop_reason = reason
        self.uc.emu_stop()

    def ret(self, value=None):
        if value is not None:
            self.uc.reg_write(UC_ARM_REG_R0, value)
        self.uc.reg_write(UC_ARM_REG_PC, self.uc.reg_read(UC_ARM_REG_LR))

    def reg(self, r):
        return self.uc.reg_read(r)

    def sctlr(self):
        return self.uc.reg_read(UC_ARM_REG_CP_REG, (15, 0, 0, 1, 0, 0, 0))

    def call(self, fn, args=(), sp=IMEM + 0x760, count=0):
        uc = self.uc
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            uc.reg_write(r, v)
        uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_LR, STOP)
        self.stop_reason = None
        try:
            uc.emu_start(fn, STOP, count=count)
        except UcError as e:
            self.violations.append(f'UcError {e} at pc {uc.reg_read(UC_ARM_REG_PC):#x}')
        except Violation as e:
            self.violations.append(str(e))
        return uc.reg_read(UC_ARM_REG_R0)

    def run(self, pc, sp, count=0):
        self.stop_reason = None
        self.uc.reg_write(UC_ARM_REG_SP, sp)
        try:
            self.uc.emu_start(pc, STOP, count=count)
        except UcError as e:
            self.violations.append(f'UcError {e} at pc {self.uc.reg_read(UC_ARM_REG_PC):#x}')
        except Violation as e:
            self.violations.append(str(e))

    def rom_state(self, sd_class=0x08, ctl=0):
        """IMEM as the ROM leaves it after an SD boot (delay factor, non-secure, card class, controller id, RCA)."""
        m = self.uc.mem_write
        m(IMEM + 0x00, struct.pack('<I', 24))
        m(IMEM + 0x0c, struct.pack('<I', 0))
        m(IMEM + 0x40, struct.pack('<I', sd_class))
        m(IMEM + 0x44, bytes([ctl]))
        m(IMEM + 0x46, struct.pack('<H', self.mmc.card.rca))


def set_cpsr_svc(uc):
    uc.reg_write(UC_ARM_REG_CPSR, 0x1d3)


__all__ = ['rom_path', 'skip_without_rom', 'ROM_SHA', 'UC_ARM_REG_R4', 'Card', 'DWMMC', 'Emu', 'Violation', 'IMEM', 'STOP', 'READ_CMDS', 'set_cpsr_svc', 'UC_ARM_REG_R0',
           'UC_ARM_REG_R1', 'UC_ARM_REG_R2', 'UC_ARM_REG_R3', 'UC_ARM_REG_PC', 'UC_ARM_REG_CPSR', 'UC_ARM_REG_SP',
           'UC_ARM_REG_LR']
