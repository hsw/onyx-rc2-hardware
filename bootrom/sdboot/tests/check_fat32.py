#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the FAT32 data partition (p2) of an sdboot card: an independent reader, it does not import fat32.py.

usage: check_fat32.py IMAGE [--offset BYTES] [--sectors N] [--hidden N] [--empty]
  IMAGE     p2 image, or sdcard.img with --offset 335544320
  --empty   also require an empty volume: FAT entries 3.. zero, root dir = only the label entry, data region all zero
Prints PASS/FAIL lines; exit 1 on any FAIL.
"""
import argparse, struct, sys

LABEL = b'RC2DATA    '
SERIAL = 0x52433244
fails = 0


def check(ok, what):
    global fails
    print(('PASS ' if ok else 'FAIL ') + what)
    if not ok:
        fails += 1
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--sectors', type=int, default=3207168)   # the spec numbers, on purpose not imported
    ap.add_argument('--hidden', type=int, default=655360)
    ap.add_argument('--empty', action='store_true')
    a = ap.parse_args()
    f = open(a.image, 'rb')

    def rd(sector, n=1):
        f.seek(a.offset + sector * 512)
        return f.read(512 * n)

    bs = rd(0)
    (bps, spc, rsvd, nfats, rootent, tot16, media, fat16, spt, heads, hidden, tot32, fatsz, extflags, fsver, rootclus,
     fsinfo_sec, bk) = struct.unpack_from('<HBHBHHBHHHIIIHHIHH', bs, 11)
    drv, _res, sig, serial = struct.unpack_from('<BBBI', bs, 64)
    check(bs[0] == 0xEB and bs[2] == 0x90 and bs[510:512] == b'\x55\xaa', 'boot sector: jump EB xx 90, signature 55 AA')
    check((bps, spc, nfats, media) == (512, 8, 2, 0xF8), f'512 B sectors, 8 sectors/cluster, 2 FATs, media F8: '
          f'{bps} {spc} {nfats} 0x{media:02x}')
    check((rootent, tot16, fat16) == (0, 0, 0) and fatsz > 0, 'FAT32 BPB: RootEntCnt, TotSec16, FATSz16 zero; FATSz32 set')
    check(tot32 == a.sectors and hidden == a.hidden, f'TotSec32 {tot32} == {a.sectors}, HiddSec {hidden} == {a.hidden}')
    check((extflags, fsver, rootclus, fsinfo_sec, bk) == (0, 0, 2, 1, 6),
          f'ExtFlags 0 (mirrored FATs), FSVer 0, root cluster 2, FSInfo 1, backup boot 6: '
          f'{extflags} {fsver} {rootclus} {fsinfo_sec} {bk}')
    check(bs[52:64] == bytes(12) and bs[65] == 0, 'reserved BPB bytes zero, clean (no dirty flag)')
    check(drv == 0x80 and sig == 0x29 and serial == SERIAL, f'drive 0x80, boot sig 0x29, serial 0x{serial:08x}')
    check(bs[71:82] == LABEL and bs[82:90] == b'FAT32   ', f'BPB label {bs[71:82]!r}, type {bs[82:90]!r}')
    data_start = rsvd + nfats * fatsz
    clusters = (tot32 - data_start) // spc
    check(clusters > 65525, f'{clusters} clusters > 65525 (FAT32 by count)')
    check(fatsz * 512 // 4 >= clusters + 2, f'FAT of {fatsz} sectors holds {clusters} + 2 entries')
    check(data_start % 8192 == 0 and rsvd % 8 == 0 and fatsz % 8 == 0 and rsvd >= 9,
          f'data region at sector {data_start} (4 MiB aligned), reserved {rsvd} and FAT {fatsz} in 4 KiB units')
    check(rd(6) == bs, 'backup boot sector at 6 == sector 0')
    fi = rd(1)
    lead, struc, free, nxt, trail = (struct.unpack_from('<I', fi, 0)[0], *struct.unpack_from('<III', fi, 484),
                                     struct.unpack_from('<I', fi, 508)[0])
    check((lead, struc, trail) == (0x41615252, 0x61417272, 0xAA550000), 'FSInfo signatures')
    fi7 = rd(7)
    if a.empty:   # writers (mtools, the Linux driver) update only the primary FSInfo later
        check(fi7 == fi, 'backup FSInfo at 7 == sector 1')
    else:
        check(fi7[0:4] == fi[0:4] and fi7[484:488] == fi[484:488] and fi7[508:] == fi[508:], 'backup FSInfo signatures')
    fat1, fat2 = rd(rsvd, fatsz), rd(rsvd + fatsz, fatsz)
    check(fat1 == fat2, 'FAT 1 == FAT 2')
    e = struct.unpack_from(f'<{clusters + 2}I', fat1, 0)
    check(e[0] == 0x0FFFFFF8 and e[1] & 0x0FFFFFFF == 0x0FFFFFFF, f'FAT[0] 0x{e[0]:08x} (media), FAT[1] 0x{e[1]:08x}'
          ' (clean, no error)')
    check(e[2] & 0x0FFFFFFF >= 0x0FFFFFF8, f'FAT[2] 0x{e[2]:08x}: root directory ends in cluster 2')
    nfree = sum(1 for x in e[2:] if x & 0x0FFFFFFF == 0)
    check(free in (nfree, 0xFFFFFFFF), f'FSInfo free count {free} (FAT says {nfree})')
    check(nxt == 0xFFFFFFFF or 2 <= nxt < clusters + 2, f'FSInfo next free {nxt}')
    root = rd(data_start, spc)
    lab = root[0:32]
    check(lab[0:11] == LABEL and lab[11] == 0x08 and struct.unpack_from('<HH', lab, 20) == (0, 0)
          and struct.unpack_from('<HH', lab, 26) == (0, 0), 'root dir entry 0: volume label RC2DATA, attr 0x08, no cluster')
    if a.empty:
        check(all(x == 0 for x in e[3:]) and fat1[(clusters + 2) * 4:] == bytes(len(fat1) - (clusters + 2) * 4),
              'empty: FAT entries 3.. and the FAT tail are zero')
        check(lab[13:26] == struct.pack('<BHHHHHH', 0, 0, 0x5D4A, 0x5D4A, 0, 0, 0x5D4A),
              'empty: label entry timestamps 2026-10-10 00:00:00')
        check(root[32:] == bytes(len(root) - 32), 'empty: nothing else in the root directory')
        others = [s for s in list(range(2, 6)) + list(range(8, rsvd)) if rd(s) != bytes(512)]
        check(not others, f'empty: reserved sectors other than 0, 1, 6, 7 zero {others[:4]}')
        f.seek(a.offset + (data_start + spc) * 512)
        left, nz = (tot32 - data_start - spc) * 512, 0
        while left and not nz:
            b = f.read(min(left, 1 << 22))
            if not b:
                break
            nz = b.count(0) != len(b)
            left -= len(b)
        check(not nz and left == 0, 'empty: data region after the root cluster is zero')
    print(f'{fails} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
