#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host test for write-card.sh's disk guards. Never writes, unmounts or reads a raw disk.

usage: python3 -I tests/check_write_guard.py [CARD_DIR]
  1. diskguard.py against saved `diskutil info|list -plist` fixtures (tests/fixtures/diskutil/: this Mac's internal SSD and
     a disk image, trimmed; hand-written USB card readers, the built-in SD reader, a USB SSD, a USB boot disk): the set of
     refused guards per case.
  2. macOS only: write-card.sh --check against the real diskutil (disk0 = internal SSD, a bogus id, a partition id, and
     with CARD_DIR also the image checks). PATH gets a `dd` that fails and a `diskutil` that only passes info/list
     through, so even a broken --check could not write or unmount anything.
"""
import os, platform, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
FIX = os.path.join(HERE, 'fixtures', 'diskutil')
CARD = 1977614336
GIB = 1 << 30
fails = 0


def check(ok, what):
    global fails
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        fails += 1


def guard(disk, image=CARD, fixtures=FIX, **env):
    e = {k: v for k, v in os.environ.items() if k not in ('RC2_CARD_BYTES', 'RC2_CARD_MAX_BYTES')}
    e.update(env)
    r = subprocess.run([sys.executable, '-I', os.path.join(TOOL, 'diskguard.py'), disk, '--image-bytes', str(image),
                        '--fixtures', fixtures], capture_output=True, text=True, env=e)
    refused = set(re.findall(r'^\s+REFUSE (\w+)', r.stdout, re.M))
    return r.returncode, refused, r.stdout


def case(what, disk, want_rc, want_refused, **kw):
    rc, refused, out = guard(disk, **kw)
    ok = rc == want_rc and refused == set(want_refused)
    check(ok, f'guard {what}: {disk} -> exit {rc}, refused {sorted(refused) or "nothing"}' + ('' if ok else '\n' + out))


def fixture_variant(td, name, drop=(), root=None):
    d = os.path.join(td, name)
    shutil.copytree(FIX, d)
    for n in drop:
        os.remove(os.path.join(d, n))
    if root:
        shutil.copyfile(os.path.join(FIX, root), os.path.join(d, 'info-root.plist'))
    return d


def fixtures():
    case('internal SSD (this Mac)', 'disk0', 1, ['internal', 'bus', 'removable', 'bootdisk', 'volumes', 'size'])
    case('partition id', 'disk0s1', 1, ['id'])
    case('unknown id', 'disk99', 1, ['id'])
    case('volume name instead of an id', 'Macintosh HD', 1, ['id'])
    case('sparse disk image with an APFS store, 161 GB', 'disk4', 1, ['bus', 'volumes', 'size'])
    case('2 GB card in a USB reader, RC2DATA mounted', 'disk6', 0, [])
    case('2 GB card, image 32 KiB bigger than the card', 'disk6', 1, ['size'], image=CARD + 32768)
    case('2 GB card, RC2_CARD_BYTES pin equal', 'disk6', 0, [], RC2_CARD_BYTES=str(CARD))
    case('2 GB card, RC2_CARD_BYTES pin 4 GiB', 'disk6', 1, ['size'], RC2_CARD_BYTES=str(4 * GIB))
    case('2 GB card, RC2_CARD_MAX_BYTES 1 GiB', 'disk6', 1, ['size'], RC2_CARD_MAX_BYTES=str(GIB))
    case('2 GB card, RC2_CARD_BYTES not a number', 'disk6', 1, ['env'], RC2_CARD_BYTES='2G')
    case('card in the built-in SD reader', 'disk7', 1, ['internal', 'bus'])
    case('USB SSD 500 GB (only the size cap stops it)', 'disk8', 1, ['size'])
    case('card with a volume mounted as Macintosh HD', 'disk9', 1, ['volumes'])
    case('APFS-formatted card (physical store)', 'disk10', 1, ['volumes'])
    case('32 GB FAT32 card, 2 GB image', 'disk12', 0, [])
    case('32 GB card, RC2_CARD_MAX_BYTES 16 GiB', 'disk12', 1, ['size'], RC2_CARD_MAX_BYTES=str(16 * GIB))
    case('USB SSD 500 GB with RC2_CARD_MAX_BYTES 1 TB (the override is the owner\'s call)', 'disk8', 0, [],
         RC2_CARD_MAX_BYTES=str(10 ** 12))
    case('32 GB card, image 0 (--check without a card dir)', 'disk12', 0, [], image=0)
    with tempfile.TemporaryDirectory() as td:
        case('Mac booted from the USB card (root store disk6s2)', 'disk6', 1, ['bootdisk'],
             fixtures=fixture_variant(td, 'usbboot', root='root-usbboot.plist'))
        case('diskutil list fails', 'disk12', 1, ['volumes'], fixtures=fixture_variant(td, 'nolist', drop=['list-disk12.plist']))
        case('diskutil info of a partition fails', 'disk6', 1, ['volumes'],
             fixtures=fixture_variant(td, 'nopart', drop=['info-disk6s2.plist']))
        case('diskutil info / fails', 'disk6', 1, ['bootdisk'], fixtures=fixture_variant(td, 'noroot', drop=['info-root.plist']))
    rc, _, out = guard('disk6')
    check(rc == 0 and "target /dev/disk6: 'SD Card Reader', 1977614336 bytes" in out and "protocol 'USB'" in out
          and 'GUARD OK' in out, 'guard prints MediaName, size, protocol and GUARD OK')


def real_check(card):
    if platform.system() != 'Darwin' or not shutil.which('diskutil'):
        print('SKIP write-card.sh --check on real disks: not macOS', flush=True)
        return
    real_du = shutil.which('diskutil')
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, 'dd'), 'w') as f:
            f.write('#!/bin/sh\necho "TRAP dd called: $*"\nexit 99\n')
        with open(os.path.join(td, 'diskutil'), 'w') as f:
            f.write('#!/bin/sh\ncase "$1" in info|list) exec "%s" "$@" ;; esac\necho "TRAP diskutil $*"\nexit 99\n' % real_du)
        for n in ('dd', 'diskutil'):
            os.chmod(os.path.join(td, n), 0o755)
        env = dict(os.environ, PATH=td + os.pathsep + os.environ.get('PATH', ''))
        env.pop('RC2_CARD_BYTES', None)
        env.pop('RC2_CARD_MAX_BYTES', None)
        wc = os.path.join(TOOL, 'write-card.sh')
        cases = [(['--check', 'disk0'], 'internal SSD disk0', r'REFUSE internal'),
                 (['--check', 'disk987'], 'bogus id disk987', r'diskutil does not know disk987'),
                 (['--check', 'disk0s1'], 'partition id disk0s1', r'not a whole-disk id'),
                 (['--check', '/'], 'path instead of an id', r'not a whole-disk id')]
        if card:
            cases.append((['--check', 'disk0', card], 'internal SSD disk0 with a card dir', r'REFUSE internal'))
            cases.append((['--check', 'disk0', card, '--boot-area'], 'disk0 --boot-area', r'REFUSE bootdisk'))
        for args, what, pat in cases:
            r = subprocess.run(['bash', wc, *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
            out = r.stdout + r.stderr
            ok = r.returncode == 1 and re.search(pat, out) and 'TRAP' not in out and 'CHECK OK' not in out
            check(bool(ok), f'write-card.sh {" ".join(args)}: refused ({what})' + ('' if ok else '\n' + out))


def main(argv):
    if len(argv) > 2:
        print(__doc__)
        return 2
    fixtures()
    real_check(argv[1] if len(argv) == 2 else None)
    print(f'RESULT {"FAIL" if fails else "PASS"} write guard: {fails} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
