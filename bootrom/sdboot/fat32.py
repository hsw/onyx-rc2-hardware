#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic FAT32 writer for the sdboot data partition (p2, label RC2DATA). Stdlib only, no mkfs tool: the same
bytes on macOS and Linux.

Geometry (512-byte sectors, 4 KiB clusters, two FATs; README.md "Card layout"):
  sector 0          boot sector (BPB + FAT32 EBR), backup at sector 6
  sector 1          FSInfo, backup at sector 7
  sector R          FAT 1, then FAT 2; R and the FAT size are multiples of 8 sectors (4 KiB) and the data region
                    starts at sector 8192 (4 MiB) of the partition
  data, cluster 2   root directory: only the volume-label entry RC2DATA
Fixed: volume serial 0x52433244 ("RC2D" read as big-endian bytes, stored little endian), label RC2DATA, OEM name MSWIN4.1,
timestamps 2026-10-10 00:00:00.

usage: fat32.py OUT [--sectors N] [--hidden N]   writes an empty data-partition image (sparse file of N sectors; default the
       2 GB card's p2 as mkcard.py places it: 3 207 168 sectors at LBA 655 360). mkdata.sh fills such an image with mtools.
"""
import argparse, os, struct, sys

SECTOR = 512
SPC = 8                                   # sectors per cluster: 4 KiB
RESERVED_MIN = 32
DATA_ALIGN = 8192                         # data region at 4 MiB from the partition start
NFATS = 2
LABEL = 'RC2DATA'
SERIAL = 0x52433244                       # bytes 44 32 43 52 on disk; "RC2D" as a big-endian number
OEM = b'MSWIN4.1'
MEDIA = 0xF8
FAT_DATE = ((2026 - 1980) << 9) | (10 << 5) | 10   # 2026-10-10
FAT_TIME = 0                              # 00:00:00
EOC = 0x0FFFFFFF


def geometry(total):
    """Reserved sectors, FAT size, data start, cluster count for a partition of `total` sectors."""
    data = DATA_ALIGN
    while data < total:
        clusters = (total - data) // SPC
        fat = -(-(clusters + 2) * 4 // SECTOR)
        fat = -(-fat // 8) * 8                       # FAT size in whole 4 KiB pages
        reserved = data - NFATS * fat
        if reserved >= RESERVED_MIN:
            assert reserved % 8 == 0 and clusters > 65525, (reserved, clusters)
            return dict(reserved=reserved, fat_sectors=fat, data_start=data, clusters=clusters)
        data += DATA_ALIGN
    raise ValueError(f'partition of {total} sectors too small for FAT32')


def label11(s):
    b = s.encode('ascii')
    assert len(b) <= 11 and b == b.upper()
    return b.ljust(11, b' ')


def boot_sector(total, hidden, g):
    b = bytearray(SECTOR)
    b[0:3] = b'\xeb\x58\x90'
    b[3:11] = OEM
    struct.pack_into('<HBHBHHBHHHII', b, 11, SECTOR, SPC, g['reserved'], NFATS, 0, 0, MEDIA, 0, 63, 255, hidden, total)
    struct.pack_into('<IHHIHH', b, 36, g['fat_sectors'], 0, 0, 2, 1, 6)   # FATSz32, ExtFlags, FSVer, RootClus, FSInfo, BkBoot
    struct.pack_into('<BBBI', b, 64, 0x80, 0, 0x29, SERIAL)
    b[71:82] = label11(LABEL)
    b[82:90] = b'FAT32   '
    b[90:94] = b'\xcd\x18\xeb\xfe'                  # not bootable: int 18h, then spin
    b[510:512] = b'\x55\xaa'
    return bytes(b)


def fsinfo(g):
    b = bytearray(SECTOR)
    struct.pack_into('<I', b, 0, 0x41615252)
    struct.pack_into('<III', b, 484, 0x61417272, g['clusters'] - 1, 3)   # free count (root dir uses cluster 2), next free
    struct.pack_into('<I', b, 508, 0xAA550000)
    return bytes(b)


def label_entry():
    e = bytearray(32)
    e[0:11] = label11(LABEL)
    e[11] = 0x08                                     # ATTR_VOLUME_ID
    struct.pack_into('<BHHHHHHHI', e, 13, 0, FAT_TIME, FAT_DATE, FAT_DATE, 0, FAT_TIME, FAT_DATE, 0, 0)
    return bytes(e)


def build(total, hidden):
    """[(byte offset in the partition, bytes)] of every non-zero piece, and the geometry. All else is zero."""
    g = geometry(total)
    bs, fi = boot_sector(total, hidden, g), fsinfo(g)
    fat0 = struct.pack('<III', 0x0FFFFF00 | MEDIA, EOC, EOC)      # media marker, clean/no-error, root dir end of chain
    chunks = [(0, bs), (SECTOR, fi), (6 * SECTOR, bs), (7 * SECTOR, fi)]
    chunks += [((g['reserved'] + k * g['fat_sectors']) * SECTOR, fat0) for k in range(NFATS)]
    chunks.append((g['data_start'] * SECTOR, label_entry()))
    info = dict(g, total_sectors=total, hidden_sectors=hidden, cluster_bytes=SPC * SECTOR, label=LABEL,
                serial=f'0x{SERIAL:08x}', oem=OEM.decode(), timestamp='2026-10-10 00:00:00')
    return chunks, info


def write_into(f, base, chunks):
    for off, data in chunks:
        f.seek(base + off)
        f.write(data)


def check_boot_sector(b, total):
    """Problems with a prebuilt data image's boot sector (empty list = a FAT32 volume RC2DATA that fits `total`)."""
    bad = []
    if len(b) < SECTOR or b[510:512] != b'\x55\xaa':
        return ['no 55 AA boot signature']
    bps, spc, rsvd, nfats, rootent, tot16, _media, fat16 = struct.unpack_from('<HBHBHHBH', b, 11)
    tot32, fat32 = struct.unpack_from('<II', b, 32)
    root_clus = struct.unpack_from('<I', b, 44)[0]
    if b[0] not in (0xEB, 0xE9):
        bad.append(f'jump byte 0x{b[0]:02x}')
    if bps != SECTOR:
        bad.append(f'bytes per sector {bps}')
    if spc == 0 or spc & (spc - 1):
        bad.append(f'sectors per cluster {spc}')
    if rootent or tot16 or fat16 or not fat32 or not nfats or not rsvd:
        bad.append(f'not a FAT32 BPB (root entries {rootent}, TotSec16 {tot16}, FATSz16 {fat16}, FATSz32 {fat32}, '
                   f'FATs {nfats}, reserved {rsvd})')
    if not 0 < tot32 <= total:
        bad.append(f'TotSec32 {tot32} not in 1..{total}')
    if b[82:90] != b'FAT32   ':
        bad.append(f'FilSysType {b[82:90]!r}')
    if b[66] != 0x29:
        bad.append(f'extended boot signature 0x{b[66]:02x}')
    if b[71:82] != label11(LABEL):
        bad.append(f'volume label {b[71:82]!r} != {LABEL!r}')
    if not bad:
        clusters = (tot32 - rsvd - nfats * fat32) // spc if spc else 0
        if clusters <= 65525:
            bad.append(f'{clusters} clusters: FAT16 by the cluster-count rule')
        elif fat32 * bps // 4 < clusters + 2:
            bad.append(f'FAT of {fat32} sectors too small for {clusters} clusters')
        if root_clus < 2:
            bad.append(f'root cluster {root_clus}')
    return bad


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mkcard   # the card layout (P2_LBA, P2_SECTORS) lives there
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--sectors', type=int, default=mkcard.P2_SECTORS)
    ap.add_argument('--hidden', type=int, default=mkcard.P2_LBA, help='BPB hidden sectors = partition start LBA')
    a = ap.parse_args()
    chunks, info = build(a.sectors, a.hidden)
    with open(a.out, 'wb') as f:
        f.truncate(a.sectors * SECTOR)
        write_into(f, 0, chunks)
    print(f"{a.out}: FAT32 {LABEL} serial {info['serial']}, {a.sectors} sectors, {info['clusters']} clusters of 4 KiB, "
          f"reserved {info['reserved']}, FAT {info['fat_sectors']} x2, data at sector {info['data_start']}")


if __name__ == '__main__':
    sys.exit(main())
