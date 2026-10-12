#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""MBR guard for write-card.sh --boot-area / --rootfs: the card's partition table must already be the image's.

A partial write rewrites sector 0 (the MBR) but leaves the rest of the card as it is. On a card with another layout (e.g. an
old single-partition card under a two-partition image) that would leave a partition entry pointing at stale data. Only the
full write may change the layout.

usage: mbrguard.py CARD_HEAD IMAGE [TABLE_HEX]
  CARD_HEAD  file with at least the first 512 bytes read from the card (write-card.sh reads one 32 KiB block)
  IMAGE      sdcard.img (its first 512 bytes)
  TABLE_HEX  manifest.json mbr.table_hex (bytes 446..509 of the image), checked against IMAGE when given
exit 0: bytes 446..511 (four entries + 55 AA) are equal; 1: they differ (REFUSE); 2: unreadable input or bad manifest.
"""
import struct, sys


def head(path):
    with open(path, 'rb') as f:
        b = f.read(512)
    if len(b) != 512:
        raise ValueError(f'{path}: only {len(b)} bytes')
    return b


def describe(b):
    rows = []
    for i in range(4):
        e = b[446 + 16 * i:462 + 16 * i]
        lba, n = struct.unpack_from('<II', e, 8)
        if e[4] or lba or n:
            rows.append(f'p{i + 1} type 0x{e[4]:02x} LBA {lba} sectors {n}')
    sig = 'signature 55aa' if b[510:512] == b'\x55\xaa' else f'NO 55aa signature ({b[510:512].hex()})'
    return '; '.join(rows + [sig]) if rows else f'no partitions; {sig}'


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        card, img = head(argv[1]), head(argv[2])
    except (OSError, ValueError) as e:
        print(f'REFUSE: {e}')
        return 2
    if len(argv) == 4 and img[446:510].hex() != argv[3].strip().lower():
        print('REFUSE: the image MBR table differs from manifest.json mbr.table_hex')
        return 2
    print(f'card  MBR: {describe(card)}')
    print(f'image MBR: {describe(img)}')
    if card[446:512] != img[446:512]:
        print('REFUSE: the card has another partition table; a partial write would leave it inconsistent. '
              'Write the whole image (no mode option) to change the layout.')
        return 1
    print('MBR guard OK: same partition table')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
