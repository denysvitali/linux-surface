#!/usr/bin/python3
"""Install AA's distinct silent diagnostic payload and bounded timers, unselected."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
Z = BASE / 'attempts/20260930z'
AA = BASE / 'attempts/20260930aa'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT = Path('/boot/spx-trial-20260930aa')
RELEASE = '7.3.0-rc2-spx-mainline-20260930aa+'
BID = 'e0479717-1fe0-4a8f-a6ac-af198c4b703a'


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


assert os.geteuid() == 0 and not (AA / 'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == '6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
assert not BOOT.exists() and not (Path('/usr/lib/modules') / RELEASE).exists()
assert not (AA / 'attempt.json').exists() and not (AA / 'entry.cfg').exists()
prior = json.loads((Z / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
assert Path('/boot/grub/custom.cfg').read_text() == (Z / 'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
archive = json.loads((AA / 'archive-review.json').read_text())
assert archive['preboot_id'] == BID and not archive['boot_selected']
assert sha(AA / 'build-sha256.json') == archive['build_manifest_sha256']
assert sha(AA / 'build/module-sha256.json') == archive['module_manifest_sha256']
assert files(AA / 'build') == json.loads((AA / 'build-sha256.json').read_text())
assert links(AA / 'build') == json.loads((AA / 'build-symlinks.json').read_text())
assert command('git', '-C', str(REPO), 'rev-parse', 'HEAD') == (AA / 'build/source-commit.txt').read_text().strip()
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (AA / 'build/source.diff').read_bytes()
assert sha(REPO / '.config') == archive['config_sha256']
modules = json.loads((AA / 'build/module-sha256.json').read_text())
source_modules = AA / 'build/module-root/lib/modules' / RELEASE
assert len(modules) == 202 and files(source_modules) == modules
for name, digest in prior['recovery_sha256'].items():
    assert sha(name) == digest, name
retired = AA / 'retired-boot-slots/20260927y'
assert files(retired) == json.loads((AA / 'retired-y-sha256.json').read_text())
assert not Path('/boot/spx-trial-20260927y').exists()

cmdline = prior['cmdline'].replace('spx_attempt=20260930z', 'spx_attempt=20260930aa') + ' soundwire_qcom.spx_enum_diag=1'
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930aa', 'soundwire_qcom.spx_enum_diag=1'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930z'}
entry = (Z / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('20260930z', '20260930aa').replace('20260927y', '20260930aa')
entry = entry.replace('Authorized one-shot Z silent SD_N pin 1 trial', 'Authorized one-shot AA silent enumerator identity trial')
assert entry.count('--id spx-trial-20260930aa') == 1
assert entry.count('soundwire_qcom.spx_enum_diag=1') == 1
assert all(entry.count('/spx-trial-20260930aa/' + name) == 1 for name in ('vmlinuz', 'spx.dtb', 'initramfs.img'))
preview = AA / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()
runtime = Path('/usr/local/lib/spx-boot-diagnostics/aa-finalize.py')
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/99-aa-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units = {}
for action, delay in (('finalize', 620), ('fallback', 900)):
    executable = str(runtime) if action == 'finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
    units[f'spx-aa-{action}.service'] = (
        f'[Unit]\nDescription=AA silent identity {action}\nConditionKernelCommandLine=spx_attempt=20260930aa\n'
        'After=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n'
        f'[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n')
    units[f'spx-aa-{action}.timer'] = (
        f'[Unit]\nDescription=AA {action} timer\nConditionKernelCommandLine=spx_attempt=20260930aa\n\n'
        f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-aa-{action}.service\n\n'
        '[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
for name in ('aa-finalize.py', 'aa-reboot-check.py'):
    assert (REPO / 'tools/spx/boot-diagnostics' / name).is_file()

write(AA / 'deploy-started', BID + '\n')
installed = Path('/usr/lib/modules') / RELEASE
shutil.copytree(source_modules, installed, symlinks=True)
assert files(installed) == modules and links(installed) == links(source_modules)
BOOT.mkdir(mode=0o700)
payload_source = {'vmlinuz': AA / 'build/vmlinuz', 'initramfs.img': AA / 'build/initramfs.img',
                  'spx.dtb': AA / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'}
for name, source in payload_source.items():
    shutil.copy2(source, BOOT / name)
    key = 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb' if name == 'spx.dtb' else name
    assert sha(BOOT / name) == archive['boot_payload_sha256'][key]
shutil.copy2('/boot/grub/custom.cfg', AA / 'custom-before-aa.cfg')
temporary = Path('/boot/grub/custom.cfg.aa-new')
write(temporary, entry, 0o644)
os.replace(temporary, '/boot/grub/custom.cfg')
write(AA / 'entry.cfg', entry)
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/aa-reboot-check.py', AA / 'reboot-check.py')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/aa-finalize.py', runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930aa\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-aa-finalize.timer', 'spx-aa-fallback.timer'], check=True, timeout=30)
for name in ('spx-aa-finalize.timer', 'spx-aa-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'
runtime_files = [runtime, exclude, AA / 'reboot-check.py', Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
a = {'attempt': '20260930aa', 'entry': 'spx-trial-20260930aa', 'release': RELEASE,
     'preboot_id': BID, 'source_commit': (AA / 'build/source-commit.txt').read_text().strip(),
     'source_diff': str(AA / 'build/source.diff'), 'build_archive': str(AA / 'build'),
     'state': 'prepared AA; no boot selection', 'sha256': {str(BOOT / name): sha(BOOT / name) for name in payload_source},
     'recovery_sha256': prior['recovery_sha256'], 'authorization': prior['authorization'],
     'runtime_sha256': {str(p): sha(p) for p in runtime_files},
     'cmdline': cmdline, 'parent_attempt': '20260930z', 'return_window_seconds': 600,
     'comparison': 'Distinct bounded existing-read enum logger; exact Z DTB and selectors; no playback',
     'archive_review_sha256': sha(AA / 'archive-review.json'), 'playback_requested': False}
write(AA / 'attempt.json', json.dumps(a, indent=2) + '\n')
temporary = BASE / 'attempt-aa.new.json'
write(temporary, json.dumps(a, indent=2) + '\n')
os.replace(temporary, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('AA installed with distinct kernel/modules; no boot selected or playback scheduled')
