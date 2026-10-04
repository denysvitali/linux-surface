#!/usr/bin/python3
"""Install AJ's distinct silent diagnostic payload and bounded timers, unselected."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS']='0'
BASE = Path('/var/lib/spx-boot-diagnostics')
Z = BASE / 'attempts/20260930ai'
AJ = BASE / 'attempts/20260930aj'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT = Path('/boot/spx-trial-20260930aj')
RELEASE = '7.3.0-rc2-spx-mainline-20260930aj+'
BID = '81412181-f873-4ba8-a5fe-07f5376bf680'


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


assert os.geteuid() == 0 and not (AJ / 'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == '6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
assert not BOOT.exists() and not (Path('/usr/lib/modules') / RELEASE).exists()
assert not (AJ / 'attempt.json').exists() and not (AJ / 'entry.cfg').exists()
prior = json.loads((Z / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
assert Path('/boot/grub/custom.cfg').read_text() == (Z / 'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
archive = json.loads((AJ / 'archive-review.json').read_text())
assert archive['preboot_id'] == BID and not archive['boot_selected']
assert sha(AJ / 'build-sha256.json') == archive['build_manifest_sha256']
assert sha(AJ / 'build/module-sha256.json') == archive['module_manifest_sha256']
assert files(AJ / 'build') == json.loads((AJ / 'build-sha256.json').read_text())
assert links(AJ / 'build') == json.loads((AJ / 'build-symlinks.json').read_text())
assert command('git', '-C', str(REPO), 'rev-parse', 'HEAD') == (AJ / 'build/source-commit.txt').read_text().strip()
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (AJ / 'build/source.diff').read_bytes()
assert sha(REPO / '.config') == archive['config_sha256']
build_review = json.loads((AJ / 'independent-build-review.json').read_text())
assert build_review['build_manifest_sha256'] == archive['build_manifest_sha256']
assert build_review['driver_delta'] == 'detached PA gain availability guard only'
assert build_review['config_delta'] == 'LOCALVERSION only'
assert not build_review['functional_driver_policy_unchanged'] and build_review['detached_gain_guard_verified'] and build_review['dtb_exact_ag']
modules = json.loads((AJ / 'build/module-sha256.json').read_text())
source_modules = AJ / 'build/module-root/lib/modules' / RELEASE
assert len(modules) == 202 and files(source_modules) == modules
for name, digest in prior['recovery_sha256'].items():
    assert sha(name) == digest, name
parent_review = json.loads((Z / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == '45fe6dfc-cd08-4536-9cdf-d5423699080d' and not parent_review['scoped_passed'] and not parent_review['fallback_stopped']
assert json.loads((Z / 'recovery-return/report.json').read_text())['recovery_boot_id'] == BID
assert sha(Z / 'independent-result-review.json') == archive['parent_result_review_sha256']
assert sha(Z / 'touch-startup-review.json') == archive['parent_touch_review_sha256']
assert archive['dtb_exact_ag'] and not archive['functional_policy_unchanged']
assert archive['startup_diag_windows'] == 8 and archive['startup_diag_events_per_window'] == 48
assert command('systemctl', 'show', 'spx-ai-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
for name, digest in (prior['sha256'] | prior['runtime_sha256']).items():
    assert sha(name) == digest, name
required_bytes = sum((AJ / 'build' / name).stat().st_size for name in ('vmlinuz', 'initramfs.img')) + 1048576
space = os.statvfs('/boot')
assert space.f_bavail * space.f_frsize > required_bytes, 'insufficient /boot space'

cmdline = prior['cmdline'].replace('spx_attempt=20260930ai', 'spx_attempt=20260930aj')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930aj'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930ai'}
entry = (Z / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260930ai', '--id spx-trial-20260930aj')
entry = entry.replace('set spx_diag_attempt=20260930ai', 'set spx_diag_attempt=20260930aj')
entry = entry.replace('SPX bounded boot diagnostic 20260930ai', 'SPX bounded boot diagnostic 20260930aj')
entry = entry.replace('Authorized one-shot AI silent right command-history diagnostic', 'Authorized one-shot AJ silent detached PA gain guard trial')
entry = entry.replace('/spx-trial-20260930ai/vmlinuz', '/spx-trial-20260930aj/vmlinuz')
entry = entry.replace('/spx-trial-20260930ai/initramfs.img', '/spx-trial-20260930aj/initramfs.img')
entry = entry.replace('/spx-trial-20260930ai/spx.dtb', '/spx-trial-20260930aj/spx.dtb')
assert entry.count('--id spx-trial-20260930aj') == 1
assert entry.count('spi_hid.startup_diag=1') == 1 and entry.count('soundwire_qcom.spx_force_attach=0') == 1
assert all(entry.count('/spx-trial-20260930aj/' + name) == 1 for name in ('vmlinuz', 'spx.dtb', 'initramfs.img'))
preview = AJ / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()
runtime = Path('/usr/local/lib/spx-boot-diagnostics/aj-finalize.py')
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/108-aj-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units = {}
for action, delay in (('finalize', 620), ('fallback', 900)):
    executable = str(runtime) if action == 'finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
    units[f'spx-aj-{action}.service'] = (
        f'[Unit]\nDescription=AJ silent detached PA gain guard trial {action}\nConditionKernelCommandLine=spx_attempt=20260930aj\n'
        'After=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n'
        f'[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n')
    units[f'spx-aj-{action}.timer'] = (
        f'[Unit]\nDescription=AJ {action} timer\nConditionKernelCommandLine=spx_attempt=20260930aj\n\n'
        f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-aj-{action}.service\n\n'
        '[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
for name in ('aj-finalize.py', 'aj-reboot-check.py'):
    assert (REPO / 'tools/spx/boot-diagnostics' / name).is_file()

write(AJ / 'deploy-started', BID + '\n')
installed = Path('/usr/lib/modules') / RELEASE
shutil.copytree(source_modules, installed, symlinks=True)
assert files(installed) == modules and links(installed) == links(source_modules)
BOOT.mkdir(mode=0o700)
payload_source = {'vmlinuz': AJ / 'build/vmlinuz', 'initramfs.img': AJ / 'build/initramfs.img',
                  'spx.dtb': AJ / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'}
for name, source in payload_source.items():
    shutil.copy2(source, BOOT / name)
    key = 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb' if name == 'spx.dtb' else name
    assert sha(BOOT / name) == archive['boot_payload_sha256'][key]
shutil.copy2('/boot/grub/custom.cfg', AJ / 'custom-before-aj.cfg')
temporary = Path('/boot/grub/custom.cfg.aj-new')
write(temporary, entry, 0o644)
os.replace(temporary, '/boot/grub/custom.cfg')
write(AJ / 'entry.cfg', entry)
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/aj-reboot-check.py', AJ / 'reboot-check.py')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/aj-finalize.py', runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930aj\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-aj-finalize.timer', 'spx-aj-fallback.timer'], check=True, timeout=30)
for name in ('spx-aj-finalize.timer', 'spx-aj-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'
runtime_files = [runtime, exclude, AJ / 'reboot-check.py', Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
a = {'attempt': '20260930aj', 'entry': 'spx-trial-20260930aj', 'release': RELEASE,
     'preboot_id': BID, 'source_commit': (AJ / 'build/source-commit.txt').read_text().strip(),
     'source_diff': str(AJ / 'build/source.diff'), 'build_archive': str(AJ / 'build'),
     'state': 'prepared AJ; no boot selection', 'sha256': {str(BOOT / name): sha(BOOT / name) for name in payload_source},
     'recovery_sha256': prior['recovery_sha256'], 'authorization': prior['authorization'],
     'runtime_sha256': {str(p): sha(p) for p in runtime_files},
     'cmdline': cmdline, 'parent_attempt': '20260930ai', 'return_window_seconds': 600,
     'comparison': 'Detached PA gain guard only; exact AG DTB; pin2/native0/cmd_diag1; no playback',
     'archive_review_sha256': sha(AJ / 'archive-review.json'), 'playback_requested': False}
write(AJ / 'attempt.json', json.dumps(a, indent=2) + '\n')
temporary = BASE / 'attempt-aj.new.json'
write(temporary, json.dumps(a, indent=2) + '\n')
os.replace(temporary, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('AJ installed with distinct kernel/modules; no boot selected or playback scheduled')
