#!/usr/bin/python3
"""Interpret frozen AD startup failure separately from final scoped readiness."""
import hashlib
import json
import os
from pathlib import Path
import re

os.umask(0o077)
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ad')
OUT = RUN / 'touch-startup-review.json'
assert os.geteuid() == 0 and not OUT.exists()

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

for name in ('final-result', 'startup-discovery'):
    root = RUN / name
    hashes = json.loads((root / 'sha256.json').read_text())
    actual = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
              if p.is_file() and not p.is_symlink()}
    assert actual == hashes | {'sha256.json': sha(root / 'sha256.json')}
final = RUN / 'final-result'
result = json.loads((final / 'result.json').read_text())
snapshot = RUN / 'startup-discovery'
discovery = json.loads((snapshot / 'report.json').read_text())
assert result['boot_id'] == discovery['boot_id'] == '86c3ff68-09a9-480c-9288-be9443254378'
raw = (snapshot / 'dmesg-raw.log').read_text()
config = (RUN / 'build/artifacts/.config').read_text()
assert 'CONFIG_HZ=1000\n' in config
windows = {}
for line in raw.splitlines():
    if 'spi_hid spi0.0: startup-diag:' not in line:
        continue
    record = dict(re.findall(r'([a-z-]+)=([a-z0-9-]+)', line))
    record['kernel_seconds'] = float(re.search(r'\[\s*(\d+\.\d+)\]', line)[1])
    windows.setdefault(record['window'], []).append(record)
assert set(windows) == {'1', '2', '3', '4'}
assert sum(map(len, windows.values())) == result['touch_startup_diagnostic_lines'] == 76
summary = {}
for n, records in windows.items():
    assert len(records) <= 48 and records[0]['event'] == 'begin'
    assert [r['event'] for r in records] == result['touch_startup_windows'][n]
    deassert = next(r for r in records if r['event'] == 'reset-deassert')
    powered = [r for r in records if r['event'] == 'irq' and r['powered'] == '1']
    accepted = [int(r['value']) for r in records if r['event'] == 'report']
    gated = [r for r in records if r['event'] == 'irq' and r['powered'] == '0']
    terminal = records[-1]
    assert terminal['event'] in ('ready', 'timeout')
    summary[n] = {'records': len(records), 'terminal': terminal['event'],
                  'accepted_report_types': accepted,
                  'powered_irq_count': len(powered), 'gated_irq_count': len(gated),
                  'polls': int(terminal['poll']), 'headers': int(terminal['header']),
                  'reset_responses': int(terminal['reset']), 'descriptors': int(terminal['desc']),
                  'suppressed_records': int(terminal['suppressed']),
                  'reset_deassert_kernel_seconds': deassert['kernel_seconds'],
                  'first_powered_irq_kernel_seconds': powered[0]['kernel_seconds'] if powered else None,
                  'deassert_to_powered_irq_jiffies': int(powered[0]['now']) - int(deassert['now']) if powered else None,
                  'terminal_kernel_seconds': terminal['kernel_seconds'],
                  'armed_deadline_present': any(r['event'] == 'arm' for r in records)}
    if n in ('1', '2', '3'):
        assert accepted == [3, 7, 8] and terminal['event'] == 'ready'
        assert int(terminal['poll']) == 0 and len(powered) == 3
    else:
        assert terminal['event'] == 'timeout' and not powered and not accepted
        assert len(gated) == 1 and int(terminal['poll']) == int(terminal['header']) == 3
        assert all(r['ret'] == '0' and r['value'] == '9' for r in records if r['event'] == 'header')
assert raw.count('spi_hid_ll_open: firmware did not become ready: -110') == 1
assert raw.count('Invalid input report sync constant (0x0)') == 3
opens = [line for line in raw.splitlines() if 'spi_hid_ll_open:' in line]
assert len(opens) == 4 and 'firmware did not become ready' in opens[-2] and 'd3 -> d0' in opens[-1]
state = json.loads((final / 'touch-state.json').read_text())
assert state['bus_error_count'] == '3 (-22)'
assert state['regulator_error_count'] == state['logic_error_count'] == '0 (0)'
assert state['device_initiated_reset_count'] == '0'
assert state['ready'] == 'ready' and result['spi_hid_ready']
report = {'attempt': '20260930ad', 'boot_id': result['boot_id'],
          'final_result_manifest_sha256': sha(final / 'sha256.json'),
          'startup_snapshot_manifest_sha256': sha(snapshot / 'sha256.json'),
          'windows': summary, 'final_touch_state': state,
          'final_scoped_baseline_passed': result['passed_scoped_baseline'],
          'clean_touch_startup': False, 'logged_failed_open_count': 1,
          'failed_open_then_later_success_observed': True,
          'open_lines_raw': opens, 'no_manual_restart_rebind_reset_or_pcm': True,
          'limits': ['Three successful startup sequences are within one boot, not independent fresh boots.',
                     'Window4 is the last logged window; the later successful open lacks startup metadata.',
                     'Similar gated early IRQs occur before successful windows2/3 and failed window4.',
                     'A gated handler invocation does not identify usable firmware data or establish an electrical edge.',
                     'No process identity was traced for the opens; NRestarts counts systemd restarts only.',
                     'Journal reception timestamps differ from raw kernel timestamps; timing here uses raw dmesg and jiffies.',
                     'Ready at620s establishes the frozen scope, not startup reliability or a fix for missing response.']}
OUT.write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps({'boot_id': result['boot_id'], 'scoped_passed': result['passed_scoped_baseline'],
                  'clean_touch_startup': False, 'windows': summary,
                  'review_sha256': sha(OUT)}, indent=2))
