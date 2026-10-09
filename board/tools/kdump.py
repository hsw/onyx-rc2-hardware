#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Dump words of the stock RC2 kernel Image at a VA (raw ARM Image, VA = file offset + 0xc0408000) with
annotations: kallsyms name, C string, GPIO number (RK3026: 128 + 32*bank + 8*port + pin), iomux code,
section of a pointer (initdata/data/bss), and the string a pointed-to word points at.  Read-only.

usage: python3 -I kdump.py IMAGE KALLSYMS VA|SYM NWORDS
       python3 -I kdump.py IMAGE KALLSYMS --str VA          (print the C string at VA)

IMAGE: raw stock RC2 kernel Image (2017-11-07 build); KALLSYMS: from ../../kernel/extract_kallsyms.py. Uses kdis.py next to it.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdis  # noqa: E402


def main():
    a = sys.argv[1:]
    img = open(a[0], 'rb').read()
    syms = kdis.Syms(a[1])
    if a[2] == '--str':
        print(kdis.cstr(img, int(a[3], 16)))
        return
    va = syms.resolve(a[2])
    n = int(a[3], 0)
    zrun = 0
    for i in range(n):
        p = va + 4 * i
        off = p - kdis.BASE
        if not (0 <= off < len(img) - 3):
            break
        v, = struct.unpack_from('<I', img, off)
        if v == 0 and not syms.name(p, exact=True):
            zrun += 1
            continue
        if zrun:
            print('          ... %d zero word(s)' % zrun)
            zrun = 0
        notes = []
        here = syms.name(p, exact=True)
        if here:
            notes.append('@%s' % here)
        vn = syms.name(v, exact=True)
        if vn:
            notes.append('<%s>' % vn)
        s = kdis.cstr(img, v)
        if s:
            notes.append('"%s"' % s)
        w = kdis.where(v)
        if w and not vn and not s:
            notes.append('[%s]' % w)
            po = v - kdis.BASE
            if 0 <= po < len(img) - 3:
                pv, = struct.unpack_from('<I', img, po)
                ps, pn = kdis.cstr(img, pv), syms.name(pv, exact=True)
                if ps or pn:
                    notes.append('->*%s%s' % (' <%s>' % pn if pn else '', ' "%s"' % ps if ps else ''))
        g = kdis.gpio_name(v)
        if g:
            notes.append('(%s?)' % g)
        io = kdis.iomux_name(v) if v >= 0xa00 else None
        if io:
            notes.append('(%s?)' % io)
        if v and v < 0x10000000 and not g and not io:
            notes.append('%d' % v)
        if v >= 0x80000000 and not vn and not s and not w and v > 0xffff0000:
            notes.append('%d' % (v - (1 << 32)))
        print('%08x: %08x  %s' % (p, v, ' '.join(notes)))
    if zrun:
        print('          ... %d zero word(s)' % zrun)


if __name__ == '__main__':
    main()
