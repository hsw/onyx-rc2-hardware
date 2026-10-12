#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the sdboot test ramdisk ("m0", ramdisk-sd.cpio.gz): busybox + optional ebc-console + the waveform + ./init.

No binaries are in this repository; you give them:
  --busybox     a static ARM (armv7, EABI) busybox with sh, mount, setsid, devmem, awk, grep, cat, mv, sleep
  --waveform    ebc_waveform.bin from your stock boot ramdisk (the stock kernel loads it from the initramfs)
  --ebc-console optional: a text console for the panel (/dev/ebc); without it the ramdisk only blinks the LED
Deterministic newc cpio (sorted, uid/gid 0, mtime EPOCH, inode numbers in order) and gzip with mtime 0, so the same inputs
give the same bytes. listing.txt records the sha256 of every file.

usage: mkramdisk-sd.py --out DIR --busybox FILE --waveform FILE [--ebc-console FILE]
"""
import argparse, gzip, hashlib, io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EPOCH = 1791590400
DIRS = ['dev', 'proc', 'sbin', 'sys', 'tmp']


def sha(b):
    return hashlib.sha256(b).hexdigest()


def newc(entries):
    """entries: sorted list of (name, mode, data). Returns the cpio bytes."""
    b = io.BytesIO()

    def rec(ino, name, mode, data):
        nm = name.encode() + b'\0'
        hdr = '070701' + ''.join('%08X' % v for v in (ino, mode, 0, 0, 1 if mode & 0o170000 != 0o040000 else 2,
                                                      EPOCH, len(data), 0, 0, 0, 0, len(nm), 0))
        b.write(hdr.encode() + nm)
        b.write(b'\0' * (-(110 + len(nm)) % 4))
        b.write(data)
        b.write(b'\0' * (-len(data) % 4))
    for i, (name, mode, data) in enumerate(entries, 1):
        rec(i, name, mode, data)
    rec(0, 'TRAILER!!!', 0, b'')
    return b.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True)
    ap.add_argument('--busybox', required=True)
    ap.add_argument('--waveform', required=True)
    ap.add_argument('--ebc-console')
    a = ap.parse_args()
    files = [('init', 0o750, os.path.join(HERE, 'init')), ('sbin/busybox', 0o750, a.busybox),
             ('ebc_waveform.bin', 0o644, a.waveform)]
    if a.ebc_console:
        files.append(('sbin/ebc-console', 0o750, a.ebc_console))
    entries = [(d, 0o040755, b'') for d in DIRS]
    listing = []
    for dest, mode, src in files:
        try:
            data = open(src, 'rb').read()
        except OSError as e:
            sys.exit(f'REFUSE: {dest}: {e}')
        entries.append((dest, 0o100000 | mode, data))
        listing.append(f'{sha(data)}  {mode:o}  {dest}  ({len(data)} B)')
    entries.sort(key=lambda e: e[0])
    cpio = newc(entries)
    gz = gzip.compress(cpio, compresslevel=9, mtime=0)
    os.makedirs(a.out, exist_ok=True)
    p = os.path.join(a.out, 'ramdisk-sd.cpio.gz')
    open(p, 'wb').write(gz)
    with open(os.path.join(a.out, 'listing.txt'), 'w') as f:
        f.write('\n'.join(listing) + '\n' + '\n'.join(f'dir 755 {d}' for d in DIRS) + '\n')
        f.write(f'cpio {len(cpio)} B sha256 {sha(cpio)}\n')
    with open(os.path.join(a.out, 'SHA256SUMS'), 'w') as f:
        f.write(f'{sha(gz)}  ramdisk-sd.cpio.gz\n')
    print(f'{p}: {len(gz)} B sha256 {sha(gz)} (cpio {len(cpio)} B, {len(entries)} entries)')


if __name__ == '__main__':
    main()
