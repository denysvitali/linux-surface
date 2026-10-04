#!/usr/bin/python3
"""Install U's corrected DTB, one-shot entry, and guarded result collection."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
T = BASE / 'attempts/20260927t'
U = BASE / 'attempts/20260927u'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT = Path('/boot/spx-trial-20260927u')
BID = 'd8cc4fba-bbc0-455c-bd0f-2c9788d6d4f0'
RELEASE = '7.3.0-rc2-spx-mainline-20260927r+'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


def write(path, content, mode=0o600):
    with Path(path).open('x') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    Path(path).chmod(mode)


assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == '6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
assert not BOOT.exists() and not (U / 'deploy-started').exists()
assert not (U / 'attempt.json').exists() and not (U / 'entry.cfg').exists()
assert 'saved_entry=spx-known-good' in command('grub-editenv',
    '/boot/grub/grubenv', 'list').splitlines()
assert 'next_entry=' in command('grub-editenv',
    '/boot/grub/grubenv', 'list').splitlines()
assert 'BootNext:' not in command('efibootmgr')
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
assert Path('/boot/grub/custom.cfg').read_text() == (T / 'entry.cfg').read_text()
review = json.loads((T / 'independent-return-review.json').read_text())
assert review['current_boot_id'] == BID and review['recovery_hashes_verified'] == 3
prep = json.loads((U / 'preparation-review.json').read_text())
assert prep['boot_selected'] is False
assert sha(U / 'preparation-sha256.json') == prep['preparation_manifest_sha256']
manifest = json.loads((U / 'preparation-sha256.json').read_text())
for name, digest in manifest.items():
    assert sha(U / name) == digest, name
assert sha(U / 'dtb-build/spx.dtb') == prep['new_dtb_sha256']
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (
    U / 'dtb-build/source.diff').read_bytes()
parent = json.loads((T / 'attempt.json').read_text())
for name, digest in (parent['sha256'] | parent['recovery_sha256']).items():
    assert sha(name) == digest, name
modules = json.loads((U / 'reused-build/module-sha256.json').read_text())
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(Path('/usr/lib/modules') / RELEASE / name) == digest, name

old_entry = (T / 'entry.cfg').read_text()
assert old_entry.count('20260927t') >= 3
entry = old_entry.replace('20260927t', '20260927u')
entry = entry.replace('/spx-trial-20260927r/spx.dtb',
                      '/spx-trial-20260927u/spx.dtb')
entry = entry.replace('exact R artifacts; known-good default',
                      'corrected WSA DTB; known-good default')
cmdline = parent['cmdline'].replace('spx_attempt=20260927t',
                                    'spx_attempt=20260927u')
assert entry.count(' ' + cmdline + '; then') == 1
assert entry.count('devicetree /spx-trial-20260927u/spx.dtb') == 1
preview = U / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

source_finalizer = REPO / 'tools/spx/boot-diagnostics/u-finalize.py'
runtime = Path('/usr/local/lib/spx-boot-diagnostics/u-finalize.py')
assert source_finalizer.is_file() and not runtime.exists()
units = {
 'spx-u-finalize.service': '[Unit]\nDescription=Archive U SoundWire ID result at 620 seconds\nConditionKernelCommandLine=spx_attempt=20260927u\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/u-finalize.py\nTimeoutStartSec=180\n',
 'spx-u-finalize.timer': '[Unit]\nDescription=Automatically archive U result before fallback\nConditionKernelCommandLine=spx_attempt=20260927u\n\n[Timer]\nOnBootSec=620\nAccuracySec=1\nUnit=spx-u-finalize.service\n\n[Install]\nWantedBy=timers.target\n',
 'spx-u-fallback.service': '[Unit]\nDescription=Return U to known-good if attachment result fails\nConditionKernelCommandLine=spx_attempt=20260927u\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/return.sh\nTimeoutStartSec=90\n',
 'spx-u-fallback.timer': '[Unit]\nDescription=Bound U after its automatic result collector\nConditionKernelCommandLine=spx_attempt=20260927u\n\n[Timer]\nOnBootSec=900\nAccuracySec=1\nUnit=spx-u-fallback.service\n\n[Install]\nWantedBy=timers.target\n'}
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/94-u-exclude.conf')
assert not exclude.exists()

write(U / 'deploy-started', BID + '\n')
BOOT.mkdir(mode=0o700)
shutil.copy2(U / 'dtb-build/spx.dtb', BOOT / 'spx.dtb')
assert sha(BOOT / 'spx.dtb') == prep['new_dtb_sha256']
shutil.copy2('/boot/grub/custom.cfg', U / 'custom-before-u.cfg')
tmp = Path('/boot/grub/custom.cfg.u-new')
write(tmp, entry, 0o644)
os.replace(tmp, '/boot/grub/custom.cfg')
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True,
               timeout=30)
write(U / 'entry.cfg', entry)
shutil.copy2(source_finalizer, runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260927u\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-u-finalize.timer',
                'spx-u-fallback.timer'], check=True, timeout=30)
for name in ('spx-u-finalize.timer', 'spx-u-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'

runtime_files = [runtime, exclude,
                 Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
payloads = {str(Path('/boot/spx-trial-20260927r/vmlinuz')):
            sha('/boot/spx-trial-20260927r/vmlinuz'),
            str(Path('/boot/spx-trial-20260927r/initramfs.img')):
            sha('/boot/spx-trial-20260927r/initramfs.img'),
            str(BOOT / 'spx.dtb'): sha(BOOT / 'spx.dtb')}
assert payloads['/boot/spx-trial-20260927r/vmlinuz'] == parent['sha256'][
    '/boot/spx-trial-20260927r/vmlinuz']
assert payloads['/boot/spx-trial-20260927r/initramfs.img'] == parent['sha256'][
    '/boot/spx-trial-20260927r/initramfs.img']
assert payloads[str(BOOT / 'spx.dtb')] == prep['new_dtb_sha256']
attempt = {'attempt': '20260927u', 'entry': 'spx-trial-20260927u',
           'release': RELEASE, 'preboot_id': BID,
           'source_commit': prep['source_commit'],
           'source_diff': str(U / 'dtb-build/source.diff'),
           'build_archive': str(U / 'reused-build'),
           'dtb_build': str(U / 'dtb-build'),
           'state': 'prepared U; no boot selection',
           'sha256': payloads,
           'recovery_sha256': parent['recovery_sha256'],
           'runtime_sha256': {str(p): sha(p) for p in runtime_files},
           'authorization': parent['authorization'], 'cmdline': cmdline,
           'parent_attempt': '20260927t',
           'comparison': 'Exact R kernel/modules/initramfs; two DT WSA IDs corrected',
           'return_window_seconds': 600,
           'preparation_review_sha256': sha(U / 'preparation-review.json'),
           'prior_result_review_sha256': sha(T / 'independent-result-review.json'),
           'prior_return_review_sha256': sha(T / 'independent-return-review.json')}
write(U / 'attempt.json', json.dumps(attempt, indent=2) + '\n')
tmp = BASE / 'attempt-u.new.json'
write(tmp, json.dumps(attempt, indent=2) + '\n')
os.replace(tmp, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv',
    '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('U installed with corrected DTB; no boot selected')
