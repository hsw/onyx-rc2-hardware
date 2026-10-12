#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the RC2 sdboot card image (sdcard.img) and its manifest. Single layout and --data-img: a full card image of exactly
--card-bytes (default the 2 GB SanDisk SDSU02G test card). Data layout: the image ends with partition 1; write-card.sh sets
the p2 length from the card and formats p2 on the card.

Layout (512-byte sectors; README.md "Card layout"):
  LBA 0            MBR (disk signature "RC2S"), see the two layouts below
  LBA 64           IDBlock: RC4'd stock header (init_boot_size patched) + stock sectors 1..3 + stock FlashData (DDR
                   init, 8 sectors) + stage2 (padded to 2 KB). Copies 1..4 (LBA 1088/2112/3136/4160) stay zero.
  LBA 8192         boot table, 2 sectors (stage2/bootinfo.h)
  LBA 16384..      kernel Image, ramdisk, waveform: each at a 1 MiB boundary, zero padded
  single layout (default):
  LBA 131072..     partition 1 (0x83): ext4, label rc2root, to the end of the card (empty, or --rootfs-img as is)
  data layout (--data-partition):
  LBA 131072       partition 1 (0x83): ext4 rc2root, 524288 sectors (256 MiB); --rootfs-img is resized to fit
  LBA 655360..     partition 2 (0x0C): FAT32, label RC2DATA, to the end of the card. Not in the image: the MBR entry
                   carries a placeholder length (the 2 GB card's, 3207168 sectors) that write-card.sh replaces with the
                   card's size, then it formats p2 on the card (formatdata.py, newfs_msdos). With --data-img the image is
                   the full card (--card-bytes) and p2 is that prebuilt FAT32 image

usage: mkcard.py --out DIR --stage2 BIN --idb IDB_DUMP --kernel IMAGE --ramdisk RAMDISK.cpio.gz
                 (--waveform BIN | --no-waveform) [--loader RKBOOT.bin] [--rc4-key HEX]
                 [--card-bytes N] [--data-partition] [--rootfs-img EXT4] [--data-img FAT32] [--halt] [--quiet] [--chunk N]
                 [--cmdline-extra STR] [--name NAME]
Every stock input comes from your own device or firmware (README.md "Inputs"); none is in this repository. The RC4 key
comes from --rc4-key or the environment variable RK_RC4_KEY. Output: DIR/{sdcard.img, manifest.json, manifest.txt,
SHA256SUMS, idb.bin, boottable.bin}. Nothing is written to any device.
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rkidb  # noqa: E402
import fat32  # noqa: E402

DEFAULT_CARD_BYTES = 1977614336          # the 2 GB SanDisk SDSU02G test card (size from the card's sysfs)
DEFAULT_CARD_SECTORS = DEFAULT_CARD_BYTES // 512
CARD_ALIGN = 32768                       # --card-bytes: a multiple of the 32 KiB write block (write-card.sh)
MAX_CARD_BYTES = 32 << 30                # --card-bytes upper bound: SDHC ceiling (README "Card size"); write-card.sh too
IDB_LBA = 64
IDB_COPY_LBAS = [64 + 1024 * k for k in range(5)]
BT_LBA, BT_SIZE, BT_MAGIC, BT_VERSION = 8192, 1024, 0x54423252, 1
BLOB_START_LBA, BLOB_ALIGN = 16384, 2048
PART_LBA = 131072                        # partition 1 in both layouts; the first 64 MiB are the boot area
P1_DATA_SECTORS = 524288                 # data layout: p1 = 256 MiB = 65536 ext4 blocks of 4 KiB
P1_BLOCKS = P1_DATA_SECTORS * 512 // 4096
P2_LBA = PART_LBA + P1_DATA_SECTORS      # 655360 (320 MiB, 4 MiB aligned) = end of the rootfs area
DEFAULT_P2_SECTORS = DEFAULT_CARD_SECTORS - P2_LBA   # 3207168 on the default card
MIN_P1_SINGLE_BYTES = P1_DATA_SECTORS * 512   # single layout: p1 at least 256 MiB, as in the data layout (mke2fs refuses
                                         # the 32 MiB journal below ~100 MiB)
ROOTFS_AREA_BYTES = P2_LBA * 512         # write-card.sh --rootfs: [0, end of p1) = 335544320 B
assert P2_LBA % 8192 == 0 and ROOTFS_AREA_BYTES % CARD_ALIGN == 0
ROOTFS_LASTCHECK = '20261010000000'      # tune2fs -T (TZ=UTC: = EPOCH): e2fsck stamps s_lastcheck with the wall clock
FLAG_HALT, FLAG_QUIET = 1, 2
KIND = {'kernel': 1, 'ramdisk': 2, 'data': 3}
MACHINE, ATAGS, KERNEL_LOAD, INITRD_LOAD, WAVEFORM_LOAD = 3066, 0x60000800, 0x60408000, 0x62000000, 0x7ff00000

EXT4_FEATURES = ('has_journal,ext_attr,resize_inode,dir_index,filetype,extent,sparse_super,large_file,uninit_bg,'
                 '^huge_file,^flex_bg,^metadata_csum,^64bit,^dir_nlink,^extra_isize,^orphan_file,^metadata_csum_seed')
EXT4_UUID = '5d0b7c1e-2a64-4f3b-8e19-c0ffee5d0b01'
EXT4_HASH_SEED = '9e3c1f2a-7b5d-4c6e-a1f0-5d0b7c1e2a64'
EPOCH = 1791590400                        # 2026-10-10 00:00:00 UTC: fixed timestamps, reproducible images
E2FS_SBIN = os.environ.get('E2FSPROGS_SBIN') or next(
    (d for d in ('/opt/homebrew/opt/e2fsprogs/sbin', '/usr/sbin', '/sbin') if os.path.exists(os.path.join(d, 'mke2fs'))),
    '/opt/homebrew/opt/e2fsprogs/sbin')   # Homebrew keg on macOS (keg-only), /usr/sbin on Linux
MKE2FS = os.environ.get('MKE2FS', os.path.join(E2FS_SBIN, 'mke2fs'))
DUMPE2FS = os.environ.get('DUMPE2FS', os.path.join(E2FS_SBIN, 'dumpe2fs'))
E2FSCK = os.environ.get('E2FSCK', os.path.join(E2FS_SBIN, 'e2fsck'))
RESIZE2FS = os.environ.get('RESIZE2FS', os.path.join(E2FS_SBIN, 'resize2fs'))
TUNE2FS = os.environ.get('TUNE2FS', os.path.join(E2FS_SBIN, 'tune2fs'))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read_input(path, what):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError as e:
        sys.exit(f'REFUSE: {what}: {e}')


def boot_table(blobs, cmdline, flags, chunk):
    t = bytearray(BT_SIZE)
    struct.pack_into('<10I', t, 0, BT_MAGIC, BT_VERSION, BT_SIZE, flags, MACHINE, ATAGS, KERNEL_LOAD, chunk,
                     len(blobs), len(cmdline))
    for i, b in enumerate(blobs):
        struct.pack_into('<5I', t, 0x40 + 32 * i, KIND[b['kind']], b['lba'], b['size'], b['load'], b['crc32'])
    c = cmdline.encode('ascii')
    assert len(c) < 764 and all(0x20 <= x <= 0x7e for x in c)
    t[0x100:0x100 + len(c)] = c
    struct.pack_into('<I', t, 0x3fc, zlib.crc32(bytes(t[:0x3fc])) & 0xffffffff)
    return bytes(t)


def min_card_bytes(data_partition):
    """Smallest card for a layout: boot area + 256 MiB p1 (single); boot area + p1 + the smallest FAT32 p2 (data)."""
    if data_partition:
        n = P2_LBA * 512 + fat32.MIN_SECTORS * 512
    else:
        n = PART_LBA * 512 + MIN_P1_SINGLE_BYTES
    return -(-n // CARD_ALIGN) * CARD_ALIGN


def card_error(card_bytes, data_partition):
    """Why --card-bytes cannot hold this layout, or None."""
    if card_bytes % CARD_ALIGN:
        return f'--card-bytes {card_bytes} is not a multiple of {CARD_ALIGN} (32 KiB)'
    if card_bytes > MAX_CARD_BYTES:
        return f'--card-bytes {card_bytes} is larger than {MAX_CARD_BYTES} (32 GiB)'
    lo = min_card_bytes(data_partition)
    if card_bytes < lo:
        return (f"--card-bytes {card_bytes} is smaller than {lo}, the minimum for the "
                f"{'data' if data_partition else 'single'} layout")
    return None


def mbr(parts):
    """parts: [(type, lba, sectors)], at most 4 primary entries."""
    m = bytearray(512)
    struct.pack_into('<I', m, 440, 0x53324352)            # disk signature "RC2S"
    for i, (ptype, lba, n) in enumerate(parts):
        e = 446 + 16 * i
        m[e] = 0x00                                       # not bootable (the ROM ignores the MBR)
        m[e + 1:e + 4] = b'\xfe\xff\xff'                  # CHS: LBA only
        m[e + 4] = ptype
        m[e + 5:e + 8] = b'\xfe\xff\xff'
        struct.pack_into('<II', m, e + 8, lba, n)
    m[510:512] = b'\x55\xaa'
    return bytes(m)


def e2env():
    # TZ: tune2fs -T parses its time as local time; UTC makes s_lastcheck = EPOCH on every host
    return dict(os.environ, MKE2FS_CONFIG=os.path.join(HERE, 'mke2fs.conf'), E2FSPROGS_FAKE_TIME=str(EPOCH),
                SOURCE_DATE_EPOCH=str(EPOCH), TZ='UTC')


def make_ext4(path, nbytes):
    with open(path, 'wb') as f:
        f.truncate(nbytes)
    subprocess.run([MKE2FS, '-q', '-F', '-t', 'ext4', '-O', EXT4_FEATURES, '-b', '4096', '-I', '256', '-i', '16384',
                    '-m', '1', '-L', 'rc2root', '-U', EXT4_UUID, '-J', 'size=32',
                    '-E', f'hash_seed={EXT4_HASH_SEED},lazy_itable_init=0,lazy_journal_init=0', path],
                   check=True, env=e2env())


def ext4_super(path):
    r = subprocess.run([DUMPE2FS, '-h', path], capture_output=True, text=True, env=e2env())
    out = r.stdout if r.returncode == 0 else ''          # not an ext2/3/4 image: no fields, no label
    return {k.strip(): v.strip() for k, v in (line.split(':', 1) for line in out.splitlines() if ':' in line)}


def ext4_label(path):
    return ext4_super(path).get('Filesystem volume name')


def fit_rootfs(src, dst, nbytes):
    """Copy the ext4 `src` to `dst` resized to exactly `nbytes` (4 KiB blocks) and make it reproducible: e2fsck -fy,
    resize2fs, tune2fs -T (e2fsck stamps s_lastcheck with the wall clock), e2fsck -fn must be clean. Never mkfs."""
    blocks = nbytes // 4096
    size = os.path.getsize(src)
    with open(dst, 'wb') as f:
        f.truncate(size)
        copy_sparse(f, src, 0)
    sb = ext4_super(dst)
    if sb.get('Filesystem volume name') != 'rc2root':
        sys.exit(f"REFUSE: --rootfs-img has ext4 label {sb.get('Filesystem volume name')!r}, not rc2root")
    if sb.get('Block size') != '4096':
        sys.exit(f"REFUSE: --rootfs-img block size {sb.get('Block size')}, not 4096")
    used = int(sb['Block count']) - int(sb['Free blocks'])
    if used > blocks:
        sys.exit(f'REFUSE: --rootfs-img uses {used} blocks, partition 1 has {blocks}')
    env = e2env()

    def run(*cmd, ok=(0,)):
        r = subprocess.run(list(cmd), env=env, capture_output=True, text=True)
        if r.returncode not in ok:
            sys.exit(f'REFUSE: {os.path.basename(cmd[0])} exit {r.returncode} on the rootfs copy:\n{r.stdout}{r.stderr}')
        return r
    if size < nbytes:
        with open(dst, 'r+b') as f:
            f.truncate(nbytes)
    r = run(E2FSCK, '-fy', dst, ok=(0, 1))
    if r.returncode == 1:
        print(f'note: e2fsck -fy corrected the rootfs copy:\n{r.stdout}', file=sys.stderr)
    if size > nbytes:
        need = int(run(RESIZE2FS, '-P', dst).stdout.strip().rsplit(':', 1)[1])
        if need > blocks:
            sys.exit(f'REFUSE: --rootfs-img needs at least {need} blocks (resize2fs -P), partition 1 has {blocks}')
    run(RESIZE2FS, dst, str(blocks))
    if size > nbytes:
        with open(dst, 'r+b') as f:
            f.truncate(nbytes)
    run(TUNE2FS, '-T', ROOTFS_LASTCHECK, dst)
    run(E2FSCK, '-fn', dst)
    sb = ext4_super(dst)
    assert int(sb['Block count']) == blocks and os.path.getsize(dst) == nbytes, (sb['Block count'], nbytes)
    return int(sb['Block count']) - int(sb['Free blocks'])


def copy_sparse(dst, src_path, offset):
    with open(src_path, 'rb') as s:
        pos = 0
        while True:
            b = s.read(1 << 20)
            if not b:
                break
            if b.count(0) != len(b):
                dst.seek(offset + pos)
                dst.write(b)
            pos += len(b)
    return pos


def file_sha(path, limit=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        left = limit
        while True:
            n = 1 << 22 if left is None else min(1 << 22, left)
            if n == 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()


def git_head():
    try:
        return subprocess.run(['git', '-C', HERE, 'rev-parse', '--short=12', 'HEAD'], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return 'unknown'


def range_shas(path, ranges):
    """sha256 of several [start, end) byte ranges of one file in a single pass."""
    hs = {k: hashlib.sha256() for k in ranges}
    with open(path, 'rb') as f:
        pos = 0
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            for k, (lo, hi) in ranges.items():
                a, z = max(lo, pos), min(hi, pos + len(b))
                if a < z:
                    hs[k].update(b[a - pos:z - pos])
            pos += len(b)
    return {k: h.hexdigest() for k, h in hs.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--name', default='rc2-sdboot')
    ap.add_argument('--stage2', required=True, help='stage2.bin from stage2/build.sh')
    ap.add_argument('--idb', required=True,
                    help='IDB dump of your own device (rkflashtool i 0 N, 528-byte sectors, N >= 12): the stock header, '
                    'sectors 1..3 and the DDR init (FlashData) are taken from it')
    ap.add_argument('--loader', help='optional: the RKBOOT loader file of your firmware; its FlashData must equal the '
                    "IDB dump's (a cross-check)")
    ap.add_argument('--rc4-key', help='Rockchip IDBlock RC4 key, 32 hex digits (default: $RK_RC4_KEY)')
    ap.add_argument('--kernel', required=True, help='kernel Image (the stock 3.0.36+ Image of your firmware)')
    ap.add_argument('--ramdisk', required=True, help='gzip cpio initramfs')
    ap.add_argument('--waveform', help='blob for waveform_addr: ebc_waveform.bin from your stock boot ramdisk')
    ap.add_argument('--no-waveform', action='store_true')
    ap.add_argument('--card-bytes', type=int,
                    help='full images only (single layout, --data-img): card (= image) size in bytes, a multiple of '
                    f'32 KiB, at most 32 GiB (default {DEFAULT_CARD_BYTES}, the 2 GB test card; "Disk Size" in diskutil '
                    'info diskN). The data layout without --data-img takes the size from the card at write time')
    ap.add_argument('--data-partition', action='store_true',
                    help='two partitions: ext4 rc2root 256 MiB + FAT32 RC2DATA to the end (default: one ext4 partition)')
    ap.add_argument('--rootfs-img', help='ext4 image (label rc2root) for partition 1 instead of an empty ext4; with '
                    f'--data-partition it is resized to {P1_BLOCKS} blocks (a copy; the input is not changed)')
    ap.add_argument('--data-img', help='with --data-partition: prebuilt FAT32 image (label RC2DATA, exactly the size of '
                    'partition 2) instead of the empty one')
    ap.add_argument('--halt', action='store_true', help='boot-table flag: load and verify, do not jump')
    ap.add_argument('--quiet', action='store_true', help='boot-table flag: no progress blinks')
    ap.add_argument('--chunk', type=int, default=4,
                    help='sectors per ROM read call, 1..128 (default 4 = 2 KB, what the ROM itself uses)')
    ap.add_argument('--cmdline-extra', default='')
    ap.add_argument('--no-partition', action='store_true', help='tests: leave the partitions zero (no mke2fs)')
    a = ap.parse_args()
    if a.data_img and not a.data_partition:
        sys.exit('REFUSE: --data-img needs --data-partition')
    fow = a.data_partition and not a.data_img   # p2 formatted on the card, its MBR length set at write time
    if fow and a.card_bytes is not None:
        sys.exit('REFUSE: --card-bytes: the data layout takes the p2 length from the card at write time (write-card.sh); '
                 '--card-bytes is for full images (single layout, --data-img)')
    card_bytes = DEFAULT_CARD_BYTES if a.card_bytes is None else a.card_bytes
    err = card_error(card_bytes, a.data_partition)
    if err:
        sys.exit('REFUSE: ' + err)
    card_sectors = card_bytes // 512
    p2_sectors = card_sectors - P2_LBA            # with fow: the placeholder (the 2 GB card's p2)
    image_bytes = ROOTFS_AREA_BYTES if fow else card_bytes

    if not a.waveform and not a.no_waveform:
        sys.exit('REFUSE: give --waveform (ebc_waveform.bin from your stock boot ramdisk) or --no-waveform')
    rkidb.set_key(a.rc4_key)

    idb = read_input(a.idb, '--idb')
    kernel = read_input(a.kernel, '--kernel')
    stage2 = read_input(a.stage2, '--stage2')
    ramdisk = read_input(a.ramdisk, '--ramdisk')
    if ramdisk[:2] != b'\x1f\x8b':
        sys.exit('REFUSE: ramdisk is not gzip')
    inputs = dict(idb=dict(name=os.path.basename(a.idb), sha256=sha(idb)),
                  kernel=dict(name=os.path.basename(a.kernel), sha256=sha(kernel)))

    _, _, fd = rkidb.stock_parts(idb)
    if a.loader:   # FlashData in the IDB dump == FlashData in the RKBOOT loader file
        ldr = read_input(a.loader, '--loader')
        try:
            ldr_fd = rkidb.rkboot_entry(ldr, 'loader', 'FlashData')
        except (KeyError, struct.error, UnicodeDecodeError):
            sys.exit('REFUSE: --loader has no FlashData entry (not an RKBOOT loader file?)')
        if fd != ldr_fd:
            sys.exit('REFUSE: FlashData differs between the IDB dump and --loader')
        inputs['loader'] = dict(name=os.path.basename(a.loader), sha256=sha(ldr))
    idb_img, hdr = rkidb.build_idb(idb, stage2)
    assert len(idb_img) // 512 + IDB_LBA <= IDB_COPY_LBAS[1], 'IDB overlaps the ROM copy-1 slot'

    blobs = [dict(kind='kernel', name=os.path.basename(a.kernel), data=kernel, load=KERNEL_LOAD),
             dict(kind='ramdisk', name=os.path.basename(a.ramdisk), data=ramdisk, load=INITRD_LOAD)]
    if not a.no_waveform:
        wf = read_input(a.waveform, '--waveform')
        inputs['waveform'] = dict(name=os.path.basename(a.waveform), sha256=sha(wf))
        blobs.append(dict(kind='data', name=os.path.basename(a.waveform), data=wf, load=WAVEFORM_LOAD))
    lba = BLOB_START_LBA
    for b in blobs:
        b['lba'] = lba
        b['size'] = len(b['data'])
        b['crc32'] = zlib.crc32(b['data']) & 0xffffffff
        b['sha256'] = sha(b['data'])
        lba += -(-b['size'] // (512 * BLOB_ALIGN)) * BLOB_ALIGN
    if lba > PART_LBA:
        sys.exit('REFUSE: blobs overlap partition 1')
    if KERNEL_LOAD + len(kernel) > INITRD_LOAD:
        sys.exit('REFUSE: kernel Image runs into the initrd address')

    cmdline = (f'console=ttyFIQ0 androidboot.console=ttyFIQ0 waveform_addr=0x{WAVEFORM_LOAD:08x} init=/init '
               f'initrd=0x{INITRD_LOAD:08X},0x{len(ramdisk):08X} pcb_ver=2 onyx_emmc=1 rc2.root=sd')
    if a.cmdline_extra:
        cmdline += ' ' + a.cmdline_extra
    flags = (FLAG_HALT if a.halt else 0) | (FLAG_QUIET if a.quiet else 0)
    if not 1 <= a.chunk <= 128:
        sys.exit('REFUSE: --chunk must be 1..128')
    bt = boot_table(blobs, cmdline, flags, a.chunk)

    layout = 'data' if a.data_partition else 'single'
    parts = [dict(index=1, lba=PART_LBA, sectors=P1_DATA_SECTORS if a.data_partition else card_sectors - PART_LBA,
                  type='0x83', fs='ext4', label='rc2root')]
    if a.data_partition:
        parts.append(dict(index=2, lba=P2_LBA, sectors=p2_sectors, type='0x0c', fs='fat32', label=fat32.LABEL,
                          serial=f'0x{fat32.SERIAL:08x}'))
    for p in parts:
        p['offset'], p['bytes'] = p['lba'] * 512, p['sectors'] * 512
    p1 = parts[0]
    mbr_sector = mbr([(int(p['type'], 16), p['lba'], p['sectors']) for p in parts])
    if a.data_img:
        if os.path.getsize(a.data_img) != p2_sectors * 512:
            sys.exit(f'REFUSE: --data-img is {os.path.getsize(a.data_img)} B, partition 2 is {p2_sectors * 512} B')
        with open(a.data_img, 'rb') as d:
            bad = fat32.check_boot_sector(d.read(512), p2_sectors)
        if bad:
            sys.exit('REFUSE: --data-img boot sector: ' + '; '.join(bad))

    os.makedirs(a.out, exist_ok=True)
    for n in ('manifest.json', 'manifest.txt', 'SHA256SUMS'):   # never leave an old manifest next to a new image
        if os.path.exists(os.path.join(a.out, n)):
            os.remove(os.path.join(a.out, n))
    img_path = os.path.join(a.out, 'sdcard.img')
    with open(img_path, 'wb') as f, tempfile.TemporaryDirectory() as td:
        f.truncate(image_bytes)
        f.seek(0); f.write(mbr_sector)
        f.seek(IDB_LBA * 512); f.write(idb_img)
        f.seek(BT_LBA * 512); f.write(bt)
        for b in blobs:
            f.seek(b['lba'] * 512); f.write(b['data'])
        if a.no_partition:
            for p in parts:
                p['content'] = 'zero (--no-partition)'
        else:
            if a.rootfs_img and a.data_partition:
                src, tmp = a.rootfs_img, os.path.join(td, 'p1.ext4')
                used = fit_rootfs(src, tmp, p1['bytes'])
                p1['content'] = (f'{os.path.basename(src)} sha256 {file_sha(src)}, resized to {p1["bytes"] // 4096} '
                                 f'blocks ({used} used), lastcheck {ROOTFS_LASTCHECK}')
                copy_sparse(f, tmp, p1['offset'])
            elif a.rootfs_img:
                src = a.rootfs_img
                if os.path.getsize(src) > p1['bytes']:
                    sys.exit('REFUSE: --rootfs-img larger than partition 1')
                if ext4_label(src) != 'rc2root':
                    sys.exit('REFUSE: --rootfs-img has no ext4 label rc2root')
                p1['content'] = f'{os.path.basename(src)} sha256 {file_sha(src)}'
                copy_sparse(f, src, p1['offset'])
            else:
                tmp = os.path.join(td, 'p1.ext4')
                make_ext4(tmp, p1['bytes'])
                p1['content'] = f'empty ext4, uuid {EXT4_UUID}, sha256 {file_sha(tmp)}'
                copy_sparse(f, tmp, p1['offset'])
            if a.data_partition:
                p2 = parts[1]
                if a.data_img:
                    p2['content'] = f'{os.path.basename(a.data_img)} sha256 {file_sha(a.data_img)}'
                    copy_sparse(f, a.data_img, p2['offset'])
    if fow:
        p2 = parts[1]
        p2.update(format_on_write=True, sha256=None,
                  content='not in the image: write-card.sh sets the MBR length from the card (placeholder: the 2 GB '
                  'card\'s) and formats it on the card (formatdata.py: newfs_msdos FAT32 RC2DATA, 32 KiB aligned)')
    assert os.path.getsize(img_path) == image_bytes
    ranges = dict(img=(0, image_bytes), boot=(0, PART_LBA * 512), rootfs_area=(0, p1['offset'] + p1['bytes']))
    ranges.update({f"p{p['index']}": (p['offset'], p['offset'] + p['bytes']) for p in parts
                   if p['offset'] + p['bytes'] <= image_bytes})
    hashes = range_shas(img_path, ranges)
    for p in parts:
        if f"p{p['index']}" in hashes:
            p['sha256'] = hashes[f"p{p['index']}"]

    open(os.path.join(a.out, 'idb.bin'), 'wb').write(idb_img)
    open(os.path.join(a.out, 'boottable.bin'), 'wb').write(bt)
    m = dict(
        name=a.name, image_bytes=image_bytes, card_bytes=None if fow else card_bytes, git_head=git_head(),
        layout=layout, sdcard_img_sha256=hashes['img'],
        boot_area_bytes=PART_LBA * 512, boot_area_sha256=hashes['boot'],
        mbr=dict(lba=0, disk_signature='0x53324352', table_hex=mbr_sector[446:510].hex(), boot_signature='55aa'),
        partitions=parts,
        idb=dict(lba=IDB_LBA, bytes=len(idb_img), sha256=sha(idb_img), header=hdr,
                 flashdata_sha256=sha(fd), stage2=dict(name=os.path.basename(a.stage2), bytes=len(stage2),
                                                       sha256=sha(stage2)),
                 copies_1_to_4='zero (LBA 1088, 2112, 3136, 4160)'),
        boot_table=dict(lba=BT_LBA, bytes=BT_SIZE, sha256=sha(bt), flags=flags, chunk_sectors=a.chunk,
                        machine=MACHINE, atags=f'0x{ATAGS:08x}', entry=f'0x{KERNEL_LOAD:08x}', cmdline=cmdline),
        blobs=[dict(kind=b['kind'], name=b['name'], lba=b['lba'], offset=b['lba'] * 512, size=b['size'],
                    load=f"0x{b['load']:08x}", crc32=f"0x{b['crc32']:08x}", sha256=b['sha256']) for b in blobs],
        inputs=inputs,
    )
    if a.data_partition:   # write-card.sh --rootfs: [0, end of partition 1)
        assert ranges['rootfs_area'][1] == ROOTFS_AREA_BYTES
        m['rootfs_area_bytes'], m['rootfs_area_sha256'] = ROOTFS_AREA_BYTES, hashes['rootfs_area']
    json.dump(m, open(os.path.join(a.out, 'manifest.json'), 'w'), indent=1)
    with open(os.path.join(a.out, 'manifest.txt'), 'w') as t:
        t.write(f"{a.name}  sdcard.img {image_bytes} B  sha256 {m['sdcard_img_sha256']}\n")
        t.write('card size: set at write time (p2 length from the card, p2 formatted on the card)\n' if fow
                else f'card size {card_bytes} B (full image)\n')
        t.write(f"layout {layout}\n")
        t.write(f"boot area (first {PART_LBA * 512} B) sha256 {m['boot_area_sha256']}\n")
        if a.data_partition:
            t.write(f"rootfs area (first {m['rootfs_area_bytes']} B) sha256 {m['rootfs_area_sha256']}\n")
        t.write(f"MBR partition table (bytes 446..509) {m['mbr']['table_hex']}\n")
        t.write(f"git {m['git_head']}\n")
        t.write(f"LBA {IDB_LBA:>7}  IDB {len(idb_img)} B sha256 {sha(idb_img)} (init_boot_size {hdr['init_boot_size']},"
                f" stage2 {len(stage2)} B sha256 {sha(stage2)})\n")
        t.write(f"LBA {BT_LBA:>7}  boot table flags {flags} chunk {a.chunk} sha256 {sha(bt)}\n")
        for b in blobs:
            t.write(f"LBA {b['lba']:>7}  {b['kind']:<8} {b['size']:>9} B -> 0x{b['load']:08x} crc32 0x{b['crc32']:08x}"
                    f" sha256 {b['sha256']} ({b['name']})\n")
        for p in parts:
            n = f"{p['sectors']} sectors (placeholder)" if p.get('format_on_write') else f"{p['sectors']} sectors"
            h = '' if p.get('format_on_write') else f", sha256 {p['sha256']}"
            t.write(f"LBA {p['lba']:>7}  partition {p['index']} type {p['type']} {p['fs']} {p['label']}, {n}{h}: "
                    f"{p['content']}\n")
        t.write(f"cmdline: {cmdline}\n")
    with open(os.path.join(a.out, 'SHA256SUMS'), 'w') as s:
        s.write(f"{m['sdcard_img_sha256']}  sdcard.img\n{sha(idb_img)}  idb.bin\n{sha(bt)}  boottable.bin\n")
    print(open(os.path.join(a.out, 'manifest.txt')).read(), end='')


if __name__ == '__main__':
    main()
