#!/usr/bin/python3
"""Install the distinct W kernel and bounded, one-shot audio trial."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
V = BASE / 'attempts/20260927v'
W = BASE / 'attempts/20260927w'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT = Path('/boot/spx-trial-20260927w')
RELEASE = '7.3.0-rc2-spx-mainline-20260927w+'
BID = 'b9a390b7-fb58-40bc-8ae2-8404ee9e88d2'


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
assert not BOOT.exists() and not (Path('/usr/lib/modules') / RELEASE).exists()
assert not (W / 'deploy-started').exists() and not (W / 'attempt.json').exists()
assert not (W / 'entry.cfg').exists()
assert (W / 'retired-boot-slots/20260927r').is_dir()
assert not Path('/boot/spx-trial-20260927r').exists()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
assert Path('/boot/grub/custom.cfg').read_text() == (V / 'entry.cfg').read_text()
prior = json.loads((V / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
return_review = json.loads((V / 'independent-return-review.json').read_text())
assert return_review['current_boot_id'] == BID
assert return_review['recovery_hashes_verified'] == 3
assert sha(V / 'independent-return-review.json') == \
    'a18767d6534ac1d959674107ddf14cab2c3049d76aca05cda1db8c583dfbd4b9'
review = json.loads((W / 'independent-artifact-review.json').read_text())
assert review['regular_files_verified'] == 953 and review['symlinks_verified'] == 272
assert review['boot_selected'] is False and review['recovery_files_verified'] == 3
archive = json.loads((W / 'archive-review.json').read_text())
assert sha(W / 'build-sha256.json') == archive['build_manifest_sha256']
assert sha(W / 'build-symlinks.json') == archive['build_symlink_manifest_sha256']
assert sha(W / 'build/module-sha256.json') == archive['module_manifest_sha256']
assert sha(W / 'build/source.diff') == archive['source_diff_sha256']
assert sha(W / 'build/artifacts/.config') == archive['config_sha256']
assert command('git', '-C', str(REPO), 'rev-parse', 'HEAD') == \
    (W / 'build/source-commit.txt').read_text().strip()
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == \
    (W / 'build/source.diff').read_bytes()
manifest = json.loads((W / 'build-sha256.json').read_text())
symlinks = json.loads((W / 'build-symlinks.json').read_text())
assert files(W / 'build') == manifest and links(W / 'build') == symlinks
modules = json.loads((W / 'build/module-sha256.json').read_text())
assert len(modules) == 202
source_modules = W / 'build/module-root/lib/modules' / RELEASE
assert files(source_modules) == modules
for name, digest in prior['recovery_sha256'].items():
    assert sha(name) == digest, name
retired = json.loads((W / 'retired-r-sha256.json').read_text())
assert {p.name: sha(p) for p in (W / 'retired-boot-slots/20260927r').iterdir()
        if p.is_file()} == retired

entry = (V / 'entry.cfg').read_text().replace('20260927v', '20260927w')
entry = entry.replace('/spx-trial-20260927u/spx.dtb',
                      '/spx-trial-20260927w/spx.dtb')
entry = entry.replace('/spx-trial-20260927r/vmlinuz',
                      '/spx-trial-20260927w/vmlinuz')
entry = entry.replace('/spx-trial-20260927r/initramfs.img',
                      '/spx-trial-20260927w/initramfs.img')
entry = entry.replace('Authorized one-shot T SoundWire force-attach trial; corrected WSA DTB',
                      'Authorized one-shot W force-attach FIFO correction trial')
cmdline = prior['cmdline'].replace('spx_attempt=20260927v',
                                   'spx_attempt=20260927w')
assert entry.count(' ' + cmdline + '; then') == 1
assert all(entry.count('/spx-trial-20260927w/' + n) == 1
           for n in ('vmlinuz', 'spx.dtb', 'initramfs.img'))
assert '20260927r' not in entry and '20260927u' not in entry
preview = W / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

source_finalizer = REPO / 'tools/spx/boot-diagnostics/w-finalize.py'
runtime = Path('/usr/local/lib/spx-boot-diagnostics/w-finalize.py')
assert source_finalizer.is_file() and not runtime.exists()
units = {
 'spx-w-finalize.service': '[Unit]\nDescription=Archive W force-attach FIFO result at 620 seconds\nConditionKernelCommandLine=spx_attempt=20260927w\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/w-finalize.py\nTimeoutStartSec=180\n',
 'spx-w-finalize.timer': '[Unit]\nDescription=Automatically archive W result before fallback\nConditionKernelCommandLine=spx_attempt=20260927w\n\n[Timer]\nOnBootSec=620\nAccuracySec=1\nUnit=spx-w-finalize.service\n\n[Install]\nWantedBy=timers.target\n',
 'spx-w-fallback.service': '[Unit]\nDescription=Return W to known-good if codec initialization fails\nConditionKernelCommandLine=spx_attempt=20260927w\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/return.sh\nTimeoutStartSec=90\n',
 'spx-w-fallback.timer': '[Unit]\nDescription=Bound W after its automatic result collector\nConditionKernelCommandLine=spx_attempt=20260927w\n\n[Timer]\nOnBootSec=900\nAccuracySec=1\nUnit=spx-w-fallback.service\n\n[Install]\nWantedBy=timers.target\n'}
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/96-w-exclude.conf')
assert not exclude.exists()

write(W / 'deploy-started', BID + '\n')
installed = Path('/usr/lib/modules') / RELEASE
shutil.copytree(source_modules, installed, symlinks=True)
assert files(installed) == modules and links(installed) == links(source_modules)
BOOT.mkdir(mode=0o700)
payload_source = {
    'vmlinuz': W / 'build/vmlinuz',
    'initramfs.img': W / 'build/initramfs.img',
    'spx.dtb': W / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb',
}
payload_expected = archive['boot_payload_sha256']
for name, source in payload_source.items():
    shutil.copy2(source, BOOT / name)
    key = ('artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
           if name == 'spx.dtb' else name)
    assert sha(BOOT / name) == payload_expected[key]
shutil.copy2('/boot/grub/custom.cfg', W / 'custom-before-w.cfg')
tmp = Path('/boot/grub/custom.cfg.w-new')
write(tmp, entry, 0o644)
os.replace(tmp, '/boot/grub/custom.cfg')
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True,
               timeout=30)
write(W / 'entry.cfg', entry)
shutil.copy2(source_finalizer, runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260927w\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-w-finalize.timer',
                'spx-w-fallback.timer'], check=True, timeout=30)
for name in ('spx-w-finalize.timer', 'spx-w-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'

runtime_files = [runtime, exclude,
                 Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
payloads = {str(BOOT / name): sha(BOOT / name) for name in payload_source}
attempt = {'attempt': '20260927w', 'entry': 'spx-trial-20260927w',
           'release': RELEASE, 'preboot_id': BID,
           'source_commit': prior['source_commit'],
           'source_diff': str(W / 'build/source.diff'),
           'build_archive': str(W / 'build'),
           'state': 'prepared W; no boot selection',
           'sha256': payloads,
           'recovery_sha256': prior['recovery_sha256'],
           'runtime_sha256': {str(p): sha(p) for p in runtime_files},
           'authorization': prior['authorization'], 'cmdline': cmdline,
           'parent_attempt': '20260927v',
           'comparison': 'Distinct W kernel with force-attach FIFO flush; same V selectors and corrected DTB',
           'return_window_seconds': 600,
           'artifact_review_sha256': sha(W / 'independent-artifact-review.json'),
           'prior_result_review_sha256': sha(V / 'independent-result-review.json'),
           'prior_return_review_sha256': sha(V / 'independent-return-review.json')}
write(W / 'attempt.json', json.dumps(attempt, indent=2) + '\n')
tmp = BASE / 'attempt-w.new.json'
write(tmp, json.dumps(attempt, indent=2) + '\n')
os.replace(tmp, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('W installed with distinct kernel and modules; no boot selected')
