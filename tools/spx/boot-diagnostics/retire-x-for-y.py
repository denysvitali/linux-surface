#!/usr/bin/python3
"""Preserve the consumed X boot slot before making room for Y."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
W = BASE / '20260927x'
X = BASE / '20260927y'
SLOT = Path('/boot/spx-trial-20260927x')
RETIRED = X / 'retired-boot-slots/20260927x'
BID = 'f5039e57-1a71-4833-9193-6da333d4d4f9'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_attempt=20260927x' in Path('/proc/cmdline').read_text().split()
assert subprocess.check_output(['uname', '-r'], text=True).strip() == '7.3.0-rc2-spx-mainline-20260927x+'
assert not RETIRED.exists() and not (X / 'attempt.json').exists()
assert (X / 'independent-artifact-review.json').exists()
env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
w = json.loads((W / 'attempt.json').read_text())
expected = {
    'vmlinuz': w['sha256'][str(SLOT / 'vmlinuz')],
    'initramfs.img': w['sha256'][str(SLOT / 'initramfs.img')],
    'spx.dtb': w['sha256'][str(SLOT / 'spx.dtb')],
}
assert {p.name: sha(p) for p in SLOT.iterdir() if p.is_file()} == expected
RETIRED.parent.mkdir(mode=0o700)
shutil.copytree(SLOT, RETIRED)
assert {p.name: sha(p) for p in RETIRED.iterdir() if p.is_file()} == expected
(X / 'retired-x-sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
os.sync()
shutil.rmtree(SLOT)
assert not SLOT.exists()
assert {p.name: sha(p) for p in RETIRED.iterdir() if p.is_file()} == expected
os.sync()
print('X boot slot archived and rehashed; Y boot space freed')
