#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""write-card.sh helper: may this disk be overwritten with a card image? macOS only (diskutil). Reads, never writes.

usage: diskguard.py DISK [--image-bytes N] [--fixtures DIR] [--print-size]
  DISK           whole-disk id, e.g. disk7 (^disk[0-9]+$)
  --image-bytes  the image that would be written (0 = no image: only the disk guards)
  --fixtures     tests: read `diskutil info -plist X` from DIR/info-X.plist (X = / -> info-root.plist) and
                 `diskutil list -plist X` from DIR/list-X.plist instead of running diskutil
  --print-size   only print the disk's TotalSize in bytes (no guards)
Environment: RC2_CARD_MAX_BYTES (default 32 GiB) raises the size cap for bigger cards; RC2_CARD_BYTES pins the exact disk
size (e.g. 1977614336 for the 2 GB test card).

Guards (all of them are evaluated and printed; any failure -> REFUSE):
  id         DISK matches ^disk[0-9]+$, diskutil knows it and it is a WholeDisk
  internal   Internal == false
  bus        BusProtocol == "USB" (the Mac's built-in SD reader times out on raw I/O: use a USB card reader)
  removable  RemovableMedia or Ejectable is true
  bootdisk   not the ParentWholeDisk of / and not the whole disk of an APFSPhysicalStore of /
  volumes    no volume of the disk is mounted at /, under /System or /Volumes/Macintosh HD, and none is an APFS container or
             physical store
  size       image size <= disk size <= RC2_CARD_MAX_BYTES; disk size == RC2_CARD_BYTES when that is set
Prints one line per guard and the verdict. Exit 0 = OK, 1 = REFUSE, 2 = usage.
"""
import os, plistlib, re, subprocess, sys

DISK_RE = re.compile(r'^disk[0-9]+$')
MAX_DEFAULT = 32 << 30                   # SDHC ceiling, as mkcard.py --card-bytes (README "Card size")
BLOCKED_MOUNTS = ('/System', '/Volumes/Macintosh HD')
APFS_CONTENT = ('Apple_APFS', 'Apple_APFS_ISC', 'Apple_APFS_Recovery', 'Apple_APFS_Container',
                'EF57347C-0000-11AA-AA11-00306543ECAC')   # the last one: an APFS container (synthesized disk)


class Diskutil:
    """`diskutil info|list -plist X` as dicts; None when diskutil fails (unknown id) or the plist does not parse."""
    def __init__(self, fixtures=None):
        self.fixtures = fixtures

    def _load(self, verb, target):
        if self.fixtures:
            name = f"{verb}-{'root' if target == '/' else target}.plist"
            try:
                with open(os.path.join(self.fixtures, name), 'rb') as f:
                    return plistlib.load(f)
            except (OSError, plistlib.InvalidFileException, ValueError):
                return None
        try:
            r = subprocess.run(['diskutil', verb, '-plist', target], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        try:
            d = plistlib.loads(r.stdout)
        except (plistlib.InvalidFileException, ValueError):
            return None
        return d if isinstance(d, dict) and d else None

    def info(self, target):
        return self._load('info', target)

    def list(self, target):
        return self._load('list', target)


def whole(dev):
    """disk0s2 -> disk0; disk3s1s1 -> disk3."""
    m = re.match(r'^(disk[0-9]+)', dev or '')
    return m.group(1) if m else None


def env_int(name, default, out):
    v = os.environ.get(name, '')
    if not v:
        return default
    if not v.isdigit():
        out.append((False, 'env', f'{name}={v!r} is not a byte count'))
        return default
    return int(v)


def evaluate(disk, image_bytes, du):
    """[(ok, guard, text)] and a summary dict for the target line."""
    res, summary = [], {}

    def add(ok, guard, text):
        res.append((bool(ok), guard, text))

    if not DISK_RE.match(disk):
        add(False, 'id', f"'{disk}' is not a whole-disk id like disk7 (^disk[0-9]+$; partitions such as disk7s1 are refused)")
        return res, summary
    info = du.info(disk)
    if info is None:
        add(False, 'id', f'diskutil does not know {disk}')
        return res, summary
    size = info.get('TotalSize', info.get('Size'))
    summary = dict(media=info.get('MediaName', ''), size=size, bus=info.get('BusProtocol', ''),
                   node=info.get('DeviceNode', f'/dev/{disk}'))
    add(info.get('WholeDisk') is True and info.get('DeviceIdentifier') == disk, 'id',
        f"{disk}: WholeDisk {info.get('WholeDisk')}, DeviceIdentifier {info.get('DeviceIdentifier')}")
    add(info.get('Internal') is False, 'internal', f"Internal {info.get('Internal')} (must be false)")
    add(info.get('BusProtocol') == 'USB', 'bus',
        f"BusProtocol {info.get('BusProtocol')!r} (must be 'USB'; the Mac's built-in SD reader times out on raw I/O, use a "
        'USB card reader)')
    add(info.get('RemovableMedia') is True or info.get('Ejectable') is True, 'removable',
        f"RemovableMedia {info.get('RemovableMedia')}, Ejectable {info.get('Ejectable')} (one must be true)")

    root = du.info('/')
    if root is None:
        add(False, 'bootdisk', 'diskutil info / failed: cannot tell the boot disk')
    else:
        boot = {whole(root.get('ParentWholeDisk')), whole(root.get('DeviceIdentifier'))}
        boot |= {whole(s.get('APFSPhysicalStore')) for s in root.get('APFSPhysicalStores') or [] if isinstance(s, dict)}
        boot.discard(None)
        add(disk not in boot, 'bootdisk', f"boot disk(s) of / {sorted(boot)}; {disk} must not be one of them")

    lst = du.list(disk)
    ids = [d for d in (lst or {}).get('AllDisks') or [] if isinstance(d, str)]
    if lst is None or disk not in ids:
        add(False, 'volumes', f'diskutil list {disk} failed: cannot see its volumes')
    else:
        bad = []
        for dev in ids:
            if whole(dev) != disk:
                bad.append(f'{dev} listed under {disk}')
                continue
            di = info if dev == disk else du.info(dev)
            if di is None:
                bad.append(f'diskutil info {dev} failed')
                continue
            mp = di.get('MountPoint') or ''
            if mp == '/' or any(mp == b or mp.startswith(b + '/') or (b.endswith(' HD') and mp.startswith(b))
                                for b in BLOCKED_MOUNTS):
                bad.append(f'{dev} is mounted at {mp}')
            if di.get('APFSContainerReference') or di.get('APFSPhysicalStores') or di.get('Content') in APFS_CONTENT:
                bad.append(f"{dev} is an APFS container or physical store (Content {di.get('Content')!r})")
        add(not bad, 'volumes', '; '.join(bad) if bad else
            f"{len(ids)} entries ({', '.join(ids)}): none at / or a system path, no APFS container/store")

    cap = env_int('RC2_CARD_MAX_BYTES', MAX_DEFAULT, res)
    pin = env_int('RC2_CARD_BYTES', None, res)
    if not isinstance(size, int):
        add(False, 'size', f'no TotalSize for {disk}')
    else:
        add(size >= image_bytes, 'size', f'disk {size} B >= image {image_bytes} B')
        add(size <= cap, 'size', f'disk {size} B <= {cap} B (RC2_CARD_MAX_BYTES raises the cap for a bigger card)')
        if pin is not None:
            add(size == pin, 'size', f'disk {size} B == RC2_CARD_BYTES {pin} B')
    return res, summary


def main(argv):
    args, image_bytes, fixtures, print_size = [], 0, None, False
    it = iter(argv[1:])
    for x in it:
        if x == '--image-bytes':
            v = next(it, '')
            if not v.isdigit():
                print('usage: --image-bytes N')
                return 2
            image_bytes = int(v)
        elif x == '--print-size':
            print_size = True
        elif x == '--fixtures':
            fixtures = next(it, None)
            if not fixtures:
                print('usage: --fixtures DIR')
                return 2
        elif x.startswith('-'):
            print(__doc__)
            return 2
        else:
            args.append(x)
    if len(args) != 1:
        print(__doc__)
        return 2
    disk = args[0]
    if print_size:   # write-card.sh: the disk size for the p2 length (after the guards passed)
        info = Diskutil(fixtures).info(disk) if DISK_RE.match(disk) else None
        size = (info or {}).get('TotalSize')
        if not isinstance(size, int):
            print(f'REFUSE: no size for {disk}')
            return 1
        print(size)
        return 0
    res, s = evaluate(disk, image_bytes, Diskutil(fixtures))
    if s:
        gb = s['size'] / 1e9 if isinstance(s['size'], int) else 0
        print(f"target {s['node']}: '{s['media']}', {s['size']} bytes ({gb:.2f} GB), protocol '{s['bus']}'")
    for ok, guard, text in res:
        print(f"  {'ok    ' if ok else 'REFUSE'} {guard:<9} {text}")
    if res and all(ok for ok, _, _ in res):
        print(f'GUARD OK: {disk} is an external removable USB disk, not the boot disk')
        return 0
    print(f'REFUSE: {disk} failed the disk guards above')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
