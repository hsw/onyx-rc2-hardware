#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""write-card.sh helper: format the data partition (p2, FAT32 RC2DATA) on the card with macOS newfs_msdos. macOS only.

usage: formatdata.py DISK [--dry-run]
  DISK       whole-disk id (disk7). The card's MBR (read from /dev/rDISK) must have entry 2 = type 0x0c at LBA 655360;
             its sector count is the partition size. diskutil must show DISKs2 on DISK, not internal, of that size.
  --dry-run  print the newfs_msdos command and stop
Geometry (fat32.format_geometry): the largest cluster of 32/16/8/4 KiB that keeps FAT32 (> 65525 clusters; the 2 GB card
gets 16 KiB), reserved sectors and both FATs in whole 32 KiB units, data region at a 4 MiB multiple, hidden sectors = 655360,
two FATs, FSInfo 1, backup boot sector 6, media F8, volume id 0x52433244, label RC2DATA. After newfs_msdos the boot sector is
read back and checked against that geometry. write-card.sh runs fsck_msdos -n afterwards.
Exit 0: formatted and checked; 1: refused or the check failed.
"""
import os, plistlib, re, struct, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fat32  # noqa: E402
import mbrguard  # noqa: E402


def info(dev):
    r = subprocess.run(['diskutil', 'info', '-plist', dev], capture_output=True)
    if r.returncode != 0:
        raise ValueError(f'diskutil does not know {dev}')
    return plistlib.loads(r.stdout)


def read_sector(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        b = os.read(fd, 512)
    finally:
        os.close(fd)
    if len(b) != 512:
        raise ValueError(f'{path}: short read')
    return b


def newfs_args(dev, total, hidden, g):
    return ['newfs_msdos', '-F', '32', '-S', '512', '-c', str(g['spc']), '-n', str(fat32.NFATS), '-r', str(g['reserved']),
            '-a', str(g['fat_sectors']), '-o', str(hidden), '-s', str(total), '-m', '0xf8', '-O', 'MSWIN4.1',
            '-I', f'0x{fat32.SERIAL:08x}', '-i', '1', '-k', '6', '-u', '63', '-h', '255', '-v', fat32.LABEL, dev]


def main(argv):
    args = [a for a in argv[1:] if a != '--dry-run']
    dry = len(args) != len(argv) - 1
    if len(args) != 1 or not re.match(r'^disk[0-9]+$', args[0]):
        print(__doc__)
        return 1
    disk = args[0]
    part, raw = f'{disk}s2', f'/dev/r{disk}s2'
    try:
        mbr = read_sector(f'/dev/r{disk}')
        t, lba, total = mbrguard.entry(mbr, 1)
        if (t, lba) != (0x0C, mbrguard.P2_LBA) or mbr[510:512] != b'\x55\xaa':
            raise ValueError(f'card MBR entry 2 is type 0x{t:02x} at LBA {lba}, not the data partition (0x0c at '
                             f'{mbrguard.P2_LBA}): {mbrguard.describe(mbr)}')
        d = info(disk)
        if d.get('Internal') is not False or not d.get('WholeDisk'):
            raise ValueError(f'{disk} is internal or not a whole disk')
        # macOS rereads the partition table after the MBR write and may automount an old FAT left in p2: wait up to
        # 10 s for DISKs2 of the MBR's size and unmount it once
        for i in range(10):
            p = info(part) if subprocess.run(['diskutil', 'info', part], capture_output=True).returncode == 0 else {}
            if p.get('MountPoint') and i < 9:
                subprocess.run(['diskutil', 'unmount', part], capture_output=True)
            elif p.get('ParentWholeDisk') == disk and p.get('TotalSize') == total * 512 and not p.get('MountPoint'):
                break
            time.sleep(1)
        if p.get('ParentWholeDisk') != disk or p.get('TotalSize') != total * 512:
            raise ValueError(f"{part}: parent {p.get('ParentWholeDisk')}, {p.get('TotalSize')} B; the MBR says "
                             f'{total * 512} B on {disk}')
        if p.get('MountPoint'):
            raise ValueError(f"{part} is mounted at {p['MountPoint']}")
        g = fat32.format_geometry(total)
    except (OSError, ValueError) as e:
        print(f'REFUSE: {e}')
        return 1
    cmd = newfs_args(raw, total, lba, g)
    print(f"p2 {raw}: {total} sectors at LBA {lba}, {g['spc'] * 512 // 1024} KiB clusters x {g['clusters']}, reserved "
          f"{g['reserved']}, FAT {g['fat_sectors']} x2, data at sector {g['data_start']}")
    print('$ ' + ' '.join(cmd))
    if dry:
        return 0
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f'FAIL: newfs_msdos exit {r.returncode}')
        return 1
    bad = fat32.check_format(read_sector(raw), total, lba, g)
    if bad:
        print('FAIL: boot sector after newfs_msdos: ' + '; '.join(bad))
        return 1
    serial = struct.unpack_from('<I', read_sector(raw), 67)[0]
    print(f'formatted: FAT32 {fat32.LABEL} serial 0x{serial:08x}, boot sector checked (32 KiB aligned)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
