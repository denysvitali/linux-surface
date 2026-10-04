#!/usr/bin/python3
"""Rehash and interpret Z's silent GPIO boot result."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20260930z'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'


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


assert os.geteuid() == 0 and not (X / 'independent-result-review.json').exists()
a = json.loads((X / 'attempt.json').read_text())
assert a == json.loads((BASE / 'attempt.json').read_text())
assert a['attempt'] == '20260930z' and a['release'] == RELEASE
result_root = X / 'final-result'
expected = json.loads((result_root / 'sha256.json').read_text())
actual = files(result_root)
assert actual == expected | {'sha256.json': sha(result_root / 'sha256.json')}
result = json.loads((result_root / 'result.json').read_text())
action = json.loads((X / 'finalizer-action.json').read_text())
assert result['attempt'] == '20260930z'
assert action['boot_id'] == result['boot_id']
assert action['result_sha256'] == sha(result_root / 'result.json')
assert action['manifest_sha256'] == sha(result_root / 'sha256.json')
assert action['files_verified'] == len(expected)
assert result['release'] == RELEASE
assert (result_root / 'cmdline').read_text().split() == \
    ['BOOT_IMAGE=/spx-trial-20260927y/vmlinuz'] + a['cmdline'].split()
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
declared = {'sdw:0:0:0217:2010:00:3', 'sdw:0:0:0217:2010:00:4'}
assert declared <= set(sdw)
unexpected = sorted(set(sdw) - declared)
assert all(sdw[name]['driver'] == 'wsa881x-codec' for name in declared)
build = json.loads((X / 'build-sha256.json').read_text())
build_links = json.loads((X / 'build-symlinks.json').read_text())
assert len(build) == 977 and len(build_links) == 272
assert files(X / 'build') == build and links(X / 'build') == build_links
modules = json.loads((X / 'build/module-sha256.json').read_text())
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
             result['wsa_read_underflows'] == 0 and
             result['wsa_status_update_failures'] == 0 and
             result['wsa_slave_init_failures'] == 0 and
             result['wsa_cold_init_markers'] >= 1 and attached >= 1 and
             result['soundcards_present'])
baseline = (result['fd680_renderer'] and result['wifi_connected'] and
            result['spi_hid_ready'] and result['kernel_taint'] == '0' and
            not result['kernel_fault_lines'])
assert action['fallback_stopped'] == result['passed_scoped_baseline']
registers = json.loads((result_root / 'wcd-gpio-registers.json').read_text())
wcd_params = json.loads((result_root / 'wcd-params.json').read_text())
wsa_params = json.loads((result_root / 'wsa-params.json').read_text())
assert result['gpio_software_state_passed'] == (
    registers == {'0042': 2, '0043': 26}
    and wcd_params == {'spx_wsa_en_pin': '1', 'spx_wsa_gpio_dir': '-1', 'spx_wsa_gpio_val': '-1'}
    and wsa_params.get('spx_swap_dac_master_ports') == 'N'
    and kernel.count('SPX: forced wcd-gpio pin 1 output-high') == 1)
for marker, count in result['required_markers'].items():
    assert count == kernel.count(marker), marker
power_pass = (result['power_path'] == 'retained-address' or
              (result['power_path'] == 'capability-setup' and
               result['capability_done_markers'] == 1))
controller_pass = (all(v == 1 for v in result['required_markers'].values()) and
                   not result['kernel_fault_lines'] and
                   result['runtime_resume_failure_markers'] == 0 and
                   result['controller_registration_markers'] == 1 and
                   result['capability_timeout_markers'] == 0)
topology_pass = (len(result['slim_devices']) == 2 and len(sdw) == 2 and
                 all(':2010:' in name for name in sdw))
force_pass = (result['force_attach_worker_entries'] == 1 and
              result['force_attach_done_markers'] == 1 and
              result['force_attach_slave_markers'] >= 1 and
              result['wsa_enumerated_mode'] == 'Y')
expected_pass = (result['gpio_software_state_passed'] and power_pass and
                 controller_pass and topology_pass and force_pass and
                 mechanism and baseline)
assert result['passed_scoped_baseline'] == expected_pass
reasons = [name for name, passed in (
    ('GPIO software state', result['gpio_software_state_passed']),
    ('DSP power path', power_pass), ('controller startup', controller_pass),
    ('expected two-device topology', topology_pass),
    ('force-attach path', force_pass), ('codec initialization', mechanism),
    ('graphics/Wi-Fi/touch baseline', baseline)) if not passed]
report = {'attempt': '20260930z', 'boot_id': result['boot_id'],
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
          'gpio_software_state_passed': result['gpio_software_state_passed'],
          'gpio_register_view': registers,
          'soundwire_device_count': len(sdw),
          'unexpected_soundwire_devices': unexpected,
          'scoped_failure_reasons': reasons,
          'logical_attached_slaves': attached,
          'codec_mechanism_passed': mechanism,
          'system_baseline_passed': baseline,
          'scoped_passed': result['passed_scoped_baseline'],
          'fallback_stopped': action['fallback_stopped'],
          'persistent_default': 'spx-known-good',
          'next_entry_empty': True, 'efi_bootnext_absent': True,
          'playback_verified': False}
(X / 'independent-result-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
