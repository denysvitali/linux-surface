#!/usr/bin/python3
"""Archive one inactive historical kernel backup to make room for distinct AE."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ae')
PARENT = RUN.parent / '20260930ad'
BID = '86c3ff68-09a9-480c-9288-be9443254378'
BACKUP = Path('/boot/vmlinuz-linux-surface.bak-20260610-220702')
OUT = RUN / 'retired-unused-backup'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=90)

assert os.geteuid() == 0 and not OUT.exists() and not (RUN / 'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()
assert cmd('uname', '-r').strip() == '7.3.0-rc2-spx-mainline-20260930aa+'
archive = json.loads((RUN / 'archive-review.json').read_text())
assert archive['preboot_id'] == BID and archive['embedded_config_exact'] and archive['dtb_exact_ab']
review = json.loads((RUN / 'independent-build-review.json').read_text())
assert review['build_manifest_sha256'] == archive['build_manifest_sha256']
assert review['functional_driver_policy_unchanged'] and review['dtb_exact_ab']
for name, digest in json.loads((RUN / 'build-sha256.json').read_text()).items():
    assert sha(RUN / 'build' / name) == digest, name
parent = json.loads((PARENT / 'attempt.json').read_text())
assert parent == json.loads(Path('/var/lib/spx-boot-diagnostics/attempt.json').read_text())
for name, digest in (parent['sha256'] | parent['recovery_sha256'] | parent['runtime_sha256']).items():
    assert sha(name) == digest, name
env = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
assert 'BootNext:' not in cmd('efibootmgr')
assert str(BACKUP) not in parent['sha256'] and str(BACKUP) not in parent['recovery_sha256']
configs = [Path('/boot/grub/grub.cfg'), Path('/boot/grub/custom.cfg')]
assert all(BACKUP.name not in p.read_text() for p in configs)
assert 'set default="spx-known-good"' in configs[0].read_text()
space = os.statvfs('/boot')
available = space.f_bavail * space.f_frsize
required = sum((RUN / 'build' / n).stat().st_size for n in ('vmlinuz', 'initramfs.img')) + 1048576
assert available < required, 'retirement is unnecessary'
assert BACKUP.is_file() and not BACKUP.is_symlink()
digest = sha(BACKUP)
size = BACKUP.stat().st_size
assert size + available > required
OUT.mkdir(mode=0o700)
shutil.copy2(BACKUP, OUT / BACKUP.name)
assert sha(OUT / BACKUP.name) == digest
for p in configs:
    shutil.copy2(p, OUT / p.name)
shutil.copy2(__file__, OUT / 'retire-unused-backup-for-ae.py')
report = {'preboot_id': BID, 'original_path': str(BACKUP), 'archive_path': str(OUT / BACKUP.name),
          'backup_sha256': digest, 'backup_size_bytes': size,
          'active_grub_configs_do_not_reference_backup': True,
          'active_trial_and_known_good_payloads_preserved': True,
          'available_before_bytes': available, 'required_ae_bytes_with_margin': required,
          'restore_instruction': 'Copy the verified archived file to original_path before using a historical GRUB configuration that references it.'}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
hashes = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
assert all(sha(OUT / name) == value for name, value in hashes.items())
os.sync()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert cmd('grub-editenv', '/boot/grub/grubenv', 'list') == env
assert sha(BACKUP) == digest
BACKUP.unlink()
assert sha(OUT / BACKUP.name) == digest and not BACKUP.exists()
for name, value in (parent['sha256'] | parent['recovery_sha256'] | parent['runtime_sha256']).items():
    assert sha(name) == value, name
space = os.statvfs('/boot')
assert space.f_bavail * space.f_frsize > required
os.sync()
print('Inactive historical kernel backup preserved and rehashed:', digest)
print('Active AA/AB trial and all known-good artifacts remain unchanged')
