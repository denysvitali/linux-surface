#!/usr/bin/python3
"""Install silent Z GPIO entry and result/fallback timers; do not select it."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
Y = BASE / 'attempts/20260927y'
Z = BASE / 'attempts/20260930z'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = 'b5f0a540-3e81-4415-b08c-f869e01349a2'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


def write(path, value, mode=0o600):
    with Path(path).open('x') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    Path(path).chmod(mode)


assert os.geteuid() == 0 and not (Z / 'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == RELEASE
prior = json.loads((Y / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
assert 'spx_attempt=20260927y' in Path('/proc/cmdline').read_text().split()
assert Path('/boot/grub/custom.cfg').read_text() == (Y / 'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
reuse = json.loads((Z / 'reuse-review.json').read_text())
assert reuse['preboot_id'] == BID and not reuse['boot_selected']
assert sha(Z / 'build-sha256.json') == reuse['build_manifest_sha256']
for name, digest in json.loads((Z / 'build-sha256.json').read_text()).items():
    assert sha(Z / 'build' / name) == digest, name
for name, digest in json.loads((Z / 'preparation-sources-sha256.json').read_text()).items():
    assert sha(Z / 'preparation-sources' / name) == digest, name
for name, digest in (prior['sha256'] | prior['recovery_sha256']).items():
    assert sha(name) == digest, name

cmdline = prior['cmdline'].replace('spx_attempt=20260927y', 'spx_attempt=20260930z') + ' wcd934x.spx_wsa_en_pin=1'
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930z', 'wcd934x.spx_wsa_en_pin=1'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260927y'}
entry = (Y / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260927y', '--id spx-trial-20260930z')
entry = entry.replace('set spx_diag_attempt=20260927y', 'set spx_diag_attempt=20260930z')
entry = entry.replace('Authorized one-shot Y shadow-backed WSA control trial', 'Authorized one-shot Z silent SD_N pin 1 trial')
entry = entry.replace('SPX bounded boot diagnostic 20260927y', 'SPX bounded boot diagnostic 20260930z')
assert entry.count('--id spx-trial-20260930z') == 1
assert entry.count('wcd934x.spx_wsa_en_pin=1') == 1
assert entry.count('devicetree /spx-trial-20260927y/spx.dtb') == 1
preview = Z / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

runtime = Path('/usr/local/lib/spx-boot-diagnostics/z-finalize.py')
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/98-z-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units = {}
for action, delay in (('finalize', 620), ('fallback', 900)):
    executable = str(runtime) if action == 'finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
    units[f'spx-z-{action}.service'] = (
        f'[Unit]\nDescription=Z silent GPIO {action}\nConditionKernelCommandLine=spx_attempt=20260930z\n'
        'After=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n'
        f'[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n')
    units[f'spx-z-{action}.timer'] = (
        f'[Unit]\nDescription=Z {action} timer\nConditionKernelCommandLine=spx_attempt=20260930z\n\n'
        f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-z-{action}.service\n\n'
        '[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
write(Z / 'deploy-started', BID + '\n')
shutil.copy2('/boot/grub/custom.cfg', Z / 'custom-before-z.cfg')
temporary = Path('/boot/grub/custom.cfg.z-new')
write(temporary, entry, 0o644)
os.replace(temporary, '/boot/grub/custom.cfg')
write(Z / 'entry.cfg', entry)
shutil.copy2(Z / 'preparation-sources/z-reboot-check.py', Z / 'reboot-check.py')
shutil.copy2(Z / 'preparation-sources/z-finalize.py', runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930z\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-z-finalize.timer', 'spx-z-fallback.timer'], check=True, timeout=30)
for name in ('spx-z-finalize.timer', 'spx-z-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'
runtime_files = [runtime, exclude, Z / 'reboot-check.py', Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
a = {'attempt': '20260930z', 'entry': 'spx-trial-20260930z', 'release': RELEASE,
     'preboot_id': BID, 'source_commit': prior['source_commit'],
     'source_diff': str(Z / 'build/source.diff'), 'build_archive': str(Z / 'build'),
     'state': 'prepared Z; no boot selection', 'sha256': prior['sha256'],
     'recovery_sha256': prior['recovery_sha256'], 'authorization': prior['authorization'],
     'runtime_sha256': {str(p): sha(p) for p in runtime_files},
     'cmdline': cmdline, 'parent_attempt': '20260927y', 'return_window_seconds': 600,
     'comparison': 'Exact Y artifacts; boot-time pin 1 output-high; no playback',
     'reuse_review_sha256': sha(Z / 'reuse-review.json'), 'playback_requested': False}
write(Z / 'attempt.json', json.dumps(a, indent=2) + '\n')
temporary = BASE / 'attempt-z.new.json'
write(temporary, json.dumps(a, indent=2) + '\n')
os.replace(temporary, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('Z installed using exact Y payload paths; no boot selected and no playback scheduled')
