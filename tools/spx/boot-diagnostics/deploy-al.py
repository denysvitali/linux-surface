#!/usr/bin/python3
"""Install AL silent corrected-topology pin1 control entry and timers, unselected."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS']='0'
BASE = Path('/var/lib/spx-boot-diagnostics')
Y = BASE / 'attempts/20260930ak'
Z = BASE / 'attempts/20260930al'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = 'db98e8ac-8aa3-44d4-8899-47c4fab5fb07'
RELEASE = '7.3.0-rc2-spx-mainline-20260930ak+'


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
assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260930ak+'
prior = json.loads((Y / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
assert 'spx_attempt=20260930ak' in Path('/proc/cmdline').read_text().split()
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
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (Z / 'build/source.diff').read_bytes()
assert sha(REPO / '.config') == reuse['config_sha256']
parent_review = json.loads((Y / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']
assert not parent_review['scoped_failure_reasons'] and parent_review['firmware_identity_match_passed']
assert sha(Y / 'independent-result-review.json') == reuse['parent_result_review_sha256']
assert sha(Y / 'touch-startup-review.json') == reuse['parent_touch_review_sha256']
assert sha(Y / 'enumeration-word-review.json') == reuse['parent_enumeration_word_review_sha256']
assert sha(Y / 'final-result/sha256.json') == reuse['parent_result_manifest_sha256']
for name, digest in json.loads((Y / 'final-result/sha256.json').read_text()).items():
    assert sha(Y / 'final-result' / name) == digest, name
assert command('systemctl', 'show', 'spx-ak-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
for name, digest in (prior['sha256'] | prior['recovery_sha256'] | prior['runtime_sha256']).items():
    assert sha(name) == digest, name

cmdline = prior['cmdline'].replace('spx_attempt=20260930ak', 'spx_attempt=20260930al').replace('wcd934x.spx_wsa_en_pin=2', 'wcd934x.spx_wsa_en_pin=1')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930al', 'wcd934x.spx_wsa_en_pin=1'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930ak', 'wcd934x.spx_wsa_en_pin=2'}
entry = (Y / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260930ak', '--id spx-trial-20260930al')
entry = entry.replace('set spx_diag_attempt=20260930ak', 'set spx_diag_attempt=20260930al')
entry = entry.replace('SPX bounded boot diagnostic 20260930ak', 'SPX bounded boot diagnostic 20260930al')
entry = entry.replace('Authorized one-shot AK silent detached BOOST Switch guard trial', 'Authorized one-shot AL silent corrected-topology pin1 control')
assert entry.count('--id spx-trial-20260930al') == 1
assert entry.count('spi_hid.startup_diag=1') == 1
assert entry.count('soundwire_qcom.spx_force_attach=0') == 1
assert entry.count('devicetree /spx-trial-20260930ak/spx.dtb') == 1
assert entry.count('linux /spx-trial-20260930ak/vmlinuz') == 1
assert entry.count('initrd /spx-trial-20260930ak/initramfs.img') == 1
preview = Z / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

runtime = Path('/usr/local/lib/spx-boot-diagnostics/al-finalize.py')
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/110-al-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units = {}
for action, delay in (('finalize', 620), ('fallback', 900)):
    executable = str(runtime) if action == 'finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
    units[f'spx-al-{action}.service'] = (
        f'[Unit]\nDescription=AL silent corrected-topology pin1 control {action}\nConditionKernelCommandLine=spx_attempt=20260930al\n'
        'After=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n'
        f'[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n')
    units[f'spx-al-{action}.timer'] = (
        f'[Unit]\nDescription=AL {action} timer\nConditionKernelCommandLine=spx_attempt=20260930al\n\n'
        f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-al-{action}.service\n\n'
        '[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
write(Z / 'deploy-started', BID + '\n')
shutil.copy2('/boot/grub/custom.cfg', Z / 'custom-before-al.cfg')
temporary = Path('/boot/grub/custom.cfg.al-new')
write(temporary, entry, 0o644)
os.replace(temporary, '/boot/grub/custom.cfg')
write(Z / 'entry.cfg', entry)
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/al-reboot-check.py', Z / 'reboot-check.py')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/al-finalize.py', runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930al\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-al-finalize.timer', 'spx-al-fallback.timer'], check=True, timeout=30)
for name in ('spx-al-finalize.timer', 'spx-al-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'
runtime_files = [runtime, exclude, Z / 'reboot-check.py', Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
a = {'attempt': '20260930al', 'entry': 'spx-trial-20260930al', 'release': RELEASE,
     'preboot_id': BID, 'source_commit': prior['source_commit'],
     'source_diff': str(Z / 'build/source.diff'), 'build_archive': str(Z / 'build'),
     'state': 'prepared AL; no boot selection', 'sha256': prior['sha256'],
     'recovery_sha256': prior['recovery_sha256'], 'authorization': prior['authorization'],
     'runtime_sha256': {str(p): sha(p) for p in runtime_files},
     'cmdline': cmdline, 'parent_attempt': '20260930ak', 'return_window_seconds': 600,
     'comparison': 'Exact AK artifacts; pin2 -> pin1; no PCM or playback',
     'archive_review_sha256': sha(Z / 'archive-review.json'), 'playback_requested': False}
write(Z / 'attempt.json', json.dumps(a, indent=2) + '\n')
temporary = BASE / 'attempt-al.new.json'
write(temporary, json.dumps(a, indent=2) + '\n')
os.replace(temporary, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('AL installed with exact AK payloads; no selection or playback scheduled')
