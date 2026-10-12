#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic stand-ins for the stock inputs, so that the card builder and the tests run without any vendor file.

usage: fake_inputs.py OUTDIR
Writes OUTDIR/{idb.bin, kernel.bin, waveform.bin, busybox, rc4key.txt}:
  idb.bin       12 sectors of 528 B in the rkflashtool IDB dump format: an RC4'd header (magic 0x0FF0AA55, init_offset 4,
                init_size 8, init_boot_size 232 as the stock RC2 IDB), filler sectors 1..3, and an 8-sector "FlashData"
                that starts with "RK30" and is otherwise filler (it is never executed: the Unicorn chain test stubs it)
  kernel.bin    1 MiB of filler (stage2 only loads and CRC-checks it; the test stops at the kernel entry)
  waveform.bin  256 003 B of filler (the size of the stock ebc_waveform.bin)
  busybox       a text placeholder (the ramdisk build only packs it)
  rc4key.txt    the key used for idb.bin: $RK_RC4_KEY if set (then the Unicorn chain test can run the ROM's own
                decryption on it), else a fixed test key that is NOT the Rockchip key
Nothing here is vendor data; all bytes come from a seeded generator.
"""
import os, random, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rkidb  # noqa: E402

TEST_KEY = '00112233445566778899aabbccddeeff'      # not the Rockchip key


def filler(rng, n):
    return rng.randbytes(n)


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    key = os.environ.get('RK_RC4_KEY') or TEST_KEY
    rkidb.set_key(key)
    rng = random.Random(3026)
    hdr = bytearray(filler(rng, 512))
    struct.pack_into('<I', hdr, 0, rkidb.IDB_MAGIC)
    struct.pack_into('<H', hdr, 0x0c, 4)
    struct.pack_into('<H', hdr, 0x1fa, 8)
    struct.pack_into('<H', hdr, 0x1fc, 232)
    sectors = [rkidb.rc4(bytes(hdr))] + [filler(rng, 512) for _ in range(3)]
    fd = b'RK30' + filler(rng, 8 * 512 - 4)
    sectors += [rkidb.rc4(fd[i:i + 512]) for i in range(0, len(fd), 512)]
    idb = b''.join(s + b'\xff' * 16 for s in sectors)            # 528-byte sectors: 512 data + 16 spare
    files = {'idb.bin': idb, 'kernel.bin': filler(rng, 1 << 20), 'waveform.bin': filler(rng, 256003),
             'busybox': b'placeholder, not a busybox binary\n', 'rc4key.txt': (key + '\n').encode()}
    for name, data in files.items():
        with open(os.path.join(out, name), 'wb') as f:
            f.write(data)
    print(f"fake inputs in {out} ({'RK_RC4_KEY' if os.environ.get('RK_RC4_KEY') else 'test key, chain test will skip'})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
