#!/usr/bin/python3
"""Independently rehash U's result and interpret SoundWire's status spelling."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
U = BASE / 'attempts/20260927u'
OUT = U / 'final-result'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


assert os.geteuid() == 0 and OUT.is_dir()
assert not (U / 'independent-result-review.json').exists()
result = json.loads((OUT / 'result.json').read_text())
action = json.loads((U / 'finalizer-action.json').read_text())
assert result['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert result['attempt'] == '20260927u'
assert 600 <= result['uptime_seconds'] < 900
assert not result['passed_scoped_baseline'] and not action['fallback_stopped']
manifest = json.loads((OUT / 'sha256.json').read_text())
actual = {str(p.relative_to(OUT)): sha(p) for p in OUT.rglob('*')
          if p.is_file() and not p.is_symlink() and p.name != 'sha256.json'}
assert actual == manifest
assert sha(OUT / 'sha256.json') == action['manifest_sha256']
assert len(manifest) == action['files_verified']
assert sha(OUT / 'result.json') == action['result_sha256']
attempt = json.loads((U / 'attempt.json').read_text())
assert attempt == json.loads((BASE / 'attempt.json').read_text())
for name, digest in (attempt['sha256'] | attempt['recovery_sha256'] |
                     attempt['runtime_sha256']).items():
    assert sha(Path(name)) == digest, name
build = json.loads((U / 'reused-build-sha256.json').read_text())
for name, digest in build.items():
    assert sha(U / 'reused-build' / name) == digest, name
modules = json.loads((U / 'reused-build/module-sha256.json').read_text())
root = Path('/usr/lib/modules') / attempt['release']
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(root / name) == digest, name
slaves = result['soundwire_slaves']
assert len(slaves) == 2 and all(':2010:' in name for name in slaves)
attached = sum(value['status'].casefold() == 'attached' and
               value['device_number'] == '1' for value in slaves.values())
assert result['attached_slave_count'] == 0 and attached >= 1
assert result['force_attach_worker_entries'] == 1
assert result['force_attach_done_markers'] == 1
assert result['force_attach_slave_markers'] >= 1
assert all(value == 1 for value in result['required_markers'].values())
assert result['controller_registration_markers'] == 1
assert result['runtime_resume_failure_markers'] == 0
assert result['capability_timeout_markers'] == 0
assert result['power_path'] in ('retained-address', 'capability-setup')
if result['power_path'] == 'capability-setup':
    assert result['capability_done_markers'] == 1
assert not result['kernel_fault_lines'] and result['kernel_taint'] == '0'
assert len(result['slim_devices']) == 2 and result['soundcards_present']
assert result['fd680_renderer'] and result['wifi_connected'] and result['spi_hid_ready']
assert command('systemctl', 'is-active', 'spx-u-fallback.timer') == 'active'
assert float(Path('/proc/uptime').read_text().split()[0]) < 880
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
subprocess.run(['systemctl', 'stop', 'spx-u-fallback.timer'], check=True,
               timeout=30)
assert command('systemctl', 'show', 'spx-u-fallback.timer', '-p',
               'ActiveState', '--value') != 'active'
review = {'attempt': '20260927u', 'boot_id': result['boot_id'],
          'original_scoped_pass': False,
          'corrected_scoped_pass': True,
          'correction': 'SoundWire sysfs reports Attached; collector compared ATTACHED',
          'logical_attached_slaves': attached,
          'physical_codec_init_success': False,
          'codec_init_failure_marker': 'Slave 1 initialization failed: -5',
          'result_files_verified': len(manifest),
          'result_manifest_sha256': sha(OUT / 'sha256.json'),
          'build_files_verified': len(build),
          'module_files_verified': len(modules),
          'payload_recovery_runtime_hashes_verified': len(
              attempt['sha256'] | attempt['recovery_sha256'] | attempt['runtime_sha256']),
          'fallback_stopped': True,
          'known_good_default': True,
          'next_entry_empty': True,
          'efi_bootnext_absent': True,
          'limits': 'Logical attachment alone does not establish physical reads or playback'}
assert review['codec_init_failure_marker'] in (OUT / 'kernel.log').read_text()
(U / 'independent-result-review.json').write_text(json.dumps(review, indent=2) + '\n')
os.sync()
print(json.dumps(review, indent=2))
