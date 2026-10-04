#!/usr/bin/python3
"""Independently verify W's installation and preserve known-good preboot state."""

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
W = BASE / 'attempts/20260927w'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = 'b9a390b7-fb58-40bc-8ae2-8404ee9e88d2'
RELEASE = '7.3.0-rc2-spx-mainline-20260927w+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def links(root):
    return {str(p.relative_to(root)): os.readlink(p)
            for p in sorted(root.rglob('*')) if p.is_symlink()}


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
assert not (W / 'installed-review.json').exists()
a = json.loads((W / 'attempt.json').read_text())
assert a == json.loads((BASE / 'attempt.json').read_text())
assert a['state'] == 'prepared W; no boot selection'
assert Path('/boot/grub/custom.cfg').read_text() == (W / 'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
for name, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
    assert sha(name) == digest, name
manifest = json.loads((W / 'build-sha256.json').read_text())
symlinks = json.loads((W / 'build-symlinks.json').read_text())
assert len(manifest) == 953 and len(symlinks) == 272
assert files(W / 'build') == manifest and links(W / 'build') == symlinks
modules = json.loads((W / 'build/module-sha256.json').read_text())
installed = Path('/usr/lib/modules') / RELEASE
source_modules = W / 'build/module-root/lib/modules' / RELEASE
assert len(modules) == 202 and files(installed) == modules
assert links(installed) == links(source_modules)
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == \
    (W / 'build/source.diff').read_bytes()
assert all(command('systemctl', 'is-enabled', unit) == 'enabled' and
           command('systemctl', 'show', unit, '-p', 'ActiveState', '--value') != 'active'
           for unit in ('spx-w-finalize.timer', 'spx-w-fallback.timer'))
subprocess.run(['grub-script-check', '/boot/grub/grub.cfg'], check=True, timeout=30)
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)

subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'], check=True,
               timeout=90)
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
snapshot = W / 'preboot-snapshot'
snapshot.mkdir(mode=0o700)
(snapshot / 'boot-id').write_text(BID + '\n')
(snapshot / 'uname').write_text(command('uname', '-r') + '\n')
(snapshot / 'cmdline').write_text(Path('/proc/cmdline').read_text())
(snapshot / 'grubenv').write_text('\n'.join(env) + '\n')
(snapshot / 'efibootmgr').write_text(command('efibootmgr') + '\n')
collector = BASE / 'boots' / BID
with (collector / 'collect.lock').open() as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    shutil.copytree(collector, snapshot / 'collector', symlinks=True,
                    ignore=shutil.ignore_patterns('collect.lock'))
snapshot_hashes = files(snapshot)
(snapshot / 'sha256.json').write_text(json.dumps(snapshot_hashes, indent=2) + '\n')
assert files(snapshot) == snapshot_hashes | \
    {'sha256.json': sha(snapshot / 'sha256.json')}
for name, digest in snapshot_hashes.items():
    assert sha(snapshot / name) == digest, name

scripts = W / 'deployment-sources'
scripts.mkdir(mode=0o700)
script_names = ('retire-r-for-w.py', 'deploy-w.py', 'review-w-install.py',
                'w-finalize.py', 'queue-w-once.py', 'w-reboot-check.py')
for name in script_names:
    src = REPO / 'tools/spx/boot-diagnostics' / name
    assert src.is_file(), name
    shutil.copy2(src, scripts / name)
script_hashes = files(scripts)
(W / 'deployment-sources-sha256.json').write_text(json.dumps(script_hashes, indent=2) + '\n')

report = {'attempt': '20260927w', 'preboot_id': BID,
          'payload_recovery_runtime_hashes_verified': sum(len(x) for x in
              (a['sha256'], a['recovery_sha256'], a['runtime_sha256'])),
          'build_files_verified': len(manifest),
          'build_symlinks_verified': len(symlinks),
          'modules_verified': len(modules),
          'preboot_snapshot_files_verified': len(snapshot_hashes),
          'preboot_snapshot_manifest_sha256': sha(snapshot / 'sha256.json'),
          'deployment_source_files_verified': len(script_hashes),
          'deployment_source_manifest_sha256': sha(W / 'deployment-sources-sha256.json'),
          'known_good_default': True, 'next_entry_empty': True,
          'efi_bootnext_absent': True, 'w_timers_enabled_inactive': True,
          'boot_selected': False}
(W / 'installed-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
