#!/usr/bin/python3
"""Install the distinct X kernel and bounded, one-shot audio trial."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
W = BASE / 'attempts/20260927w'
X = BASE / 'attempts/20260927x'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT = Path('/boot/spx-trial-20260927x')
RELEASE = '7.3.0-rc2-spx-mainline-20260927x+'
BID = 'e6989b7a-9ee5-4138-939d-84f8f73f53d5'


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
assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260927w+'
assert 'spx_attempt=20260927w' in Path('/proc/cmdline').read_text().split()
assert not BOOT.exists() and not (Path('/usr/lib/modules') / RELEASE).exists()
assert not (X / 'deploy-started').exists() and not (X / 'attempt.json').exists()
assert not (X / 'entry.cfg').exists()
assert (X / 'retired-boot-slots/20260927w').is_dir()
assert not Path('/boot/spx-trial-20260927w').exists()
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
assert Path('/boot/grub/custom.cfg').read_text() == (W / 'entry.cfg').read_text()
prior = json.loads((W / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
parent_review = json.loads((W / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed']
assert parent_review['fallback_stopped']
assert sha(W / 'independent-result-review.json') == \
    'fabb90518623edb95190a6185fadd533c040d515fb74c53b1fbcb4ec9d48934d'
assert sha(W / 'silent-pcm-test/sha256.json') == \
    'b907ddaa6fa6611ed6d796285c417cb6931360a5effbaad0b56fb95f9ce492d1'
review = json.loads((X / 'independent-artifact-review.json').read_text())
assert review['regular_files_verified'] == 964 and review['symlinks_verified'] == 272
assert review['boot_selected'] is False and review['recovery_files_verified'] == 3
archive = json.loads((X / 'archive-review.json').read_text())
assert sha(X / 'build-sha256.json') == archive['build_manifest_sha256']
assert sha(X / 'build-symlinks.json') == archive['build_symlink_manifest_sha256']
assert sha(X / 'build/module-sha256.json') == archive['module_manifest_sha256']
assert sha(X / 'build/source.diff') == archive['source_diff_sha256']
assert sha(X / 'build/artifacts/.config') == archive['config_sha256']
assert command('git', '-C', str(REPO), 'rev-parse', 'HEAD') == \
    (X / 'build/source-commit.txt').read_text().strip()
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == \
    (X / 'build/source.diff').read_bytes()
manifest = json.loads((X / 'build-sha256.json').read_text())
symlinks = json.loads((X / 'build-symlinks.json').read_text())
assert files(X / 'build') == manifest and links(X / 'build') == symlinks
modules = json.loads((X / 'build/module-sha256.json').read_text())
assert len(modules) == 202
source_modules = X / 'build/module-root/lib/modules' / RELEASE
assert files(source_modules) == modules
for name, digest in prior['recovery_sha256'].items():
    assert sha(name) == digest, name
retired = json.loads((X / 'retired-w-sha256.json').read_text())
assert {p.name: sha(p) for p in (X / 'retired-boot-slots/20260927w').iterdir()
        if p.is_file()} == retired

entry = (W / 'entry.cfg').read_text().replace('20260927w', '20260927x')
entry = entry.replace('Authorized one-shot W force-attach FIFO correction trial',
                      'Authorized one-shot X attached-only WSA transport trial')
cmdline = prior['cmdline'].replace('spx_attempt=20260927w',
                                   'spx_attempt=20260927x')
assert entry.count(' ' + cmdline + '; then') == 1
assert all(entry.count('/spx-trial-20260927x/' + n) == 1
           for n in ('vmlinuz', 'spx.dtb', 'initramfs.img'))
assert '20260927w' not in entry
preview = X / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

source_finalizer = REPO / 'tools/spx/boot-diagnostics/x-finalize.py'
runtime = Path('/usr/local/lib/spx-boot-diagnostics/x-finalize.py')
assert source_finalizer.is_file() and not runtime.exists()
units = {
 'spx-x-finalize.service': '[Unit]\nDescription=Archive X attached-only WSA transport result at 620 seconds\nConditionKernelCommandLine=spx_attempt=20260927x\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/x-finalize.py\nTimeoutStartSec=180\n',
 'spx-x-finalize.timer': '[Unit]\nDescription=Automatically archive X result before fallback\nConditionKernelCommandLine=spx_attempt=20260927x\n\n[Timer]\nOnBootSec=620\nAccuracySec=1\nUnit=spx-x-finalize.service\n\n[Install]\nWantedBy=timers.target\n',
 'spx-x-fallback.service': '[Unit]\nDescription=Return X to known-good if codec initialization fails\nConditionKernelCommandLine=spx_attempt=20260927x\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/return.sh\nTimeoutStartSec=90\n',
 'spx-x-fallback.timer': '[Unit]\nDescription=Bound X after its automatic result collector\nConditionKernelCommandLine=spx_attempt=20260927x\n\n[Timer]\nOnBootSec=900\nAccuracySec=1\nUnit=spx-x-fallback.service\n\n[Install]\nWantedBy=timers.target\n'}
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/97-x-exclude.conf')
assert not exclude.exists()

write(X / 'deploy-started', BID + '\n')
installed = Path('/usr/lib/modules') / RELEASE
shutil.copytree(source_modules, installed, symlinks=True)
assert files(installed) == modules and links(installed) == links(source_modules)
BOOT.mkdir(mode=0o700)
payload_source = {
    'vmlinuz': X / 'build/vmlinuz',
    'initramfs.img': X / 'build/initramfs.img',
    'spx.dtb': X / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb',
}
payload_expected = archive['boot_payload_sha256']
for name, source in payload_source.items():
    shutil.copy2(source, BOOT / name)
    key = ('artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
           if name == 'spx.dtb' else name)
    assert sha(BOOT / name) == payload_expected[key]
shutil.copy2('/boot/grub/custom.cfg', X / 'custom-before-x.cfg')
tmp = Path('/boot/grub/custom.cfg.x-new')
write(tmp, entry, 0o644)
os.replace(tmp, '/boot/grub/custom.cfg')
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True,
               timeout=30)
write(X / 'entry.cfg', entry)
shutil.copy2(source_finalizer, runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260927x\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-x-finalize.timer',
                'spx-x-fallback.timer'], check=True, timeout=30)
for name in ('spx-x-finalize.timer', 'spx-x-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'

runtime_files = [runtime, exclude,
                 Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
payloads = {str(BOOT / name): sha(BOOT / name) for name in payload_source}
attempt = {'attempt': '20260927x', 'entry': 'spx-trial-20260927x',
           'release': RELEASE, 'preboot_id': BID,
           'source_commit': prior['source_commit'],
           'source_diff': str(X / 'build/source.diff'),
           'build_archive': str(X / 'build'),
           'state': 'prepared X; no boot selection',
           'sha256': payloads,
           'recovery_sha256': prior['recovery_sha256'],
           'runtime_sha256': {str(p): sha(p) for p in runtime_files},
           'authorization': prior['authorization'], 'cmdline': cmdline,
           'parent_attempt': '20260927w',
           'comparison': 'Distinct X kernel gates detached WSA stream use; same W selectors and corrected DTB',
           'return_window_seconds': 600,
           'artifact_review_sha256': sha(X / 'independent-artifact-review.json'),
           'prior_result_review_sha256': sha(W / 'independent-result-review.json'),
           'prior_silent_test_manifest_sha256': sha(W / 'silent-pcm-test/sha256.json')}
write(X / 'attempt.json', json.dumps(attempt, indent=2) + '\n')
tmp = BASE / 'attempt-x.new.json'
write(tmp, json.dumps(attempt, indent=2) + '\n')
os.replace(tmp, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('X installed with distinct kernel and modules; no boot selected')
