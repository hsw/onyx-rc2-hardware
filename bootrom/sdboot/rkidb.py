# SPDX-License-Identifier: MIT
"""RK3026 IDBlock helpers for sdboot (imported by mkcard.py and the tests).

The ROM (../README.md §3) reads the header sector at card LBA 64, checks the RC4'd magic, then loads init_size sectors
from base + init_offset into SRAM 0x10080800 (must start "RK30", must return 0) and the remaining
init_boot_size - init_size sectors in 2 KB chunks to DDR 0x60000000, and jumps there. Every IDB sector on media is RC4'd
from a fresh state with the standard Rockchip IDBlock key.

The key is not in this repository. Give it as 32 hex digits with set_key() (mkcard.py --rc4-key, or the environment
variable RK_RC4_KEY). It is the key Rockchip's own tools use; public copies are in U-Boot (tools/rkcommon.c, rc4_key) and
rkdeveloptool. A wrong key is caught: the stock header then does not decrypt to the magic 0x0FF0AA55.
"""
import os, struct

_KEY = None
IDB_MAGIC = 0x0FF0AA55
STOCK_SECTOR = 528            # rkflashtool IDB dumps use 528-byte sectors (512 data)


def set_key(hexkey=None):
    """Set the RC4 key from 32 hex digits (default: the environment variable RK_RC4_KEY)."""
    global _KEY
    h = (hexkey or os.environ.get('RK_RC4_KEY') or '').replace(' ', '').replace(',', '')
    try:
        k = bytes.fromhex(h)
    except ValueError:
        k = b''
    if len(k) != 16:
        raise SystemExit('REFUSE: the Rockchip IDBlock RC4 key is needed as 32 hex digits (--rc4-key or RK_RC4_KEY); '
                         'see the README')
    _KEY = k


def ksa(key):
    """RC4 key schedule: the initial S-box. The BootROM keeps this S-box (not the key) at ROM offset 0x2e34."""
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 255
        S[i], S[j] = S[j], S[i]
    return S


def rc4_sbox(data, sbox):
    """RC4 from a given initial S-box (a fresh state for every call, as the ROM does per sector)."""
    S = list(sbox)
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) & 255
        j = (j + S[i]) & 255
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) & 255])
    return bytes(out)


def rc4(data):
    if _KEY is None:
        set_key()
    return rc4_sbox(data, ksa(_KEY))


def rc4_sectors(b):
    assert len(b) % 512 == 0
    return b''.join(rc4(b[i:i + 512]) for i in range(0, len(b), 512))


def header_fields(h):
    return dict(magic=struct.unpack_from('<I', h, 0)[0], init_offset=struct.unpack_from('<H', h, 0xc)[0],
                init_size=struct.unpack_from('<H', h, 0x1fa)[0], init_boot_size=struct.unpack_from('<H', h, 0x1fc)[0])


def stock_parts(idb):
    """From the stock IDB dump (`rkflashtool i 0 N`, 528-byte sectors, N >= 12): decrypted header (bytearray), raw
    sectors 1..3, FlashData (the DDR init stage)."""
    S = STOCK_SECTOR
    if len(idb) < 12 * S:
        raise SystemExit(f'REFUSE: the IDB dump has {len(idb)} B; it needs at least 12 sectors of {S} B')
    hdr = bytearray(rc4(idb[:512]))
    f = header_fields(hdr)
    if f['magic'] != IDB_MAGIC:
        raise SystemExit(f"REFUSE: the IDB header decrypts to magic {f['magic']:#010x}, not {IDB_MAGIC:#010x}: wrong RC4 key, "
                         'or not an rkflashtool IDB dump (528-byte sectors)')
    o, isz = f['init_offset'], f['init_size']
    if (o, isz) != (4, 8):
        raise SystemExit(f'REFUSE: IDB init_offset/init_size {o}/{isz}, expected 4/8 (the RC2 stock loader)')
    fd = b''.join(rc4(idb[(o + i) * S:(o + i) * S + 512]) for i in range(isz))
    if fd[:4] != b'RK30':
        raise SystemExit('REFUSE: the IDB init stage (FlashData) does not start with RK30')
    raw123 = b''.join(idb[i * S:i * S + 512] for i in (1, 2, 3))
    return hdr, raw123, fd


def rkboot_entry(ldr, kind, name):
    """Decrypted (per 512 B) payload of a loader-section entry of an RKBOOT file (FlashData/FlashBoot)."""
    o = 14 + 7 + 4
    tables = {}
    for k in ('471', '472', 'loader'):
        tables[k] = struct.unpack_from('<BIB', ldr, o)
        o += 6
    n, off, sz = tables[kind]
    for i in range(n):
        e = off + i * sz
        nm = ldr[e + 5:e + 45].decode('utf-16le').rstrip('\0')
        doff, dsz = struct.unpack_from('<II', ldr, e + 45)
        if nm == name:
            return rc4_sectors(ldr[doff:doff + dsz])
    raise KeyError(name)


def build_idb(idb, boot_part):
    """IDB image for card LBA 64: stock header (init_boot_size patched) + stock sectors 1..3 + FlashData + boot_part.
    boot_part is padded to a multiple of 2 KB (the ROM loads 4-sector chunks). Returns (image, fields)."""
    hdr, raw123, fd = stock_parts(idb)
    bp = boot_part + b'\0' * (-len(boot_part) % 2048)
    ibs = 8 + len(bp) // 512
    assert 5 <= ibs <= 0x7fff
    struct.pack_into('<H', hdr, 0x1fc, ibs)
    img = rc4(bytes(hdr)) + raw123 + rc4_sectors(fd) + rc4_sectors(bp)
    return img, header_fields(hdr)
