#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""macOS host test for the data-layout write path (write-card.sh default mode) on DISK IMAGES only: p2 length set from the
disk size, patched MBR block written and read back, p2 formatted by formatdata.py (newfs_msdos), fsck_msdos -n, mounted.

usage: python3 -I tests/test_format_data.py WORKDIR
For a 2 GB (the test card's 1977614336 B) and a 32 GiB sparse file in WORKDIR: attach it without mounting (diskutil image
attach --noMount);
refuse to go on unless diskutil reports BusProtocol "Disk Image" for the attached disk (never a physical disk); then run the
same helper commands write-card.sh runs (mbrguard.py p2-for-disk / patch / sha / written, dd in 32 KiB blocks,
formatdata.py, fsck_msdos -n), mount p2 at WORKDIR/mnt (FAT32, label RC2DATA), check the boot sector against
fat32.format_geometry (32 KiB alignment, hidden 655360) from the backing file, and fsck.fat -n on the 2 GB p2 when
dosfstools is installed. Also: formatdata.py refuses a disk image with a single-layout MBR. The helpers run with
/usr/bin/python3 when present (what sudo write-card.sh uses). SKIP when not on macOS.
"""
import hashlib, os, platform, plistlib, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, TOOL)
import fat32, mkcard  # noqa: E402,E401

PY = '/usr/bin/python3' if os.access('/usr/bin/python3', os.X_OK) else sys.executable
BS = 32768
P2_LBA, P1_LBA, P1_SECTORS = 655360, 131072, 524288
IMAGE_BYTES = P2_LBA * 512
fails = 0


def check(ok, what):
    global fails
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        fails += 1
    return ok


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def helper(name, *args):
    return run([PY, '-I', os.path.join(TOOL, name), *args])


def attach(path):
    """Attach a raw disk image without mounting (diskutil image attach; hdiutil attach -nomount on older macOS) and
    return its disk id, refusing anything diskutil does not report as an external disk image."""
    r = run(['diskutil', 'image', 'attach', '--noMount', path])
    if r.returncode == 0 and r.stdout.startswith('/dev/disk'):
        ids = [r.stdout.split()[0].rsplit('/', 1)[1]]
    else:
        r = subprocess.run(['hdiutil', 'attach', '-nomount', '-plist', '-imagekey', 'diskimage-class=CRawDiskImage', path],
                           capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f'cannot attach {path}: {r.stderr.decode(errors="replace")}')
        ids = sorted({e['dev-entry'].rsplit('/', 1)[1] for e in plistlib.loads(r.stdout)['system-entities']})
        ids = [i for i in ids if re.match(r'^disk[0-9]+$', i)]
    if len(ids) != 1 or not re.match(r'^disk[0-9]+$', ids[0]):
        raise RuntimeError(f'attach {path}: {ids}')
    d = ids[0]
    info = plistlib.loads(subprocess.run(['diskutil', 'info', '-plist', d], capture_output=True, check=True).stdout)
    if info.get('BusProtocol') != 'Disk Image' or info.get('Internal') is not False:
        detach(d)
        raise RuntimeError(f'{d} is not a disk image ({info.get("BusProtocol")}): refusing')
    return d


def detach(d):
    subprocess.run(['diskutil', 'unmountDisk', d], capture_output=True)
    if subprocess.run(['diskutil', 'eject', d], capture_output=True).returncode:
        subprocess.run(['hdiutil', 'detach', '-force', d], capture_output=True)


def make_image(path):
    """A data-layout sdcard.img stand-in: the MBR with the placeholder p2 length, a pattern in the boot area and p1."""
    with open(path, 'wb') as f:
        f.truncate(IMAGE_BYTES)
        f.write(mkcard.mbr([(0x83, P1_LBA, P1_SECTORS), (0x0C, P2_LBA, mkcard.DEFAULT_P2_SECTORS)]))
        for off in (64 * 512, P1_LBA * 512, IMAGE_BYTES - BS):
            f.seek(off)
            f.write(hashlib.sha256(str(off).encode()).digest() * 1024)


def dd(*args):
    r = run(['dd', *args])
    if r.returncode:
        raise RuntimeError(f'dd {args}: {r.stderr}')


def one(work, img, disk_bytes):
    what = f'{disk_bytes} B disk image'
    backing = os.path.join(work, f'card-{disk_bytes}.img')
    with open(backing, 'wb') as f:
        f.truncate(disk_bytes)
    d = attach(backing)
    try:
        raw = f'/dev/r{d}'
        r = helper('mbrguard.py', 'p2-for-disk', str(disk_bytes))
        p2 = int(r.stdout.strip())
        check(p2 == disk_bytes // BS * BS // 512 - P2_LBA, f'{what}: p2 = {p2} sectors')
        head = os.path.join(work, 'head.bin')
        check(helper('mbrguard.py', 'patch', img, head, str(p2)).returncode == 0, f'{what}: patched MBR block')
        want = helper('mbrguard.py', 'sha', img, head, str(IMAGE_BYTES)).stdout.strip()
        n = IMAGE_BYTES // BS
        dd(f'if={img}', f'of={raw}', f'bs={BS}', 'skip=1', 'seek=1', f'count={n - 1}', 'conv=notrunc')
        dd(f'if={head}', f'of={raw}', f'bs={BS}', 'count=1', 'conv=notrunc')  # MBR last, as write-card.sh
        h = hashlib.sha256()
        with open(raw, 'rb') as f:
            for _ in range(n):
                h.update(f.read(BS))
        check(h.hexdigest() == want, f'{what}: readback of the first {IMAGE_BYTES} B = image with the patched MBR')
        card_head = os.path.join(work, 'card-head.bin')
        dd(f'if={raw}', f'of={card_head}', f'bs={BS}', 'count=1')
        check(helper('mbrguard.py', 'written', card_head, img, str(p2)).returncode == 0,
              f'{what}: mbrguard written (only bytes 474..477 differ)')
        r = helper('mbrguard.py', card_head, img, '--p2-any-length')
        check(r.returncode == 0, f'{what}: mbrguard --p2-any-length (a later --rootfs/--boot-area would pass)')
        r = helper('formatdata.py', d)
        check(r.returncode == 0 and 'boot sector checked' in r.stdout,
              f'{what}: formatdata.py' + ('' if r.returncode == 0 else '\n' + r.stdout + r.stderr))
        part = run(['diskutil', 'info', '-plist', f'{d}s2'])
        pi = plistlib.loads(part.stdout.encode()) if part.returncode == 0 else {}
        check(pi.get('TotalSize') == p2 * 512, f'{what}: macOS sees {d}s2 with the new length ({pi.get("TotalSize")} B)')
        r = run(['fsck_msdos', '-n', f'/dev/r{d}s2'])
        check(r.returncode == 0, f'{what}: fsck_msdos -n clean' + ('' if r.returncode == 0 else '\n' + r.stdout + r.stderr))
        mnt = os.path.join(work, 'mnt')
        os.makedirs(mnt, exist_ok=True)
        r = run(['diskutil', 'mount', '-mountPoint', mnt, f'{d}s2'])
        pi = plistlib.loads(run(['diskutil', 'info', '-plist', f'{d}s2']).stdout.encode())
        check(r.returncode == 0 and pi.get('VolumeName') == 'RC2DATA' and 'FAT32' in (pi.get('FilesystemName') or ''),
              f"{what}: mounts as {pi.get('FilesystemName')!r}, label {pi.get('VolumeName')!r}")
        subprocess.run(['diskutil', 'unmount', f'{d}s2'], capture_output=True)
    finally:
        detach(d)
    with open(backing, 'rb') as f:
        f.seek(P2_LBA * 512)
        bs = f.read(512)
    g = fat32.format_geometry(p2)
    bad = fat32.check_format(bs, p2, P2_LBA, g)
    check(not bad, f"{what}: boot sector from the backing file: {g['spc'] // 2} KiB clusters, FATs and data 32 KiB "
          f"aligned, hidden {P2_LBA}" + (f' (bad: {bad})' if bad else ''))
    fsck = shutil.which('fsck.fat') or next((p for p in ('/opt/homebrew/sbin/fsck.fat',) if os.access(p, os.X_OK)), None)
    if disk_bytes <= 4 << 30 and fsck:
        p2img = os.path.join(work, 'p2.img')
        with open(backing, 'rb') as s, open(p2img, 'wb') as t:
            t.truncate(p2 * 512)
            s.seek(P2_LBA * 512)
            left = p2 * 512
            while left:
                b = s.read(min(left, 1 << 22))
                if b.count(0) != len(b):
                    t.seek(p2 * 512 - left)
                    t.write(b)
                left -= len(b)
        r = run([fsck, '-n', p2img])
        check(r.returncode == 0, f'{what}: fsck.fat -n (dosfstools, the Linux checker) clean')
        os.remove(p2img)
    elif disk_bytes <= 4 << 30:
        print('SKIP fsck.fat -n: dosfstools not installed', flush=True)
    os.remove(backing)


def refuse_single(work):
    backing = os.path.join(work, 'single.img')
    with open(backing, 'wb') as f:
        f.truncate(1 << 30)
        f.write(mkcard.mbr([(0x83, P1_LBA, (1 << 30) // 512 - P1_LBA)]))
    d = attach(backing)
    try:
        r = helper('formatdata.py', d)
        check(r.returncode == 1 and 'REFUSE' in r.stdout and 'not the data partition' in r.stdout,
              'formatdata.py refuses a single-layout disk (no p2 at LBA 655360)')
        r = helper('formatdata.py', f'{d}s1')
        check(r.returncode == 1, 'formatdata.py refuses a partition id')
    finally:
        detach(d)
    os.remove(backing)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    if platform.system() != 'Darwin' or not shutil.which('newfs_msdos') or not shutil.which('diskutil'):
        print('SKIP format-on-write test: needs macOS (diskutil, newfs_msdos)')
        print('RESULT PASS format data: 0 failures (skipped)')
        return 0
    work = os.path.abspath(argv[1])
    os.makedirs(work, exist_ok=True)
    img = os.path.join(work, 'sdcard.img')
    make_image(img)
    print(f'helpers run with {PY}', flush=True)
    for disk_bytes in (mkcard.DEFAULT_CARD_BYTES, 32 << 30):
        try:
            one(work, img, disk_bytes)
        except (RuntimeError, ValueError, OSError) as e:
            check(False, f'{disk_bytes} B disk image: {e}')
    try:
        refuse_single(work)
    except (RuntimeError, OSError) as e:
        check(False, f'single-layout refusal: {e}')
    os.remove(img)
    print(f'RESULT {"FAIL" if fails else "PASS"} format data: {fails} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
