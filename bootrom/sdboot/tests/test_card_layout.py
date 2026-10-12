#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host tests for the card layouts (mkcard.py --data-partition, fat32.py, mbrguard.py, write-card.sh mode checks).
No device and no disk is touched; write-card.sh is only run into its refusals, which come before any diskutil call.

usage: python3 -I tests/test_card_layout.py STAGE2_BIN RAMDISK WORKDIR [SINGLE_CARD_DIR] -- MKCARD_INPUT_ARGS...
  WORKDIR            scratch (sparse 1.9 GB images; emptied of the large files at the end)
  SINGLE_CARD_DIR    a default (single-partition) card built by run.sh, for the old-layout manifest and MBR guard checks
  MKCARD_INPUT_ARGS  the stock inputs for mkcard.py (--idb, --kernel, --waveform, ...; real ones or fake_inputs.py's);
                     the RC4 key comes from RK_RC4_KEY
Checks:
  - data-layout card built twice with --rootfs-img: identical sdcard.img; MBR entries; manifest hashes recomputed
  - p1: grown to 65536 blocks of 4 KiB, label rc2root, e2fsck -fn clean, test file intact, shrink path, refusals
  - the fat32.py p2 (for --data-img): tests/check_fat32.py --empty; fsck.fat -n; mdir (label, empty); mcopy round trip + fsck.fat -n (SKIP without them)
  - --data-img: the empty p2 gives the format-on-write image + that p2 (full 2 GB image); a filled one lands byte for byte; wrong size/label refused
  - mbrguard.py on old-layout vs new-layout sectors; write-card.sh refusals (bad mode, --rootfs on a single-layout card)
  - data layout: the image ends with p1 (320 MiB), p2 is an MBR entry with the placeholder length and format_on_write;
    mbrguard.py p2-for-disk / patch / sha / written / --p2-any-length for the p2 length set at write time (2 GB, 32 GiB)
  - --card-bytes (full images: single layout, --data-img): 4 GiB gives a consistent MBR and manifest; not a multiple of
    32 KiB, above 32 GiB, too small for the layout, or with the format-on-write data layout: refused
"""
import hashlib, json, os, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, TOOL)
import mkcard  # noqa: E402

P1_LBA, P1_SECTORS, P2_LBA, P2_SECTORS = 131072, 524288, 655360, 3207168   # the spec, on purpose not imported
P1_BLOCKS = P1_SECTORS // 8
P1_OFF, P1_BYTES, P2_OFF, P2_BYTES = P1_LBA * 512, P1_SECTORS * 512, P2_LBA * 512, P2_SECTORS * 512
ROOTFS_AREA = P1_OFF + P1_BYTES
HELLO = b'rc2 card layout test\n'
fails = 0


def check(ok, what):
    global fails
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        fails += 1
    return ok


def skip(what):
    print('SKIP ' + what, flush=True)


def tool(name, dirs=('/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/sbin', '/sbin')):
    p = shutil.which(name)
    if p:
        return p
    return next((os.path.join(d, name) for d in dirs if os.access(os.path.join(d, name), os.X_OK)), None)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def extract(img, off, n, dst):
    with open(img, 'rb') as s, open(dst, 'wb') as d:
        d.truncate(n)
        s.seek(off)
        pos = 0
        while pos < n:
            b = s.read(min(1 << 22, n - pos))
            if b.count(0) != len(b):
                d.seek(pos)
                d.write(b)
            pos += len(b)


def card_consistent(d, card_bytes, layout):
    """sdcard.img size, manifest card_bytes/image_bytes/layout/partitions/mbr.table_hex/sha256 and the MBR entries agree.
    card_bytes None: the data layout with p2 formatted on write (image = first 320 MiB, p2 length = the placeholder)."""
    img, m = os.path.join(d, 'sdcard.img'), json.load(open(os.path.join(d, 'manifest.json')))
    fow = card_bytes is None
    image_bytes = ROOTFS_AREA if fow else card_bytes
    sectors = (mkcard.DEFAULT_CARD_BYTES if fow else card_bytes) // 512
    with open(img, 'rb') as f:
        sec0 = f.read(512)
    ents = [struct.unpack_from('<B3xII', sec0, 446 + 16 * i + 4)[0:3] for i in range(4)]
    if layout == 'data':
        want = [(0x83, P1_LBA, P1_SECTORS), (0x0C, P2_LBA, sectors - P2_LBA)]
    else:
        want = [(0x83, P1_LBA, sectors - P1_LBA)]
    mp = [(int(p['type'], 16), p['lba'], p['sectors']) for p in m['partitions']]
    bad = [what for what, ok in (
        ('file size', os.path.getsize(img) == image_bytes),
        ('manifest card_bytes, image_bytes', m.get('card_bytes') == card_bytes and m.get('image_bytes') == image_bytes),
        ('p2 format_on_write', not fow or (m['partitions'][1].get('format_on_write') is True
                                           and m['partitions'][1].get('sha256') is None)),
        ('manifest layout', m['layout'] == layout),
        ('MBR entries', ents == want + [(0, 0, 0)] * (4 - len(want))),
        ('manifest partitions', mp == want and all(p['offset'] == p['lba'] * 512 and p['bytes'] == p['sectors'] * 512
                                                   for p in m['partitions'])),
        ('last partition ends at the card end', want[-1][1] + want[-1][2] == sectors),
        ('mbr.table_hex', m['mbr']['table_hex'] == sec0[446:510].hex()),
        ('55 AA', sec0[510:512] == b'\x55\xaa'),
        ('sdcard_img_sha256', m['sdcard_img_sha256'] == mkcard.file_sha(img)),
        ('rootfs area', layout != 'data' or m['rootfs_area_bytes'] == ROOTFS_AREA)) if not ok]
    return bad


def sha_range(path, off, n):
    return mkcard.range_shas(path, {'r': (off, off + n)})['r']


def main(argv):
    inputs = []
    if '--' in argv:
        k = argv.index('--')
        argv, inputs = argv[:k], argv[k + 1:]
    if len(argv) not in (4, 5) or not inputs:
        print(__doc__)
        return 2
    stage2, ramdisk, work = argv[1], argv[2], argv[3]
    single = argv[4] if len(argv) == 5 else None
    os.makedirs(work, exist_ok=True)

    def mk(out, *extra):
        return run([sys.executable, '-I', os.path.join(TOOL, 'mkcard.py'), '--stage2', stage2, '--ramdisk', ramdisk,
                    '--out', os.path.join(work, out), *inputs, *extra])

    def refused(r, what):
        return check(r.returncode != 0 and 'REFUSE' in r.stderr + r.stdout,
                     f"refused: {what} ({(r.stderr + r.stdout).strip().splitlines()[-1] if (r.stderr + r.stdout).strip() else r.returncode})")

    # --- mbrguard.py on sectors: works without e2fsprogs
    old = mkcard.mbr([(0x83, P1_LBA, mkcard.DEFAULT_CARD_SECTORS - P1_LBA)])
    new = mkcard.mbr([(0x83, P1_LBA, P1_SECTORS), (0x0C, P2_LBA, P2_SECTORS)])
    for n, b in (('old.mbr', old), ('new.mbr', new + b'\xa5' * 32256), ('short.mbr', new[:100])):
        open(os.path.join(work, n), 'wb').write(b)
    g = [sys.executable, '-I', os.path.join(TOOL, 'mbrguard.py')]
    w = lambda n: os.path.join(work, n)  # noqa: E731
    check(run(g + [w('old.mbr'), w('new.mbr')]).returncode == 1, 'mbrguard: old single-partition card vs data image -> 1')
    check(run(g + [w('new.mbr'), w('old.mbr')]).returncode == 1, 'mbrguard: data card vs single image -> 1')
    r = run(g + [w('new.mbr'), w('new.mbr'), new[446:510].hex()])
    check(r.returncode == 0 and 'MBR guard OK' in r.stdout, 'mbrguard: same table (32 KiB card head) -> 0')
    check(run(g + [w('old.mbr'), w('old.mbr'), new[446:510].hex()]).returncode == 2, 'mbrguard: image != manifest hex -> 2')
    check(run(g + [w('short.mbr'), w('new.mbr')]).returncode == 2, 'mbrguard: short card read -> 2')
    blank = bytearray(new)
    blank[446:512] = bytes(66)
    open(w('blank.mbr'), 'wb').write(blank)
    check(run(g + [w('blank.mbr'), w('new.mbr')]).returncode == 1, 'mbrguard: blank card -> 1')

    # --- fat32.py alone
    p2e = w('p2-empty.img')
    r = run([sys.executable, '-I', os.path.join(TOOL, 'fat32.py'), p2e])
    check(r.returncode == 0 and os.path.getsize(p2e) == P2_BYTES, 'fat32.py writes a p2-sized image')
    r = run([sys.executable, '-I', os.path.join(HERE, 'check_fat32.py'), p2e, '--empty'])
    check(r.returncode == 0, 'check_fat32.py --empty on fat32.py output' + ('' if r.returncode == 0 else '\n' + r.stdout))

    # --- --card-bytes: refusals and consistent layouts at another size (partitions left zero: no e2fsprogs needed)
    G4 = 4 << 30
    refused(mk('dX', '--no-partition', '--card-bytes', str(mkcard.DEFAULT_CARD_BYTES + 512)),
            '--card-bytes not a multiple of 32 KiB (default size + 512)')
    refused(mk('dX', '--no-partition', '--card-bytes', str(G4 + 4096)), '--card-bytes 4 GiB + 4 KiB')
    refused(mk('dX', '--no-partition', '--card-bytes', str((32 << 30) + 32768)), '--card-bytes above 32 GiB')
    refused(mk('dX', '--no-partition', '--data-partition', '--data-img', p2e, '--card-bytes',
               str(mkcard.min_card_bytes(True) - 32768)),
            f'--data-img --card-bytes {mkcard.min_card_bytes(True) - 32768} (32 KiB below the FAT32 minimum)')
    refused(mk('dX', '--no-partition', '--data-partition', '--card-bytes', str(mkcard.DEFAULT_CARD_BYTES)),
            '--data-partition --card-bytes without --data-img (p2 length comes from the card)')
    refused(mk('dX', '--no-partition', '--card-bytes', str(256 << 20)), '--card-bytes 256 MiB (single layout)')
    refused(mk('dX', '--no-partition', '--card-bytes', '0'), '--card-bytes 0')
    p2g4 = w('p2-4g.img')
    r = run([sys.executable, '-I', os.path.join(TOOL, 'fat32.py'), p2g4, '--card-bytes', str(G4)])
    check(r.returncode == 0 and os.path.getsize(p2g4) == G4 - P2_OFF, 'fat32.py --card-bytes 4 GiB: p2-sized image')
    for what, cb, lay, extra in (('single layout --card-bytes 4 GiB', G4, 'single', ['--card-bytes', str(G4)]),
                                 ('data layout --data-img --card-bytes 4 GiB', G4, 'data',
                                  ['--data-partition', '--data-img', p2g4, '--card-bytes', str(G4)]),
                                 ('data layout, p2 formatted on write', None, 'data', ['--data-partition'])):
        r = mk('dG', '--no-partition', *extra)
        bad = card_consistent(w('dG'), cb, lay) if r.returncode == 0 else [r.stderr.strip()]
        check(not bad, f'{what}: MBR, manifest, sha256 consistent' + (f' (bad: {bad})' if bad else ''))

    # --- p2 length set at write time (mbrguard.py), on the format-on-write image just built (dG)
    F = w('dG/sdcard.img')
    with open(F, 'rb') as f:
        fhead = f.read(32768)
    for disk, want in ((mkcard.DEFAULT_CARD_BYTES, P2_SECTORS), (32 << 30, (32 << 30) // 512 - P2_LBA),
                       (31914983424 + 4096, 31914983424 // 512 - P2_LBA)):
        r = run(g + ['p2-for-disk', str(disk)])
        check(r.returncode == 0 and r.stdout.strip() == str(want), f'mbrguard p2-for-disk {disk}: {r.stdout.strip()} == {want}')
    r = run(g + ['p2-for-disk', str(600 << 20)])
    check(r.returncode == 0, f'mbrguard p2-for-disk 600 MiB: {r.stdout.strip()} (>= the FAT32 minimum)')
    refused(run(g + ['p2-for-disk', str(512 << 20)]), 'mbrguard p2-for-disk 512 MiB (p2 below the FAT32 minimum)')
    for disk in (mkcard.DEFAULT_CARD_BYTES, 32 << 30):
        p2n = (disk // 512) - P2_LBA
        r = run(g + ['patch', F, w('head.bin'), str(p2n)])
        ph = open(w('head.bin'), 'rb').read() if r.returncode == 0 else b''
        ents = [struct.unpack_from('<B3xII', ph, 446 + 16 * i + 4)[0:3] for i in range(4)] if ph else []
        diff = [i for i in range(32768) if ph and ph[i] != fhead[i]]
        check(len(ph) == 32768 and ents[:2] == [(0x83, P1_LBA, P1_SECTORS), (0x0C, P2_LBA, p2n)]
              and all(474 <= i < 478 for i in diff),
              f'mbrguard patch for a {disk} B card: p2 = {p2n} sectors, only bytes 474..477 differ ({diff[:4]})')
        hh = hashlib.sha256(ph)
        with open(F, 'rb') as f:
            f.seek(32768)
            hh.update(f.read())
        r = run(g + ['sha', F, w('head.bin'), str(ROOTFS_AREA)])
        check(r.stdout.strip() == hh.hexdigest(), f'mbrguard sha: patched image hash ({disk} B card)')
        open(w('card.bin'), 'wb').write(ph)
        check(run(g + ['written', w('card.bin'), F, str(p2n)]).returncode == 0, f'mbrguard written: card = patched image ({disk})')
        check(run(g + ['written', w('card.bin'), F, str(p2n - 64)]).returncode == 1, 'mbrguard written: other p2 length -> 1')
        r = run(g + [w('card.bin'), F, fhead[446:510].hex(), '--p2-any-length'])
        check(r.returncode == 0 and f'{p2n} sectors' in r.stdout, f'mbrguard --p2-any-length: card p2 {p2n} sectors -> 0')
        check(run(g + [w('card.bin'), F]).returncode == (0 if p2n == P2_SECTORS else 1),
              'mbrguard exact compare: equal only for the placeholder length')
        r = run(g + ['card-p2', w('card.bin')])
        check(r.stdout.strip() == str(p2n), f'mbrguard card-p2: {r.stdout.strip()}')
    check(run(g + ['written', F, F, str(32 << 20)]).returncode == 1, 'mbrguard written: unpatched card MBR -> 1')
    for what, off, val in (('p2 start LBA', 470, P2_LBA + 64), ('p1 length', 458, P1_SECTORS - 8), ('p2 length 0', 474, 0)):
        bb = bytearray(ph)
        struct.pack_into('<I', bb, off, val)
        open(w('card.bin'), 'wb').write(bb)
        check(run(g + [w('card.bin'), F, '--p2-any-length']).returncode == 1, f'mbrguard --p2-any-length: other {what} -> 1')
    check(run(g + [w('old.mbr'), F, '--p2-any-length']).returncode == 1, 'mbrguard --p2-any-length: single-layout card -> 1')
    check(run(g + [w('old.mbr'), w('old.mbr'), '--p2-any-length']).returncode == 2,
          'mbrguard --p2-any-length on a single-layout image -> 2')

    have_e2 = all(os.access(x, os.X_OK) for x in (mkcard.MKE2FS, mkcard.E2FSCK, mkcard.RESIZE2FS, mkcard.TUNE2FS,
                                                   mkcard.DUMPE2FS))
    debugfs = os.path.join(os.path.dirname(mkcard.E2FSCK), 'debugfs')
    if not have_e2:
        skip(f'card builds and ext4 checks: e2fsprogs not found in {mkcard.E2FS_SBIN}')
        return finish(work)

    # --- a small rootfs (made like mkcard's empty p1) with one file
    small = w('small.ext4')
    mkcard.make_ext4(small, 160 << 20)
    open(w('hello.txt'), 'wb').write(HELLO)
    run([debugfs, '-w', '-R', f"write {w('hello.txt')} hello.txt", small], env=mkcard.e2env())
    small_sha = mkcard.file_sha(small)

    # --- data layout twice
    ra, rb = mk('dA', '--data-partition', '--rootfs-img', small), mk('dB', '--data-partition', '--rootfs-img', small)
    if not check(ra.returncode == 0 and rb.returncode == 0, 'mkcard --data-partition --rootfs-img x2 builds'):
        print(ra.stderr, rb.stderr)
        return finish(work)
    A, B = w('dA/sdcard.img'), w('dB/sdcard.img')
    check(run(['cmp', A, B]).returncode == 0, 'reproducible: data-layout sdcard.img byte-identical across two builds')
    check(mkcard.file_sha(small) == small_sha, '--rootfs-img input left unchanged')
    m = json.load(open(w('dA/manifest.json')))
    with open(A, 'rb') as f:
        sec0 = f.read(512)
    ents = [struct.unpack_from('<B3xII', sec0, 446 + 16 * i + 4)[0:3] for i in range(4)]
    check(ents == [(0x83, P1_LBA, P1_SECTORS), (0x0C, P2_LBA, P2_SECTORS), (0, 0, 0), (0, 0, 0)],
          f'MBR entries {ents[:2]}')
    check(sec0[510:512] == b'\x55\xaa' and sec0[440:444] == b'RC2S' and sec0[446] == 0 and sec0[462] == 0,
          'MBR: 55 AA, disk signature RC2S, no boot flags')
    check(P2_LBA + P2_SECTORS == mkcard.DEFAULT_CARD_SECTORS and P2_LBA % 8192 == 0,
          'p2 placeholder ends at the 2 GB card end, 4 MiB aligned')
    check(m['layout'] == 'data' and m['mbr']['table_hex'] == sec0[446:510].hex(), 'manifest: layout data, mbr.table_hex')
    check(m['card_bytes'] is None and m['image_bytes'] == ROOTFS_AREA == os.path.getsize(A),
          'manifest: card_bytes null (set at write time), image_bytes 335544320 = sdcard.img size')
    h = mkcard.range_shas(A, dict(boot=(0, P1_OFF), area=(0, ROOTFS_AREA), p1=(P1_OFF, ROOTFS_AREA)))
    check(m['rootfs_area_bytes'] == ROOTFS_AREA == 335544320 and m['rootfs_area_sha256'] == h['area']
          == m['sdcard_img_sha256'], 'manifest: rootfs_area = the whole image (first 335544320 B), sha256 recomputed')
    check(m['boot_area_sha256'] == h['boot'], 'manifest: boot_area_sha256 recomputed')
    mp = {p['index']: p for p in m['partitions']}
    check(mp[1]['sha256'] == h['p1'] and mp[2]['sha256'] is None and mp[2]['format_on_write'] is True and
          (mp[1]['lba'], mp[1]['sectors'], mp[1]['type'], mp[1]['label']) == (P1_LBA, P1_SECTORS, '0x83', 'rc2root') and
          (mp[2]['lba'], mp[2]['sectors'], mp[2]['type'], mp[2]['label']) == (P2_LBA, P2_SECTORS, '0x0c', 'RC2DATA'),
          'manifest: partitions lba/sectors/type/label/sha256, p2 format_on_write')

    # --- p1
    p1 = w('p1.ext4')
    extract(A, P1_OFF, P1_BYTES, p1)
    sb = mkcard.ext4_super(p1)
    check(sb.get('Block count') == str(P1_BLOCKS) and sb.get('Filesystem volume name') == 'rc2root',
          f"p1: {sb.get('Block count')} blocks, label {sb.get('Filesystem volume name')}")
    r = run([mkcard.E2FSCK, '-fn', p1])
    check(r.returncode == 0, 'p1: e2fsck -fn clean' + ('' if r.returncode == 0 else '\n' + r.stdout + r.stderr))
    check(sb.get('Last checked') == 'Sat Oct 10 00:00:00 2026', f"p1: last checked {sb.get('Last checked')} UTC (tune2fs -T)")
    r = run([debugfs, '-R', 'cat hello.txt', p1])
    check(r.stdout.encode() == HELLO, 'p1: test file from the rootfs intact')

    # --- p2 for --data-img (fat32.py, mkdata.sh); the card's own p2 is formatted at write time (test_format_data.py)
    p2 = p2e
    fsck, mdir, mcopy = tool('fsck.fat'), tool('mdir'), tool('mcopy')
    env = dict(os.environ, MTOOLS_SKIP_CHECK='1')
    if fsck:
        r = run([fsck, '-n', p2])
        check(r.returncode == 0, f'p2: fsck.fat -n clean ({r.stdout.strip().splitlines()[-1]})')
    else:
        skip('fsck.fat -n: dosfstools not installed')
    filled = w('p2-filled.img')
    if mdir and mcopy:
        r = run([mdir, '-i', p2, '::/'], env=env)
        check(r.returncode == 0 and 'RC2DATA' in r.stdout and 'No files' in r.stdout and '5243-3244' in r.stdout,
              'p2: mdir shows label RC2DATA, serial 5243-3244, no files')
        shutil.copyfile(p2, filled)
        r1 = run([mcopy, '-i', filled, w('hello.txt'), '::/hello.txt'], env=env)
        r2 = run([mdir, '-i', filled, '::/'], env=env)
        mtype = tool('mtype')
        rt = subprocess.run([mtype, '-i', filled, '::/hello.txt'], capture_output=True, env=env) if mtype else None
        check(r1.returncode == 0 and 'hello' in r2.stdout and (rt is None or rt.stdout == HELLO),
              'p2: mcopy round trip (copy in, list' + (', read back with mtype)' if rt else ')'))
        if fsck:
            r = run([fsck, '-n', filled])
            check(r.returncode == 0, f'p2 after mcopy: fsck.fat -n clean ({r.stdout.strip().splitlines()[-1]})')
        r = run([sys.executable, '-I', os.path.join(HERE, 'check_fat32.py'), filled])
        check(r.returncode == 0, 'p2 after mcopy: check_fat32.py (non-empty)' + ('' if r.returncode == 0 else r.stdout))
    else:
        skip('mdir/mcopy round trip: mtools not installed')

    # --- --data-img --card-bytes 4 GiB with real partitions: consistent, p2 = the fat32.py image, rootfs area after the MBR
    r = mk('dG', '--data-partition', '--rootfs-img', small, '--data-img', p2g4, '--card-bytes', str(G4))
    bad = card_consistent(w('dG'), G4, 'data') if r.returncode == 0 else [r.stderr.strip()]
    if not bad:
        G = w('dG/sdcard.img')
        if sha_range(G, P2_OFF, G4 - P2_OFF) != mkcard.file_sha(p2g4):
            bad.append('p2 != the --data-img')
        if sha_range(G, 512, ROOTFS_AREA - 512) != sha_range(A, 512, ROOTFS_AREA - 512):
            bad.append('rootfs area after the MBR differs from the format-on-write image')
    check(not bad, '--data-img --card-bytes 4 GiB with partitions: consistent, p2 = the FAT32 image, rootfs area = dA'
          + (f' (bad: {bad})' if bad else ''))

    # --- --data-img
    r = mk('dC', '--data-partition', '--rootfs-img', small, '--data-img', p2)
    C = w('dC/sdcard.img')
    check(r.returncode == 0 and os.path.getsize(C) == mkcard.DEFAULT_CARD_BYTES
          and sha_range(C, 0, ROOTFS_AREA) == mkcard.file_sha(A) and sha_range(C, P2_OFF, P2_BYTES) == mkcard.file_sha(p2),
          '--data-img with the empty p2: full 2 GB image = the format-on-write image + the fat32.py p2')
    if os.path.exists(filled):
        r = mk('dC', '--data-partition', '--rootfs-img', small, '--data-img', filled)
        C = w('dC/sdcard.img')
        mc = json.load(open(w('dC/manifest.json'))) if r.returncode == 0 else {}
        check(r.returncode == 0 and sha_range(C, P2_OFF, P2_BYTES) == mkcard.file_sha(filled)
              and mc['partitions'][1]['sha256'] == mkcard.file_sha(filled)
              and mc['rootfs_area_sha256'] == m['rootfs_area_sha256'],
              '--data-img filled: p2 = the image, rootfs area unchanged')
    bad = w('bad.img')
    with open(bad, 'wb') as f:
        f.truncate(P2_BYTES - 512)
    refused(mk('dX', '--data-partition', '--data-img', bad), '--data-img of the wrong size')
    shutil.copyfile(p2e, bad)
    with open(bad, 'r+b') as f:
        f.seek(71)
        f.write(b'NO NAME    ')
    refused(mk('dX', '--data-partition', '--data-img', bad), '--data-img with another label')
    with open(bad, 'r+b') as f:
        f.seek(71)
        f.write(b'RC2DATA    ')
        f.seek(82)
        f.write(b'FAT16   ')
    refused(mk('dX', '--data-partition', '--data-img', bad), '--data-img that is not FAT32')
    refused(mk('dX', '--data-img', p2e), '--data-img without --data-partition')

    # --- rootfs refusals and the shrink path
    other = w('other.ext4')
    shutil.copyfile(small, other)
    run([os.path.join(os.path.dirname(mkcard.E2FSCK), 'e2label'), other, 'otherfs'])
    refused(mk('dX', '--data-partition', '--rootfs-img', other), '--rootfs-img labelled otherfs')
    refused(mk('dX', '--data-partition', '--rootfs-img', p2e), '--rootfs-img that is not ext4')
    big = w('big.ext4')
    mkcard.make_ext4(big, 700 << 20)
    run([debugfs, '-w', '-R', f"write {w('hello.txt')} hello.txt", big], env=mkcard.e2env())
    r = mk('dX', '--data-partition', '--rootfs-img', big)
    ok = r.returncode == 0
    if ok:
        extract(w('dX/sdcard.img'), P1_OFF, P1_BYTES, p1)
        sb = mkcard.ext4_super(p1)
        ok = sb.get('Block count') == str(P1_BLOCKS) and run([mkcard.E2FSCK, '-fn', p1]).returncode == 0 \
            and run([debugfs, '-R', 'cat hello.txt', p1]).stdout.encode() == HELLO
    check(ok, f'700 MiB rootfs with little data: shrunk to {P1_BLOCKS} blocks, e2fsck -fn clean, file intact'
          + ('' if r.returncode == 0 else '\n' + r.stderr))
    r = run([debugfs, '-w', '-R', 'write /dev/null fill', big])
    r = run([debugfs, '-w', '-R', 'fallocate fill 0 149999', big])
    used = int(mkcard.ext4_super(big)['Block count']) - int(mkcard.ext4_super(big)['Free blocks'])
    if used > P1_BLOCKS:
        refused(mk('dX', '--data-partition', '--rootfs-img', big), f'--rootfs-img with {used} used blocks > {P1_BLOCKS}')
    else:
        skip(f'too-full rootfs refusal: debugfs fallocate did not fill the test image ({used} blocks used)')

    # --- single layout (run.sh's card-m0) and write-card.sh refusals before any disk access
    if single:
        ms = json.load(open(os.path.join(single, 'manifest.json')))
        with open(os.path.join(single, 'sdcard.img'), 'rb') as f:
            s0 = f.read(512)
        check(ms['layout'] == 'single' and 'rootfs_area_sha256' not in ms and ms['mbr']['table_hex'] == old[446:510].hex()
              and s0[446:512] == old[446:512] and len(ms['partitions']) == 1
              and ms['partitions'][0]['sectors'] == mkcard.DEFAULT_CARD_SECTORS - P1_LBA,
              'single layout (default): one 0x83 partition to the card end, manifest without rootfs area')
        check(run(g + [os.path.join(single, 'sdcard.img'), A]).returncode == 1,
              'mbrguard: single-layout card.img vs data-layout image -> 1')
        wc = os.path.join(TOOL, 'write-card.sh')
        r = run(['bash', wc, 'NOT-A-DISK', single, '--rootfs'])
        check(r.returncode == 1 and 'needs a data-layout image' in r.stdout and 'target' not in r.stdout,
              'write-card.sh --rootfs on a single-layout card dir: refused before any disk access')
    else:
        skip('single-layout checks: no card dir given')
    r = run(['bash', os.path.join(TOOL, 'write-card.sh'), 'NOT-A-DISK', w('dA'), '--bogus'])
    check(r.returncode == 1 and 'unknown mode' in r.stdout, 'write-card.sh: unknown mode refused before any disk access')
    return finish(work)


def finish(work):
    for n in ('dA', 'dB', 'dC', 'dX', 'dG'):
        p = os.path.join(work, n, 'sdcard.img')
        if os.path.exists(p):
            os.remove(p)
    for n in ('p1.ext4', 'p2.img', 'p2-4g.img', 'head.bin', 'card.bin', 'p2-empty.img', 'p2-filled.img', 'bad.img', 'big.ext4', 'small.ext4', 'other.ext4'):
        p = os.path.join(work, n)
        if os.path.exists(p):
            os.remove(p)
    print(f'RESULT {"FAIL" if fails else "PASS"} card layout: {fails} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
