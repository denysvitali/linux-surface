#!/usr/bin/python3
"""Install silent AC native attachment entry and bounded timers, unselected."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
Y = BASE / 'attempts/20260930ab'
Z = BASE / 'attempts/20260930ac'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = '094a2a10-d6cd-4e86-ba50-dd99bff8c6dd'
RELEASE = '7.3.0-rc2-spx-mainline-20260930aa+'


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
assert 'spx_attempt=20260930ab' in Path('/proc/cmdline').read_text().split()
assert Path('/boot/grub/custom.cfg').read_text() == (Y / 'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
reuse = json.loads((Z / 'archive-review.json').read_text())
assert reuse['preboot_id'] == BID and not reuse['boot_selected']
assert sha(Z / 'build-sha256.json') == reuse['build_manifest_sha256']
assert sha(Z / 'dtb-sha256.json') == reuse['dtb_manifest_sha256']
for tree, mf in (('build', 'build-sha256.json'), ('dtb-build', 'dtb-sha256.json')):
    for name, digest in json.loads((Z / mf).read_text()).items():
        assert sha(Z / tree / name) == digest, name
for name, target in json.loads((Z / 'build-symlinks.json').read_text()).items():
    assert os.readlink(Z / 'build' / name) == target, name
for name, digest in json.loads((Z / 'build/module-sha256.json').read_text()).items():
    assert sha(Path('/usr/lib/modules') / RELEASE / name) == digest, name
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (Z / 'dtb-build/source.diff').read_bytes()
assert sha(REPO / '.config') == reuse['config_sha256']
parent_review = json.loads((Y / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']
assert command('systemctl', 'show', 'spx-ab-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
for name, digest in (prior['sha256'] | prior['recovery_sha256'] | prior['runtime_sha256']).items():
    assert sha(name) == digest, name

cmdline = prior['cmdline'].replace('spx_attempt=20260930ab', 'spx_attempt=20260930ac').replace('soundwire_qcom.spx_force_attach=1', 'soundwire_qcom.spx_force_attach=0')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930ac', 'soundwire_qcom.spx_force_attach=0'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930ab', 'soundwire_qcom.spx_force_attach=1'}
entry = (Y / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260930ab', '--id spx-trial-20260930ac')
entry = entry.replace('set spx_diag_attempt=20260930ab', 'set spx_diag_attempt=20260930ac')
entry = entry.replace('SPX bounded boot diagnostic 20260930ab', 'SPX bounded boot diagnostic 20260930ac')
entry = entry.replace('Authorized one-shot AB silent left identity matching trial', 'Authorized one-shot AC silent force-off native attachment trial')
assert entry.count('--id spx-trial-20260930ac') == 1
assert entry.count('soundwire_qcom.spx_force_attach=0') == 1
assert entry.count('devicetree /spx-trial-20260930ab/spx.dtb') == 1
assert entry.count('linux /spx-trial-20260930aa/vmlinuz') == 1
assert entry.count('initrd /spx-trial-20260930aa/initramfs.img') == 1
preview = Z / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

runtime = Path('/usr/local/lib/spx-boot-diagnostics/ac-finalize.py')
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/101-ac-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units = {}
for action, delay in (('finalize', 620), ('fallback', 900)):
    executable = str(runtime) if action == 'finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
    units[f'spx-ac-{action}.service'] = (
        f'[Unit]\nDescription=AC silent native attachment {action}\nConditionKernelCommandLine=spx_attempt=20260930ac\n'
        'After=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n'
        f'[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n')
    units[f'spx-ac-{action}.timer'] = (
        f'[Unit]\nDescription=AC {action} timer\nConditionKernelCommandLine=spx_attempt=20260930ac\n\n'
        f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ac-{action}.service\n\n'
        '[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
write(Z / 'deploy-started', BID + '\n')
shutil.copy2('/boot/grub/custom.cfg', Z / 'custom-before-ac.cfg')
temporary = Path('/boot/grub/custom.cfg.ac-new')
write(temporary, entry, 0o644)
os.replace(temporary, '/boot/grub/custom.cfg')
write(Z / 'entry.cfg', entry)
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/ac-reboot-check.py', Z / 'reboot-check.py')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/ac-finalize.py', runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930ac\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-ac-finalize.timer', 'spx-ac-fallback.timer'], check=True, timeout=30)
for name in ('spx-ac-finalize.timer', 'spx-ac-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'
runtime_files = [runtime, exclude, Z / 'reboot-check.py', Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
a = {'attempt': '20260930ac', 'entry': 'spx-trial-20260930ac', 'release': RELEASE,
     'preboot_id': BID, 'source_commit': prior['source_commit'],
     'source_diff': str(Z / 'build/source.diff'), 'build_archive': str(Z / 'build'),
     'state': 'prepared AC; no boot selection', 'sha256': prior['sha256'],
     'recovery_sha256': prior['recovery_sha256'], 'authorization': prior['authorization'],
     'runtime_sha256': {str(p): sha(p) for p in runtime_files},
     'cmdline': cmdline, 'parent_attempt': '20260930ab', 'return_window_seconds': 600,
     'comparison': 'Exact AB artifacts; force_attach 1 -> 0; no PCM or playback',
     'archive_review_sha256': sha(Z / 'archive-review.json'), 'playback_requested': False}
write(Z / 'attempt.json', json.dumps(a, indent=2) + '\n')
temporary = BASE / 'attempt-ac.new.json'
write(temporary, json.dumps(a, indent=2) + '\n')
os.replace(temporary, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('AC installed with exact AB payloads; no selection or playback scheduled')
