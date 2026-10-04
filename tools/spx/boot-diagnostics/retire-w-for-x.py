#!/usr/bin/python3
"""Preserve the consumed W boot slot before making room for X."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
W = BASE / '20260927w'
X = BASE / '20260927x'
SLOT = Path('/boot/spx-trial-20260927w')
RETIRED = X / 'retired-boot-slots/20260927w'
BID = 'e6989b7a-9ee5-4138-939d-84f8f73f53d5'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_attempt=20260927w' in Path('/proc/cmdline').read_text().split()
assert subprocess.check_output(['uname', '-r'], text=True).strip() == '7.3.0-rc2-spx-mainline-20260927w+'
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
(X / 'retired-w-sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
os.sync()
shutil.rmtree(SLOT)
assert not SLOT.exists()
assert {p.name: sha(p) for p in RETIRED.iterdir() if p.is_file()} == expected
os.sync()
print('W boot slot archived and rehashed; X boot space freed')
