#!/usr/bin/python3
"""Install V's one-shot readless codec entry and bounded result collector."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
U = BASE / 'attempts/20260927u'
V = BASE / 'attempts/20260927v'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = 'db7ee26c-fe9f-4106-bc22-e5454ba51f9e'
RELEASE = '7.3.0-rc2-spx-mainline-20260927r+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


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
assert command('uname', '-r') == RELEASE
assert 'spx_attempt=20260927u' in Path('/proc/cmdline').read_text().split()
assert not (V / 'deploy-started').exists()
assert not (V / 'attempt.json').exists() and not (V / 'entry.cfg').exists()
prior = json.loads((U / 'attempt.json').read_text())
assert prior == json.loads((BASE / 'attempt.json').read_text())
result = json.loads((U / 'independent-result-review.json').read_text())
assert result['boot_id'] == BID and result['corrected_scoped_pass']
assert result['fallback_stopped'] and result['logical_attached_slaves'] == 1
assert sha(U / 'final-result/sha256.json') == result['result_manifest_sha256']
assert command('systemctl', 'show', 'spx-u-fallback.timer', '-p',
               'ActiveState', '--value') != 'active'
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
assert Path('/boot/grub/custom.cfg').read_text() == (U / 'entry.cfg').read_text()
reuse = json.loads((V / 'reuse-review.json').read_text())
assert reuse['boot_selected'] is False and reuse['preboot_id'] == BID
assert sha(V / 'reused-build-sha256.json') == reuse['reused_build_manifest_sha256']
assert sha(V / 'dtb-build/spx.dtb') == reuse['dtb_sha256']
assert sha(V / 'dtb-build/source.diff') == reuse['source_diff_sha256']
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (
    V / 'dtb-build/source.diff').read_bytes()
for name, digest in (prior['sha256'] | prior['recovery_sha256']).items():
    assert sha(name) == digest, name
build = json.loads((V / 'reused-build-sha256.json').read_text())
assert len(build) == 922
for name, digest in build.items():
    assert sha(V / 'reused-build' / name) == digest, name
modules = json.loads((V / 'reused-build/module-sha256.json').read_text())
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(Path('/usr/lib/modules') / RELEASE / name) == digest, name

def change(value):
    assert value.count('spx_attempt=20260927u') == 1
    assert value.count('soundwire_qcom.spx_force_attach=1') == 1
    assert 'snd_soc_wsa881x.spx_enumerated_mode=' not in value
    value = value.replace('20260927u', '20260927v')
    value = value.replace('/spx-trial-20260927v/spx.dtb',
                          '/spx-trial-20260927u/spx.dtb')
    value = value.replace('soundwire_qcom.spx_force_attach=1',
                          'soundwire_qcom.spx_force_attach=1 '
                          'snd_soc_wsa881x.spx_enumerated_mode=1')
    return value


entry = change((U / 'entry.cfg').read_text())
entry = entry.replace('Authorized one-shot U SoundWire force-attach trial',
                      'Authorized one-shot V readless WSA trial')
cmdline = change(prior['cmdline'])
assert entry.count(' ' + cmdline + '; then') == 1
assert entry.count('devicetree /spx-trial-20260927u/spx.dtb') == 1
assert entry.count('spx_attempt=20260927v') == 1
preview = V / 'entry.preview.cfg'
write(preview, entry)
subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
preview.unlink()

source_finalizer = REPO / 'tools/spx/boot-diagnostics/v-finalize.py'
runtime = Path('/usr/local/lib/spx-boot-diagnostics/v-finalize.py')
assert source_finalizer.is_file() and not runtime.exists()
units = {
 'spx-v-finalize.service': '[Unit]\nDescription=Archive V readless WSA result at 620 seconds\nConditionKernelCommandLine=spx_attempt=20260927v\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/v-finalize.py\nTimeoutStartSec=180\n',
 'spx-v-finalize.timer': '[Unit]\nDescription=Automatically archive V result before fallback\nConditionKernelCommandLine=spx_attempt=20260927v\n\n[Timer]\nOnBootSec=620\nAccuracySec=1\nUnit=spx-v-finalize.service\n\n[Install]\nWantedBy=timers.target\n',
 'spx-v-fallback.service': '[Unit]\nDescription=Return V to known-good if codec initialization fails\nConditionKernelCommandLine=spx_attempt=20260927v\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/local/lib/spx-boot-diagnostics/return.sh\nTimeoutStartSec=90\n',
 'spx-v-fallback.timer': '[Unit]\nDescription=Bound V after its automatic result collector\nConditionKernelCommandLine=spx_attempt=20260927v\n\n[Timer]\nOnBootSec=900\nAccuracySec=1\nUnit=spx-v-fallback.service\n\n[Install]\nWantedBy=timers.target\n'}
assert all(not (Path('/etc/systemd/system') / name).exists() for name in units)
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/95-v-exclude.conf')
assert not exclude.exists()

write(V / 'deploy-started', BID + '\n')
shutil.copy2('/boot/grub/custom.cfg', V / 'custom-before-v.cfg')
tmp = Path('/boot/grub/custom.cfg.v-new')
write(tmp, entry, 0o644)
os.replace(tmp, '/boot/grub/custom.cfg')
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True,
               timeout=30)
write(V / 'entry.cfg', entry)
shutil.copy2(source_finalizer, runtime)
runtime.chmod(0o755)
for name, content in units.items():
    write(Path('/etc/systemd/system') / name, content, 0o644)
write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20260927v\n', 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', 'enable', 'spx-v-finalize.timer',
                'spx-v-fallback.timer'], check=True, timeout=30)
for name in ('spx-v-finalize.timer', 'spx-v-fallback.timer'):
    assert command('systemctl', 'is-enabled', name) == 'enabled'
    assert command('systemctl', 'show', name, '-p', 'ActiveState', '--value') != 'active'

runtime_files = [runtime, exclude,
                 Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
                 Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
runtime_files += [Path('/etc/systemd/system') / name for name in units]
attempt = {'attempt': '20260927v', 'entry': 'spx-trial-20260927v',
           'release': RELEASE, 'preboot_id': BID,
           'source_commit': prior['source_commit'],
           'source_diff': str(V / 'dtb-build/source.diff'),
           'build_archive': str(V / 'reused-build'),
           'dtb_build': str(V / 'dtb-build'),
           'state': 'prepared V; no boot selection',
           'sha256': prior['sha256'],
           'recovery_sha256': prior['recovery_sha256'],
           'runtime_sha256': {str(p): sha(p) for p in runtime_files},
           'authorization': prior['authorization'],
           'cmdline': cmdline, 'parent_attempt': '20260927u',
           'comparison': 'Exact U artifacts; only attempt and readless WSA selector change',
           'return_window_seconds': 600,
           'reuse_review_sha256': sha(V / 'reuse-review.json'),
           'prior_result_review_sha256': sha(U / 'independent-result-review.json')}
write(V / 'attempt.json', json.dumps(attempt, indent=2) + '\n')
tmp = BASE / 'attempt-v.new.json'
write(tmp, json.dumps(attempt, indent=2) + '\n')
os.replace(tmp, BASE / 'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'next_entry=' in command('grub-editenv',
    '/boot/grub/grubenv', 'list').splitlines()
os.sync()
print('V installed with exact U artifacts; no boot selected')
