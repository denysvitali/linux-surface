#!/usr/bin/python3
"""Preserve the consumed Y/Z payload slot before making room for AA."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
W = BASE / '20260927y'
X = BASE / '20260930aa'
SLOT = Path('/boot/spx-trial-20260927y')
RETIRED = X / 'retired-boot-slots/20260927y'
BID = 'e0479717-1fe0-4a8f-a6ac-af198c4b703a'


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
assert not RETIRED.exists() and not (X / 'attempt.json').exists()
archive = json.loads((X / 'archive-review.json').read_text())
for name, digest in json.loads((X / 'build-sha256.json').read_text()).items():
    assert sha(X / 'build' / name) == digest, name
assert archive['dtb_exact_z'] and archive['embedded_config_exact']
for name, digest in json.loads((BASE / '20260930z/attempt.json').read_text())['recovery_sha256'].items():
    assert sha(Path(name)) == digest, name
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
(X / 'retired-y-sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
os.sync()
shutil.rmtree(SLOT)
assert not SLOT.exists()
assert {p.name: sha(p) for p in RETIRED.iterdir() if p.is_file()} == expected
os.sync()
print('Y/Z boot slot archived and rehashed; AA boot space freed')
