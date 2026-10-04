#!/usr/bin/python3
"""Rehash AU result; v2 uses the explicit-reuse archive build_links_verified key."""

import hashlib
import json
import os
import re
import subprocess
from au_camera_core import decode, complete_trial_findings
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261003au'
RELEASE = '7.3.0-rc2-spx-mainline-20261003au+'


def command_history_summary(kernel, params):
    lines = [line.split('SPX cmd diag ', 1)[1] for line in kernel.splitlines()
             if 'qcom-soundwire' in line and 'SPX cmd diag ' in line]
    dumps, malformed = [], []
    header = re.compile(r'history count=(\d+) submission-only')
    record = re.compile(r'seq=(\d+) submitted_ns=(\d+) op=([RW]) packed=([0-9a-f]{8}) bridge_rc=(-?\d+)')
    for line in lines:
        h, r = header.fullmatch(line), record.fullmatch(line)
        if h:
            dumps.append({'declared_count': int(h[1]), 'records': []})
        elif r and dumps:
            packed = int(r[4], 16)
            dumps[-1]['records'].append({'sequence': int(r[1]), 'submitted_ns': int(r[2]),
                'op': r[3], 'packed': r[4], 'bridge_rc': int(r[5]),
                'address': packed & 0xffff, 'command_id': (packed >> 16) & 15,
                'device_number': (packed >> 20) & 15, 'data_or_length': packed >> 24})
        else:
            malformed.append(line)
    good = not malformed and len(dumps) <= 2 and len(lines) <= 34
    for d in dumps:
        rs = d['records']
        good = good and 1 <= d['declared_count'] <= 16 and len(rs) == d['declared_count']
        good = good and all(b['sequence'] == a['sequence'] + 1 and
                            b['submitted_ns'] >= a['submitted_ns'] for a, b in zip(rs, rs[1:]))
    return {'enabled': params.get('spx_cmd_diag') == 'Y', 'well_formed': bool(good),
            'line_count': len(lines), 'dumps': dumps, 'malformed_lines': malformed,
            'maximum_lines': 34, 'hardware_acknowledgment_verified': False}


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
assert a['attempt'] == '20261003au' and a['release'] == RELEASE
result_root = X / 'final-result'
expected = json.loads((result_root / 'sha256.json').read_text())
actual = files(result_root)
assert actual == expected | {'sha256.json': sha(result_root / 'sha256.json')}
result = json.loads((result_root / 'result.json').read_text())
action = json.loads((X / 'finalizer-action.json').read_text())
assert result['attempt'] == '20261003au'
assert action['boot_id'] == result['boot_id']
assert action['result_sha256'] == sha(result_root / 'result.json')
assert action['manifest_sha256'] == sha(result_root / 'sha256.json')
assert action['files_verified'] == len(expected)
assert result['release'] == RELEASE
assert (result_root / 'cmdline').read_text().split() == \
    ['BOOT_IMAGE=/spx-trial-20261003au/vmlinuz'] + a['cmdline'].split()
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
declared = {'sdw:0:0:0217:2110:00:3', 'sdw:0:0:0217:2110:00:4'}
unexpected = sorted(set(sdw) - declared)
build = json.loads((X / 'build-sha256.json').read_text())
build_links = json.loads((X / 'build-symlinks.json').read_text())
archive = json.loads((X / 'archive-review.json').read_text())
assert len(build) == a['build_files_verified'] and len(build_links) == a['build_links_verified']
assert files(X / 'build') == build and links(X / 'build') == build_links
modules = json.loads((X / 'build/module-sha256.json').read_text())
assert len(modules) == 208
assert files(Path('/usr/lib/modules') / RELEASE) == modules
for name, digest in json.loads((X / 'build/dtb-sha256.json').read_text()).items():
    assert sha(X / 'build/dtb-build' / name) == digest, name
for name, digest in (a['sha256'] | a['recovery_sha256'] |
                     a['runtime_sha256']).items():
    assert sha(name) == digest, name
env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'],
                              text=True, timeout=30).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True,
                                                 timeout=30)
right_init = kernel.count('wsa881x-codec sdw:0:0:0217:2110:00:4: SPX: initializing amplifier at SoundWire device 1')
assert result['right_wsa_cold_init_markers'] == right_init
mechanism = (right_init >= 1 and result['wsa_write_overflows'] == 0 and
             result['wsa_read_underflows'] == 0 and
             result['wsa_status_update_failures'] == 0 and
             result['wsa_slave_init_failures'] == 0 and
             result['wsa_cold_init_markers'] >= 1 and attached >= 1 and
             result['soundcards_present'])
baseline = (result['fd680_renderer'] and result['wifi_connected'] and
            result['spi_hid_ready'] and result['kernel_taint'] == '0' and
            not result['kernel_fault_lines'])
assert action['fallback_stopped'] is False
assert result['sustained_gpu_pending'] and result['hardware_acceptance_closed'] is False
registers = json.loads((result_root / 'wcd-gpio-registers.json').read_text())
wcd_params = json.loads((result_root / 'wcd-params.json').read_text())
wsa_params = json.loads((result_root / 'wsa-params.json').read_text())
assert result['gpio_software_state_passed'] == (
    registers == {'0042': 4, '0043': 28}
    and wcd_params == {'spx_wsa_en_pin': '2', 'spx_wsa_gpio_dir': '-1', 'spx_wsa_gpio_val': '-1'}
    and wsa_params.get('spx_swap_dac_master_ports') == 'N'
    and kernel.count('SPX: forced wcd-gpio pin 2 output-high') == 1)
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
declared_pass = (declared <= set(sdw) and
                 all(sdw[n]['driver'] == 'wsa881x-codec' and sdw[n]['of_node'] for n in declared) and
                 not unexpected and
                 all(sdw[n]['driver'] is None and sdw[n]['status'] == 'UNATTACHED' and sdw[n]['device_number'] == 'N/A' for n in unexpected))
assert result['declared_topology_preserved'] == declared_pass
topology_pass = len(result['slim_devices']) == 2 and declared_pass
swr_params = json.loads((result_root / 'swr-params.json').read_text())
raw_trace = [line for line in kernel.splitlines() if 'SPX enum diag slot=' in line and ' words=' in line]
decoded_trace = [line for line in kernel.splitlines() if 'SPX enum diag slot=' in line and ' decoded=' in line]
identity_pass = (swr_params.get('spx_enum_diag') == 'Y' and 1 <= len(raw_trace) <= 8 and 1 <= len(decoded_trace) <= len(raw_trace) and any('rc=0/0' in line for line in raw_trace) and any('slot=1 decoded=0217:2110 unique=4' in line for line in decoded_trace))
assert result['identity_diagnostic_passed'] == identity_pass
assert result['enumeration_raw_log_count'] == len(raw_trace)
assert result['enumeration_decoded_log_count'] == len(decoded_trace)
assert result['extra_soundwire_devices'] == unexpected
assert (result_root / 'enumeration-trace.log').read_text() == '\n'.join(raw_trace + decoded_trace) + '\n'
force_pass = (result['force_attach_worker_entries'] == 0 and
              result['force_attach_done_markers'] == 0 and
              result['force_attach_slave_markers'] == 0 and
              result['wsa_enumerated_mode'] == 'Y')
right = sdw.get('sdw:0:0:0217:2110:00:4', {})
firmware_match = (right.get('status', '').casefold() == 'attached' and right.get('device_number') == '1' and (right.get('of_node') or '').endswith('/speaker@0,4'))
assert result['firmware_identity_match_passed'] == firmware_match
native_errors = re.findall(r'^.*qcom-soundwire.*(?:FIFO.*(?:underflow|overflow)|SWR CMD error|bus clsh|Port collision|link failed to connect|clock stop failed|bus failed to exit clock stop|unknown interrupt).*$', kernel, re.M | re.I)
assert native_errors == result['native_bus_error_lines']
native_path = (swr_params.get('spx_force_attach') == '0' and swr_params.get('spx_core_enum') == '0' and
               swr_params.get('spx_watchdog') == '0' and swr_params.get('spx_exact_windows_init') == 'N' and
               kernel.count('SPX enum work enter') == 0 and result['force_attach_done_markers'] == 0 and
               result['force_attach_slave_markers'] == 0 and
               all('force_pending=0 forced=0' in line for line in raw_trace) and not native_errors)
assert result['native_force_off_path_passed'] == native_path
pm = json.loads((result_root / 'runtime-pm.json').read_text())
assert len(pm) == result['runtime_pm_snapshot_paths'] and pm
touch_params = json.loads((result_root / 'touch-params.json').read_text())
touch_lines = [line for line in kernel.splitlines()
               if 'spi_hid spi0.0:' in line and 'startup-diag:' in line]
windows = {}
for line in touch_lines:
    fields = dict(re.findall(r'([a-z-]+)=([a-z0-9-]+)', line))
    assert 'window' in fields and 'event' in fields
    windows.setdefault(fields['window'], []).append(fields['event'])
touch_diag_passed = (touch_params.get('startup_diag') == 'Y' and
                     1 <= len(touch_lines) <= 384 and 1 <= len(windows) <= 8 and
                     all(1 <= int(w) <= 8 and len(events) <= 48 and events[0] == 'begin'
                         and events.count('begin') == 1 for w, events in windows.items()))
assert result['touch_startup_diagnostic_passed'] == touch_diag_passed
assert result['touch_startup_diagnostic_lines'] == len(touch_lines)
assert result['touch_startup_windows'] == windows
assert result['touch_diagnostic_limit_windows'] == 8 and result['touch_diagnostic_limit_events_per_window'] == 48
assert (result_root / 'touch-startup.log').read_text() == '\n'.join(touch_lines) + '\n'
touch_state = json.loads((result_root / 'touch-state.json').read_text())
assert result['touch_state'] == touch_state
assert result['spi_hid_ready'] == (touch_state.get('ready') == 'ready')
assert result['touch_startup_open_timeouts'] == kernel.count('spi_hid_ll_open: firmware did not become ready')
assert result['touch_startup_invalid_headers'] == kernel.count('Invalid input report sync constant')
assert result['touch_startup_clean'] == (not any(x in kernel for x in ('spi_hid_ll_open: firmware did not become ready', 'Invalid input report sync constant', 'startup response polling timed out')))
paired = re.compile(r'SPX enum diag slot=(\d+).*?rc=0/0 words=[0-9a-f]{8}/[0-9a-f]{8}\n.*?SPX enum diag slot=\1 decoded=0217:(?:2010|2110) unique=[34] version=[0-9a-f]+ class=[0-9a-f]+')
trace = '\n'.join(line for line in kernel.splitlines() if 'SPX enum diag slot=' in line)
pin2_diagnostic = (result['gpio_software_state_passed'] and native_path and
                   swr_params.get('spx_enum_diag') == 'Y' and
                   1 <= len(raw_trace) <= 8 and 1 <= len(decoded_trace) <= len(raw_trace) and
                   bool(paired.search(trace)) and power_pass and controller_pass and
                   touch_diag_passed and baseline)
assert result['pin2_enumeration_diagnostic_passed'] == pin2_diagnostic
assert result['pin2_diagnostic_controls_fallback'] is False
cmd_history = command_history_summary(kernel, swr_params)
assert json.loads((result_root / 'command-history.json').read_text()) == cmd_history == result['command_history']
cmd_diag_passed = cmd_history['enabled'] and cmd_history['well_formed']
assert result['command_diagnostic_passed'] == cmd_diag_passed
expected_pass = (cmd_diag_passed and touch_diag_passed and native_path and firmware_match and identity_pass and result['gpio_software_state_passed'] and power_pass and
                 controller_pass and topology_pass and force_pass and
                 mechanism and baseline)
assert result['passed_scoped_baseline'] == expected_pass
camera_findings = {'camera_control_initial_passed': False, 'camera_control_final_passed': False,
                   'camera_observations_ordered': False, 'camera_control_passed': False,
                   'camera_provider_idle_passed': False, 'camera_trial_passed': False}
roots = [result_root / name for name in ('camera-control-result', 'camera-control-final-result', 'camera-provider-result')]
if all((root / 'sha256.json').is_file() for root in roots):
    documents = []
    for root in roots:
        h = json.loads((root / 'sha256.json').read_text())
        assert files(root) == h | {'sha256.json': sha(root / 'sha256.json')}
        documents.append(json.loads((root / 'report.json').read_text()))
    reference_root = BASE / 'attempts/20261002ap/camera-pmic-metadata-20261003'
    assert sha(reference_root / 'sha256.json') == '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
    for name, digest in json.loads((reference_root / 'sha256.json').read_text()).items():
        assert sha(reference_root / name) == digest
    reference = decode(json.loads((reference_root / 'result.json').read_text())['reads'])
    camera_findings = complete_trial_findings(documents[0], documents[1], documents[2], reference, {
        'boot_id': result['boot_id'], 'release': RELEASE, 'taint': result['kernel_taint'],
        'cmdline': (result_root / 'cmdline').read_text().strip()})
for key, value in camera_findings.items():
    assert result[key] == value
assert result['passed_trial'] == bool(expected_pass and camera_findings['camera_trial_passed'])
reasons = [name for name, passed in (
    ('bounded command diagnostic', cmd_diag_passed),
    ('bounded touch startup diagnostic', touch_diag_passed),
    ('GPIO software state', result['gpio_software_state_passed']),
    ('DSP power path', power_pass), ('controller startup', controller_pass),
    ('right firmware identity matching', firmware_match),
    ('bounded identity diagnostic', identity_pass),
    ('declared devices and permitted unbound identity', topology_pass),
    ('force path absent', force_pass), ('native bus/clock-stop path', native_path), ('codec initialization', mechanism),
    ('graphics/Wi-Fi/touch baseline', baseline)) if not passed]
report = {'attempt': '20261003au', 'boot_id': result['boot_id'],
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
          'pin2_enumeration_diagnostic_passed': pin2_diagnostic,
          'pin2_diagnostic_controls_fallback': False,
          'gpio_register_view': registers,
          'soundwire_device_count': len(sdw),
          'extra_soundwire_devices': unexpected,
          'identity_diagnostic_passed': identity_pass,
          'firmware_identity_match_passed': firmware_match,
          'native_force_off_path_passed': native_path,
          'native_bus_error_lines': native_errors,
          'runtime_pm_snapshot_paths': len(pm),
          'enumeration_raw_log_count': len(raw_trace),
          'enumeration_decoded_log_count': len(decoded_trace),
          'scoped_failure_reasons': reasons,
          'touch_startup_diagnostic_passed': touch_diag_passed,
          'touch_startup_diagnostic_lines': len(touch_lines),
          'touch_startup_windows': windows,
          'touch_startup_clean': result['touch_startup_clean'],
          'touch_startup_open_timeouts': result['touch_startup_open_timeouts'],
          'touch_startup_invalid_headers': result['touch_startup_invalid_headers'],
          'logical_attached_slaves': attached,
          'codec_mechanism_passed': mechanism,
          'right_wsa_cold_init_markers': right_init,
          'command_diagnostic_passed': cmd_diag_passed,
          'command_history': cmd_history,
          'system_baseline_passed': baseline,
          'scoped_passed': result['passed_scoped_baseline'], 'trial_passed': result['passed_trial'], **camera_findings,
          'fallback_stopped': action['fallback_stopped'],
          'persistent_default': 'spx-known-good',
          'next_entry_empty': True, 'efi_bootnext_absent': True,
          'playback_verified': False}
(X / 'independent-result-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
