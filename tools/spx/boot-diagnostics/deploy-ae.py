#!/usr/bin/python3
"""Install AE's distinct silent diagnostic payload and bounded timers, unselected."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
Z = BASE / 'attempts/20260930ad'
AE = BASE / 'attempts/20260930ae'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT = Path('/boot/spx-trial-20260930ae')
RELEASE = '7.3.0-rc2-spx-mainline-20260930ae+'
BID = '86c3ff68-09a9-480c-9288-be9443254378'


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


def write(path, value, mode=0o600):
    with Path(path).open('x') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    Path(path).chmod(mode)


assert os.geteuid() == 0 and not (AE / 'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260930aa+'
assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()
assert not BOOT.exists() and not (Path('/usr/lib/modules') / RELEASE).exists()
assert not (AE / 'attempt.json').exists() and not (AE / 'entry.cfg').exists()
prior = json.loads((Z / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
assert Path('/boot/grub/custom.cfg').read_text() == (Z / 'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
archive = json.loads((AE / 'archive-review.json').read_text())
assert archive['preboot_id'] == BID and not archive['boot_selected']
assert sha(AE / 'build-sha256.json') == archive['build_manifest_sha256']
assert sha(AE / 'build/module-sha256.json') == archive['module_manifest_sha256']
assert files(AE / 'build') == json.loads((AE / 'build-sha256.json').read_text())
assert links(AE / 'build') == json.loads((AE / 'build-symlinks.json').read_text())
assert command('git', '-C', str(REPO), 'rev-parse', 'HEAD') == (AE / 'build/source-commit.txt').read_text().strip()
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (AE / 'build/source.diff').read_bytes()
assert sha(REPO / '.config') == archive['config_sha256']
build_review = json.loads((AE / 'independent-build-review.json').read_text())
assert build_review['build_manifest_sha256'] == archive['build_manifest_sha256']
assert build_review['driver_delta'] == 'SPI_HID_DIAG_WINDOWS4->8 only'
assert build_review['config_delta'] == 'LOCALVERSION only'
assert build_review['functional_driver_policy_unchanged'] and build_review['dtb_exact_ab']
modules = json.loads((AE / 'build/module-sha256.json').read_text())
source_modules = AE / 'build/module-root/lib/modules' / RELEASE
assert len(modules) == 202 and files(source_modules) == modules
for name, digest in prior['recovery_sha256'].items():
    assert sha(name) == digest, name
parent_review = json.loads((Z / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']
assert sha(Z / 'independent-result-review.json') == archive['parent_result_review_sha256']
assert sha(Z / 'touch-startup-review.json') == archive['parent_touch_review_sha256']
assert archive['dtb_exact_ab'] and archive['functional_policy_unchanged']
assert archive['startup_diag_windows'] == 8 and archive['startup_diag_events_per_window'] == 48
assert command('systemctl', 'show', 'spx-ad-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
for name, digest in (prior['sha256'] | prior['runtime_sha256']).items():
    assert sha(name) == digest, name
required_bytes = sum((AE / 'build' / name).stat().st_size for name in ('vmlinuz', 'initramfs.img')) + 1048576
space = os.statvfs('/boot')
assert space.f_bavail * space.f_frsize > required_bytes, 'insufficient /boot space'

cmdline = prior['cmdline'].replace('spx_attempt=20260930ad', 'spx_attempt=20260930ae')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930ae'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930ad'}
entry = (Z / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260930ad', '--id spx-trial-20260930ae')
entry = entry.replace('set spx_diag_attempt=20260930ad', 'set spx_diag_attempt=20260930ae')
entry = entry.replace('SPX bounded boot diagnostic 20260930ad', 'SPX bounded boot diagnostic 20260930ae')
entry = entry.replace('Authorized one-shot AD silent touch startup metadata trial', 'Authorized one-shot AE silent later-startup metadata trial')
entry = entry.replace('/spx-trial-20260930aa/vmlinuz', '/spx-trial-20260930ae/vmlinuz')
entry = entry.replace('/spx-trial-20260930aa/initramfs.img', '/spx-trial-20260930ae/initramfs.img')
entry = entry.replace('/spx-trial-20260930ab/spx.dtb', '/spx-trial-20260930ae/spx.dtb')
assert entry.count('--id spx-trial-20260930ae') == 1
assert entry.count('spi_hid.startup_diag=1') == 1 and entry.count('soundwire_qcom.spx_force_attach=0') == 1
assert all(entry.count('/spx-trial-20260930ae/' + name) == 1 for name in ('vmlinuz', 'spx.dtb', 'initramfs.img'))
preview = AE / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()
runtime = Path('/usr/local/lib/spx-boot-diagnostics/ae-finalize.py')
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/103-ae-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units = {}
for action, delay in (('finalize', 620), ('fallback', 900)):
    executable = str(runtime) if action == 'finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
    units[f'spx-ae-{action}.service'] = (
        f'[Unit]\nDescription=AE silent later-startup metadata {action}\nConditionKernelCommandLine=spx_attempt=20260930ae\n'
        'After=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n'
        f'[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n')
    units[f'spx-ae-{action}.timer'] = (
        f'[Unit]\nDescription=AE {action} timer\nConditionKernelCommandLine=spx_attempt=20260930ae\n\n'
        f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ae-{action}.service\n\n'
        '[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
for name in ('ae-finalize.py', 'ae-reboot-check.py'):
    assert (REPO / 'tools/spx/boot-diagnostics' / name).is_file()

write(AE / 'deploy-started', BID + '\n')
installed = Path('/usr/lib/modules') / RELEASE
shutil.copytree(source_modules, installed, symlinks=True)
assert files(installed) == modules and links(installed) == links(source_modules)
BOOT.mkdir(mode=0o700)
payload_source = {'vmlinuz': AE / 'build/vmlinuz', 'initramfs.img': AE / 'build/initramfs.img',
                  'spx.dtb': AE / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'}
for name, source in payload_source.items():
    shutil.copy2(source, BOOT / name)
    key = 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb' if name == 'spx.dtb' else name
    assert sha(BOOT / name) == archive['boot_payload_sha256'][key]
shutil.copy2('/boot/grub/custom.cfg', AE / 'custom-before-ae.cfg')
temporary = Path('/boot/grub/custom.cfg.ae-new')
write(temporary, entry, 0o644)
os.replace(temporary, '/boot/grub/custom.cfg')
write(AE / 'entry.cfg', entry)
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/ae-reboot-check.py', AE / 'reboot-check.py')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/ae-finalize.py', runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930ae\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-ae-finalize.timer', 'spx-ae-fallback.timer'], check=True, timeout=30)
for name in ('spx-ae-finalize.timer', 'spx-ae-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'
runtime_files = [runtime, exclude, AE / 'reboot-check.py', Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
a = {'attempt': '20260930ae', 'entry': 'spx-trial-20260930ae', 'release': RELEASE,
     'preboot_id': BID, 'source_commit': (AE / 'build/source-commit.txt').read_text().strip(),
     'source_diff': str(AE / 'build/source.diff'), 'build_archive': str(AE / 'build'),
     'state': 'prepared AE; no boot selection', 'sha256': {str(BOOT / name): sha(BOOT / name) for name in payload_source},
     'recovery_sha256': prior['recovery_sha256'], 'authorization': prior['authorization'],
     'runtime_sha256': {str(p): sha(p) for p in runtime_files},
     'cmdline': cmdline, 'parent_attempt': '20260930ad', 'return_window_seconds': 600,
     'comparison': 'Distinct startup logger windows4->8; exact AB DTB and AD selectors; no playback',
     'archive_review_sha256': sha(AE / 'archive-review.json'), 'playback_requested': False}
write(AE / 'attempt.json', json.dumps(a, indent=2) + '\n')
temporary = BASE / 'attempt-ae.new.json'
write(temporary, json.dumps(a, indent=2) + '\n')
os.replace(temporary, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('AE installed with distinct kernel/modules; no boot selected or playback scheduled')
