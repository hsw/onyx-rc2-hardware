#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""List sysfs attributes (struct device_attribute / kobj_attribute) compiled into the stock RC2 kernel Image.

Usage: python3 -I sysfs_attrs.py <Image> <kallsyms.txt> [name-regex] [--refs]

The Image is the uncompressed stock RC2 ARM kernel (2017-11-07 build, sha256 47a13cf3...30af, not public), VA = file offset
+ 0xC0408000; the kallsyms list comes from extract_kallsyms.py.
A device_attribute on this 3.0 kernel without lockdep is 4 words: {const char *name; umode_t mode (+pad); show; store}.
A candidate is kept when name points at a printable C string, mode is a plausible permission (no type bits), and show/store
are 0 or exactly a kallsyms text symbol, with at least one of them set. --refs also prints the strings and symbols that
the literal pools of show/store point at (what the handler prints, parses or calls), which is how the formats in
sysfs-attributes.md were read; confirm control flow with objdump (see that file).
"""
import bisect
import re
import struct
import sys

BASE = 0xC0408000


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    refs = '--refs' in sys.argv
    image, kallsyms = args[0], args[1]
    pattern = re.compile(args[2]) if len(args) > 2 else None
    d = open(image, 'rb').read()
    sym = {}
    for line in open(kallsyms):
        p = line.split()
        if line.startswith('#') or len(p) < 3 or p[1] not in 'tT':
            continue
        try:
            sym[int(p[0], 16)] = p[2]
        except ValueError:
            pass
    addrs = sorted(sym)
    end = BASE + len(d)

    def cstr(va, n=64):
        o = va - BASE
        if not 0 <= o < len(d):
            return None
        t = d[o:o + n].split(b'\0')[0]
        if len(t) < 2 or not all(32 <= c < 127 or c in (9, 10) for c in t):
            return None
        return t.decode()

    def literal_refs(fn):
        i = bisect.bisect_right(addrs, fn)
        stop = addrs[i] if i < len(addrs) else fn + 4
        out = []
        for x in range(fn, stop, 4):
            w = struct.unpack_from('<I', d, x - BASE)[0]
            if BASE <= w < end:
                if w in sym:
                    out.append('&' + sym[w])
                else:
                    t = cstr(w)
                    if t is not None:
                        out.append(repr(t))
        return out

    for o in range(0, len(d) - 16, 4):
        name, mode, show, store = struct.unpack_from('<4I', d, o)
        if not (BASE <= name < end) or not (0 < mode <= 0o777):
            continue
        if not (show or store) or (show and show not in sym) or (store and store not in sym):
            continue
        n = cstr(name, 48)
        if n is None or (pattern and not pattern.search(n)):
            continue
        print('%08x  %-24s %04o  show=%-28s store=%s' % (BASE + o, n, mode, sym.get(show, '-'), sym.get(store, '-')))
        if refs:
            for label, fn in (('show', show), ('store', store)):
                if fn:
                    print('    %s refs: %s' % (label, ', '.join(literal_refs(fn)) or '-'))


if __name__ == '__main__':
    main()
