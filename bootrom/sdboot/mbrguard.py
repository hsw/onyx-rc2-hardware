#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""MBR helpers for write-card.sh: the partition-table guard for partial writes and the p2 length set at write time.

A partial write rewrites sector 0 (the MBR) but leaves the rest of the card as it is. On a card with another layout (e.g. an
old single-partition card under a two-partition image) that would leave a partition entry pointing at stale data. Only the
full write may change the layout.

Data layout (mkcard.py --data-partition without --data-img): the image ends with partition 1 and its MBR entry 2 (p2, FAT32
RC2DATA, LBA 655360) carries a placeholder length. write-card.sh sets that length from the card (whole write: the disk size,
rounded down to 32 KiB; partial writes: the length already on the card) in a patched copy of the image's first 32 KiB block;
only the 4-byte sector count of entry 2 (MBR bytes 474..477) differs from the image.

usage:
  mbrguard.py CARD_HEAD IMAGE [TABLE_HEX] [--p2-any-length]
      exit 0: bytes 446..511 (four entries + 55 AA) are equal (with --p2-any-length: entry 2 is compared without its
      sector count, which must be non-zero); 1: they differ (REFUSE); 2: unreadable input or bad manifest
  mbrguard.py p2-for-disk DISK_BYTES        print the p2 sector count for a disk of that size (exit 1: too small)
  mbrguard.py card-p2 CARD_HEAD             print the sector count of the card's entry 2
  mbrguard.py patch IMAGE OUT P2_SECTORS    OUT = the image's first 32 KiB with entry 2's sector count set
  mbrguard.py sha IMAGE HEAD NBYTES         sha256 of HEAD (32 KiB) followed by IMAGE[32768:NBYTES]
  mbrguard.py written CARD_HEAD IMAGE P2_SECTORS
      exit 0: the card's sector 0 equals the image's except entry 2's sector count, which equals P2_SECTORS
  CARD_HEAD  file with at least the first 512 bytes read from the card (write-card.sh reads one 32 KiB block)
  IMAGE      sdcard.img
  TABLE_HEX  manifest.json mbr.table_hex (bytes 446..509 of the image), checked against IMAGE when given
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fat32  # noqa: E402

BLOCK = 32768
P2_LBA = 655360                     # mkcard.P2_LBA (the data layout's p2 start, 320 MiB)
P2_ENTRY = 446 + 16                 # MBR entry 2
P2_COUNT = slice(P2_ENTRY + 12, P2_ENTRY + 16)


def head(path, n=512):
    with open(path, 'rb') as f:
        b = f.read(n)
    if len(b) != n:
        raise ValueError(f'{path}: only {len(b)} bytes')
    return b


def entry(b, i):
    e = b[446 + 16 * i:462 + 16 * i]
    return e[4], *struct.unpack_from('<II', e, 8)


def describe(b):
    rows = []
    for i in range(4):
        t, lba, n = entry(b, i)
        if t or lba or n:
            rows.append(f'p{i + 1} type 0x{t:02x} LBA {lba} sectors {n}')
    sig = 'signature 55aa' if b[510:512] == b'\x55\xaa' else f'NO 55aa signature ({b[510:512].hex()})'
    return '; '.join(rows + [sig]) if rows else f'no partitions; {sig}'


def is_data_layout(b):
    t, lba, _ = entry(b, 1)
    return t == 0x0C and lba == P2_LBA


def p2_for_disk(disk_bytes):
    """p2 sector count for a disk: from LBA 655360 to the disk end rounded down to 32 KiB."""
    end = disk_bytes // BLOCK * BLOCK // 512
    n = end - P2_LBA
    if n < fat32.MIN_SECTORS:
        raise ValueError(f'disk of {disk_bytes} B leaves {max(n, 0)} sectors for p2; FAT32 needs {fat32.MIN_SECTORS}')
    if end > 0xFFFFFFFF:
        raise ValueError(f'disk of {disk_bytes} B is beyond the MBR limit')
    return n


def patched(img_head, p2):
    if not is_data_layout(img_head):
        raise ValueError('the image has no data-layout entry 2 (type 0x0c at LBA 655360)')
    b = bytearray(img_head)
    struct.pack_into('<I', b, P2_COUNT.start, p2)
    return bytes(b)


def compare(argv):
    any_len = '--p2-any-length' in argv
    argv = [a for a in argv if a != '--p2-any-length']
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        card, img = head(argv[0]), head(argv[1])
    except (OSError, ValueError) as e:
        print(f'REFUSE: {e}')
        return 2
    if len(argv) == 3 and img[446:510].hex() != argv[2].strip().lower():
        print('REFUSE: the image MBR table differs from manifest.json mbr.table_hex')
        return 2
    print(f'card  MBR: {describe(card)}')
    print(f'image MBR: {describe(img)}')
    if any_len:
        if not is_data_layout(img):
            print('REFUSE: --p2-any-length needs a data-layout image')
            return 2
        mask = lambda b: b[446:P2_COUNT.start] + b[P2_COUNT.stop:512]  # noqa: E731
        same = mask(card) == mask(img) and entry(card, 1)[2] > 0
    else:
        same = card[446:512] == img[446:512]
    if not same:
        print('REFUSE: the card has another partition table; a partial write would leave it inconsistent. '
              'Write the whole image (no mode option) to change the layout.')
        return 1
    print('MBR guard OK: same partition table' + (f' (p2 length on the card: {entry(card, 1)[2]} sectors)' if any_len else ''))
    return 0


def main(argv):
    cmd, args = (argv[1], argv[2:]) if len(argv) > 1 else ('', [])
    try:
        if cmd == 'p2-for-disk' and len(args) == 1:
            print(p2_for_disk(int(args[0])))
        elif cmd == 'card-p2' and len(args) == 1:
            print(entry(head(args[0]), 1)[2])
        elif cmd == 'patch' and len(args) == 3:
            with open(args[0], 'rb') as f:
                b = f.read(BLOCK)
            if len(b) != BLOCK:
                raise ValueError(f'{args[0]}: shorter than {BLOCK} bytes')
            with open(args[1], 'wb') as f:
                f.write(patched(b, int(args[2])))
        elif cmd == 'sha' and len(args) == 3:
            n = int(args[2])
            h = hashlib.sha256(head(args[1], BLOCK))
            with open(args[0], 'rb') as f:
                f.seek(BLOCK)
                left = n - BLOCK
                while left > 0:
                    b = f.read(min(left, 1 << 22))
                    if not b:
                        raise ValueError(f'{args[0]}: shorter than {n} bytes')
                    h.update(b)
                    left -= len(b)
            print(h.hexdigest())
        elif cmd == 'written' and len(args) == 3:
            card, img, p2 = head(args[0]), head(args[1]), int(args[2])
            want = patched(img, p2)
            diff = [i for i in range(512) if card[i] != img[i]]
            print(f'card MBR: {describe(card)}')
            if card != want or any(i not in range(P2_COUNT.start, P2_COUNT.stop) for i in diff):
                print(f'REFUSE: card sector 0 is not the image with p2 = {p2} sectors (differs at bytes {diff[:8]})')
                return 1
            print(f'MBR readback OK: sector 0 = image, only the p2 sector count (bytes 474..477) set to {p2}')
        elif cmd and not cmd.startswith('-') and not os.path.exists(cmd):
            print(__doc__, file=sys.stderr)
            return 2
        else:
            return compare(argv[1:])
    except (OSError, ValueError) as e:
        print(f'REFUSE: {e}')
        return 1 if cmd == 'p2-for-disk' else 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
