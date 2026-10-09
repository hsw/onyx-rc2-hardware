#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Disassemble a range of the stock RC2 kernel Image (raw ARM, VA = file offset + 0xc0408000) with GNU objdump
and annotate it with kallsyms names: function headers, branch targets, and literal-pool words that point at a
symbol or at a printable string.  The Image is only read, never executed.

usage: python3 -I kdis.py IMAGE KALLSYMS START [STOP]        (START/STOP: hex VA or symbol name;
                                                              no STOP = end of the START symbol)
       python3 -I kdis.py IMAGE KALLSYMS --callers SYM [SYM..]  (BL/B scan of the whole text for callers)

IMAGE is the raw stock RC2 kernel Image (2017-11-07 build, sha256 47a13cf3...30af); KALLSYMS comes from
../../kernel/extract_kallsyms.py. Env: OBJDUMP (GNU objdump, default 'objdump' on PATH).
"""
import bisect
import os
import re
import struct
import subprocess
import sys

BASE = 0xc0408000
OBJDUMP = os.environ.get('OBJDUMP', 'objdump')   # GNU objdump with ARM support


def load_syms(path):
    syms = []
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and not p[0].startswith("#"):
            syms.append((int(p[0], 16), p[1], p[2]))
    syms.sort()
    return syms


class Syms:
    def __init__(self, path):
        self.s = load_syms(path)
        self.addrs = [a for a, _, _ in self.s]
        self.by_name = {}
        for a, t, n in self.s:
            self.by_name.setdefault(n, a)

    def name(self, a, exact=False):
        i = bisect.bisect_right(self.addrs, a) - 1
        if i < 0:
            return None
        sa, _, sn = self.s[i]
        if sa == a:
            return sn
        if exact or a - sa > 0x10000:
            return None
        return '%s+0x%x' % (sn, a - sa)

    def end(self, a):
        i = bisect.bisect_right(self.addrs, a)
        while i < len(self.addrs) and self.addrs[i] == a:
            i += 1
        return self.addrs[i] if i < len(self.addrs) else a + 4

    def resolve(self, x):
        if re.fullmatch(r'(0x)?[0-9a-fA-F]{8}', x):
            return int(x, 16)
        return self.by_name[x]


def cstr(img, va):
    off = va - BASE
    if not (0 <= off < len(img)):
        return None
    e = img.find(b'\0', off, off + 200)
    if e < 0 or e - off < 3:
        return None
    s = img[off:e]
    if all(32 <= c < 127 or c in (9, 10) for c in s):
        return s.decode().replace('\n', '\\n')
    return None


def disasm(img_path, syms, start, stop):
    img = open(img_path, 'rb').read()
    out = subprocess.run([OBJDUMP, '-D', '-b', 'binary', '-m', 'arm', '--adjust-vma=0x%x' % BASE,
                          '--start-address=0x%x' % start, '--stop-address=0x%x' % stop, img_path],
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(.*)', line)
        if not m:
            continue
        a = int(m.group(1), 16)
        word = int(m.group(2), 16)
        ins = m.group(3)
        n = syms.name(a, exact=True)
        if n:
            print('\n%08x <%s>:' % (a, n))
        note = ''
        bm = re.match(r'(b|bl|blx|b[a-z]{2}|bl[a-z]{2})\s+0x([0-9a-f]+)', ins)
        if bm:
            t = int(bm.group(2), 16)
            tn = syms.name(t)
            if tn:
                note = '<%s>' % tn
        lm = re.search(r'\[pc, #(-?\d+)\]', ins)
        if lm and ins.startswith('ldr'):
            la = a + 8 + int(lm.group(1))
            off = la - BASE
            if 0 <= off < len(img) - 3:
                v, = struct.unpack_from('<I', img, off)
                s = cstr(img, v)
                vn = syms.name(v)
                note = '=0x%08x' % v + (' <%s>' % vn if vn else '') + (' "%s"' % s if s else '')
        if not note and (word >> 24) == 0xc0 or (not note and 0xc0400000 <= word < 0xc2000000 and ins.startswith(('stc', 'ldc', 'svc', 'eor', 'and', 'andeq', '.word', 'sbc', 'rsc', 'ldm', 'stm', 'mcr', 'cdp')) ):
            vn = syms.name(word)
            s = cstr(img, word)
            if vn or s:
                note = '[word ->%s%s]' % (' <%s>' % vn if vn else '', ' "%s"' % s if s else '')
        print('%08x: %08x  %-44s %s' % (a, word, ins, note))


def callers(img_path, syms, targets):
    img = open(img_path, 'rb').read()
    want = {syms.resolve(t): t for t in targets}
    text_end = syms.by_name.get('_etext', BASE + len(img))
    hits = {t: [] for t in want}
    for off in range(0, min(len(img), text_end - BASE) - 3, 4):
        w, = struct.unpack_from('<I', img, off)
        if (w >> 25) & 7 != 5:          # B/BL (cond != 0xf) or BLX imm (cond == 0xf)
            continue
        cond = w >> 28
        imm = w & 0xffffff
        if imm & 0x800000:
            imm -= 0x1000000
        a = BASE + off
        t = a + 8 + imm * 4
        if cond == 0xf:
            continue                     # BLX to Thumb: none in this kernel
        if t in want:
            hits[t].append((a, 'bl' if w & (1 << 24) else 'b', cond))
    # literal-pool words (function pointers)
    for off in range(0, len(img) - 3, 4):
        v, = struct.unpack_from('<I', img, off)
        if v in want:
            hits[v].append((BASE + off, 'ptr', None))
    for t, lst in hits.items():
        print('%s 0x%08x:' % (want[t], t))
        for a, k, c in lst:
            print('   %-4s at 0x%08x in %s%s' % (k, a, syms.name(a), '' if c in (None, 14) else ' cond=%x' % c))


def main():
    a = sys.argv[1:]
    syms = Syms(a[1])
    if a[2] == '--callers':
        callers(a[0], syms, a[3:])
        return
    start = syms.resolve(a[2])
    stop = syms.resolve(a[3]) if len(a) > 3 else syms.end(start)
    disasm(a[0], syms, start, stop)


if __name__ == '__main__':
    main()
