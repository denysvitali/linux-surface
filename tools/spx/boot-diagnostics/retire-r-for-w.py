#!/usr/bin/python3
"""Preserve the consumed R boot slot before making room for W."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
V = BASE / '20260927v'
W = BASE / '20260927w'
SLOT = Path('/boot/spx-trial-20260927r')
RETIRED = W / 'retired-boot-slots/20260927r'
BID = 'b9a390b7-fb58-40bc-8ae2-8404ee9e88d2'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
assert subprocess.check_output(['uname', '-r'], text=True).strip() == '6.18.3-1-surface+'
assert not RETIRED.exists() and not (W / 'attempt.json').exists()
assert (W / 'independent-artifact-review.json').exists()
env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
v = json.loads((V / 'attempt.json').read_text())
expected = {
    'vmlinuz': v['sha256'][str(SLOT / 'vmlinuz')],
    'initramfs.img': v['sha256'][str(SLOT / 'initramfs.img')],
    'spx.dtb': '5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5',
}
assert {p.name: sha(p) for p in SLOT.iterdir() if p.is_file()} == expected
RETIRED.parent.mkdir(mode=0o700)
shutil.copytree(SLOT, RETIRED)
assert {p.name: sha(p) for p in RETIRED.iterdir() if p.is_file()} == expected
(W / 'retired-r-sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
os.sync()
shutil.rmtree(SLOT)
assert not SLOT.exists()
assert {p.name: sha(p) for p in RETIRED.iterdir() if p.is_file()} == expected
os.sync()
print('R boot slot archived and rehashed; W boot space freed')
