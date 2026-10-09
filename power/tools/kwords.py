#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Dump 32-bit words of the stock RC2 kernel Image at VAs, resolving pointers to printable strings.
usage: python3 -I kwords.py IMAGE VA:COUNT [VA:COUNT ...]   (VA in hex, COUNT in words)
IMAGE: raw stock RC2 kernel Image (2017-11-07 build); addresses refer to that kernel."""
import struct
import sys

BASE = 0xc0408000


def cstr(img, v):
    o = v - BASE
    if not 0 <= o < len(img):
        return None
    e = img.find(b'\0', o, o + 200)
    s = img[o:e] if e > o else b''
    return s.decode() if s and all(32 <= c < 127 for c in s) else None


def main():
    img = open(sys.argv[1], 'rb').read()
    for spec in sys.argv[2:]:
        va, n = spec.split(':')
        va = int(va, 16)
        print('# %08x x %s' % (va, n))
        for i in range(int(n)):
            v, = struct.unpack_from('<I', img, va + 4 * i - BASE)
            s = cstr(img, v)
            print('%08x: %08x %s' % (va + 4 * i, v, '"%s"' % s if s else ''))


if __name__ == '__main__':
    main()
