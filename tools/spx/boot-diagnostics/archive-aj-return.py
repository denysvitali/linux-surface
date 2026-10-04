#!/usr/bin/python3
"""Freeze AJ's failed attachment boot and independently verify its userspace return."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
RUN = BASE / 'attempts/20260930aj'
TRIAL = '66c4697f-70f5-4b02-bc76-da46c97afdfd'
RECOVERY = 'd3b9f9b1-7e95-4963-8225-adf840755102'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}

def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=90)

assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == RECOVERY
assert cmd('uname', '-r').strip() == '6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
a = json.loads((RUN / 'attempt.json').read_text())
assert a == json.loads((BASE / 'attempt.json').read_text())
for name, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
    assert sha(name) == digest, name
for directory in ('final-result', 'boot-transition-review', 'post-result-records'):
    root = RUN / directory
    expected = json.loads((root / 'sha256.json').read_text())
    assert files(root) == expected | {'sha256.json': sha(root / 'sha256.json')}
result = json.loads((RUN / 'final-result/result.json').read_text())
review = json.loads((RUN / 'independent-result-review.json').read_text())
assert result['boot_id'] == TRIAL and review['boot_id'] == TRIAL
assert result['spi_hid_ready'] and not review['scoped_passed']
assert review['scoped_failure_reasons'] == ['native bus/clock-stop path']
assert not result['native_force_off_path_passed'] and result['fd680_renderer'] and result['wifi_connected']
assert not json.loads((RUN / 'finalizer-action.json').read_text())['fallback_stopped']
env = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
efi = cmd('efibootmgr')
assert 'BootNext:' not in efi
trial_root = BASE / 'boots' / TRIAL
assert (trial_root / 'return-requested').read_text().strip() == TRIAL
assert 'next_entry=' in (trial_root / 'pre-return-grubenv').read_text().splitlines()
fallback = cmd('journalctl', '--boot=' + TRIAL.replace('-', ''), '-u',
               'spx-aj-fallback.service', '-o', 'short-monotonic', '--no-pager')
assert '900.' in fallback and 'Evidence saved' in fallback and 'Deactivated successfully' in fallback
out = RUN / 'recovery-return'
assert not out.exists()
subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'], check=True, timeout=90)
out.mkdir(mode=0o700)
for label, bid in (('trial', TRIAL), ('recovery', RECOVERY)):
    root = BASE / 'boots' / bid
    with (root / 'collect.lock').open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        shutil.copytree(root, out / (label + '-collector'), symlinks=True,
                        ignore=shutil.ignore_patterns('collect.lock'))
    for suffix, opts in (('kernel.log', ['-k', '-o', 'short-monotonic']),
                         ('journal.log', ['-o', 'short-monotonic']),
                         ('journal.export', ['-o', 'export'])):
        with (out / (label + '-' + suffix)).open('wb') as stream:
            subprocess.run(['journalctl', '--boot=' + bid.replace('-', ''), *opts, '--no-pager'],
                           stdout=stream, check=True, timeout=90)
(out / 'fallback.log').write_text(fallback)
(out / 'grubenv').write_text(env)
(out / 'efibootmgr').write_text(efi)
(out / 'cmdline').write_text(Path('/proc/cmdline').read_text())
shutil.copy2(__file__, out / 'archive-aj-return.py')
report = {'trial_boot_id': TRIAL, 'recovery_boot_id': RECOVERY,
          'recovery_release': cmd('uname', '-r').strip(),
          'userspace_fallback_return_verified': True,
          'efi_early_kernel_recovery_validated': False,
          'known_good_default': True, 'next_entry_empty': True, 'efi_bootnext_absent': True,
          'recovery_sha256': a['recovery_sha256'],
          'result_manifest_sha256': sha(RUN / 'final-result/sha256.json'),
          'touch_final_result_manifest_sha256': sha(RUN / 'final-result/sha256.json'),
          'native_result_passed': False, 'touch_ready_at_trial_snapshot': True,
          'playback_performed': False, 'live_rebind_performed': False}
(out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
hashes = files(out)
(out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
assert files(out) == hashes | {'sha256.json': sha(out / 'sha256.json')}
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == RECOVERY
os.sync()
print(json.dumps(report | {'files_verified': len(hashes), 'manifest_sha256': sha(out / 'sha256.json')}, indent=2))
