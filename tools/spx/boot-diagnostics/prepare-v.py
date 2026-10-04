#!/usr/bin/python3
"""Archive exact U artifacts for the readless V boot; do not select it."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
U = BASE / '20260927u'
V = BASE / '20260927v'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = 'db7ee26c-fe9f-4106-bc22-e5454ba51f9e'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


assert os.geteuid() == 0 and not V.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260927r+'
assert 'spx_attempt=20260927u' in Path('/proc/cmdline').read_text().split()
review = json.loads((U / 'independent-result-review.json').read_text())
assert review['boot_id'] == BID and review['corrected_scoped_pass']
assert review['logical_attached_slaves'] == 1 and review['fallback_stopped']
assert sha(U / 'final-result/sha256.json') == review['result_manifest_sha256']
assert command('systemctl', 'show', 'spx-u-fallback.timer', '-p',
               'ActiveState', '--value') != 'active'
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
a = json.loads((U / 'attempt.json').read_text())
for name, digest in (a['sha256'] | a['recovery_sha256']).items():
    assert sha(name) == digest, name
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (
    U / 'dtb-build/source.diff').read_bytes()
build = json.loads((U / 'reused-build-sha256.json').read_text())
assert len(build) == 922
for name, digest in build.items():
    assert sha(U / 'reused-build' / name) == digest, name
prep = json.loads((U / 'preparation-sha256.json').read_text())
for name, digest in prep.items():
    assert sha(U / name) == digest, name

V.mkdir(mode=0o700)
shutil.copytree(U / 'reused-build', V / 'reused-build', symlinks=True)
shutil.copytree(U / 'dtb-build', V / 'dtb-build', symlinks=True)
shutil.copy2(U / 'reused-build-sha256.json', V / 'reused-build-sha256.json')
for name, digest in build.items():
    assert sha(V / 'reused-build' / name) == digest, name
for name in ('spx.dtb', 'config', 'source.diff', 'sc8180x-wcd9340.dtsi'):
    assert sha(V / 'dtb-build' / name) == sha(U / 'dtb-build' / name), name
modules = json.loads((V / 'reused-build/module-sha256.json').read_text())
root = Path('/usr/lib/modules') / a['release']
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(root / name) == digest, name
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/AUDIO-WSA-READLESS-20260927.md',
             V / 'plan.md')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/RESULT-20260927u.md',
             V / 'prior-result.md')
shutil.copy2(__file__, V / 'prepare.py')
report = {'attempt': '20260927v', 'boot_selected': False,
          'preboot_id': BID, 'release': a['release'],
          'reused_build_manifest_sha256': sha(V / 'reused-build-sha256.json'),
          'reused_build_files_verified': len(build),
          'dtb_sha256': sha(V / 'dtb-build/spx.dtb'),
          'module_files_verified': len(modules),
          'parent_payload_sha256': a['sha256'],
          'recovery_sha256': a['recovery_sha256'],
          'prior_result_review_sha256': sha(U / 'independent-result-review.json'),
          'plan_sha256': sha(V / 'plan.md'),
          'source_diff_sha256': sha(V / 'dtb-build/source.diff'),
          'comparison': 'exact U artifacts; boot-only readless WSA selector'}
(V / 'reuse-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
