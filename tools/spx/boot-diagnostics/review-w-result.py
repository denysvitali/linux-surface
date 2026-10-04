#!/usr/bin/python3
"""Independently rehash and interpret W's completed automatic result."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
W = BASE / 'attempts/20260927w'
RELEASE = '7.3.0-rc2-spx-mainline-20260927w+'


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


assert os.geteuid() == 0 and not (W / 'independent-result-review.json').exists()
a = json.loads((W / 'attempt.json').read_text())
assert a == json.loads((BASE / 'attempt.json').read_text())
assert a['attempt'] == '20260927w' and a['release'] == RELEASE
result_root = W / 'final-result'
expected = json.loads((result_root / 'sha256.json').read_text())
actual = files(result_root)
assert actual == expected | {'sha256.json': sha(result_root / 'sha256.json')}
result = json.loads((result_root / 'result.json').read_text())
action = json.loads((W / 'finalizer-action.json').read_text())
assert result['attempt'] == '20260927w'
assert action['boot_id'] == result['boot_id']
assert action['result_sha256'] == sha(result_root / 'result.json')
assert action['manifest_sha256'] == sha(result_root / 'sha256.json')
assert action['files_verified'] == len(expected)
assert result['release'] == RELEASE
assert (result_root / 'cmdline').read_text().split() == \
    ['BOOT_IMAGE=/spx-trial-20260927w/vmlinuz'] + a['cmdline'].split()
kernel = (result_root / 'kernel.log').read_text()
assert result['wsa_write_overflows'] == kernel.count(
    'swrm_wait_for_wr_fifo_avail err write overflow')
assert result['wsa_status_update_failures'] == kernel.count(
    'Update Slave status failed')
assert result['wsa_read_underflows'] == kernel.count(
    'swrm_wait_for_rd_fifo_avail err read underflow')
assert result['wsa_cold_init_markers'] == kernel.count(
    'SPX: initializing amplifier at SoundWire device 1')
assert result['wsa_slave_init_failures'] == kernel.count(
    'Slave 1 initialization failed')
sdw = json.loads((result_root / 'soundwire-slaves.json').read_text())
assert result['soundwire_slaves'] == sdw
attached = sum(x['status'].casefold() == 'attached' and
               x['device_number'] == '1' for x in sdw.values())
assert attached == result['attached_slave_count']
assert len(sdw) == 2
build = json.loads((W / 'build-sha256.json').read_text())
build_links = json.loads((W / 'build-symlinks.json').read_text())
assert len(build) == 953 and len(build_links) == 272
assert files(W / 'build') == build and links(W / 'build') == build_links
modules = json.loads((W / 'build/module-sha256.json').read_text())
assert len(modules) == 202
assert files(Path('/usr/lib/modules') / RELEASE) == modules
for name, digest in (a['sha256'] | a['recovery_sha256'] |
                     a['runtime_sha256']).items():
    assert sha(name) == digest, name
env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'],
                              text=True, timeout=30).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True,
                                                 timeout=30)
mechanism = (result['wsa_write_overflows'] == 0 and
             result['wsa_status_update_failures'] == 0 and
             result['wsa_slave_init_failures'] == 0 and
             result['wsa_cold_init_markers'] >= 1 and attached >= 1 and
             result['soundcards_present'])
baseline = (result['fd680_renderer'] and result['wifi_connected'] and
            result['spi_hid_ready'] and result['kernel_taint'] == '0' and
            not result['kernel_fault_lines'])
assert action['fallback_stopped'] == result['passed_scoped_baseline']
report = {'attempt': '20260927w', 'boot_id': result['boot_id'],
          'result_manifest_sha256': sha(result_root / 'sha256.json'),
          'result_files_verified': len(expected),
          'build_files_verified': len(build),
          'build_symlinks_verified': len(build_links),
          'installed_module_files_verified': len(modules),
          'payload_recovery_runtime_hashes_verified': sum(len(x) for x in
              (a['sha256'], a['recovery_sha256'], a['runtime_sha256'])),
          'wsa_write_overflows': result['wsa_write_overflows'],
          'wsa_status_update_failures': result['wsa_status_update_failures'],
          'wsa_read_underflows': result['wsa_read_underflows'],
          'wsa_slave_init_failures': result['wsa_slave_init_failures'],
          'logical_attached_slaves': attached,
          'codec_mechanism_passed': mechanism,
          'system_baseline_passed': baseline,
          'scoped_passed': result['passed_scoped_baseline'],
          'fallback_stopped': action['fallback_stopped'],
          'persistent_default': 'spx-known-good',
          'next_entry_empty': True, 'efi_bootnext_absent': True,
          'playback_verified': False}
(W / 'independent-result-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
