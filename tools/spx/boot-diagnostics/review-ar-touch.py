#!/usr/bin/python3
"""Decode frozen AR startup metadata without accessing input events or hardware."""
import hashlib
import json
import os
from pathlib import Path
import re

os.umask(0o077)
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ar')
ROOT = RUN / 'final-result'
OUT = RUN / 'touch-startup-review.json'
assert os.geteuid() == 0 and not OUT.exists()

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

hashes = json.loads((ROOT / 'sha256.json').read_text())
actual = {str(p.relative_to(ROOT)): sha(p) for p in sorted(ROOT.rglob('*'))
          if p.is_file() and not p.is_symlink()}
assert actual == hashes | {'sha256.json': sha(ROOT / 'sha256.json')}
result = json.loads((ROOT / 'result.json').read_text())
a = json.loads((RUN / 'attempt.json').read_text())
assert result['attempt'] == a['attempt'] == '20261003ar'
assert result['release'] == a['release'] == '7.3.0-rc2-spx-mainline-20261003ar+'
assert result['boot_id'] != a['preboot_id']
assert (ROOT / 'cmdline').read_text().split() == ['BOOT_IMAGE=/spx-trial-20261003ar/vmlinuz'] + a['cmdline'].split()
raw = (ROOT / 'dmesg-raw.log').read_text()
assert 'CONFIG_HZ=1000\n' in (RUN / 'build/artifacts/.config').read_text()
windows = {}
for line in raw.splitlines():
    if 'spi_hid spi0.0: startup-diag:' not in line:
        continue
    record = dict(re.findall(r'([a-z-]+)=([a-z0-9-]+)', line))
    record['kernel_seconds'] = float(re.search(r'\[\s*(\d+\.\d+)\]', line)[1])
    windows.setdefault(record['window'], []).append(record)
assert 1 <= len(windows) <= 8
assert sum(map(len, windows.values())) == result['touch_startup_diagnostic_lines'] <= 384
summary = {}
for n, records in windows.items():
    assert 1 <= int(n) <= 8 and len(records) <= 48 and records[0]['event'] == 'begin'
    assert [r['event'] for r in records] == result['touch_startup_windows'][n]
    anchors = {name: next((r for r in records if r['event'] == name), None)
               for name in ('reset-assert', 'regulator-enable', 'reset-deassert')}
    deassert = anchors['reset-deassert']

    def interval(left, right):
        start, end = anchors[left], anchors[right]
        return int(end['now']) - int(start['now']) if start and end else None

    powered = [r for r in records if r['event'] == 'irq' and r['powered'] == '1']
    gated = [r for r in records if r['event'] == 'irq' and r['powered'] == '0']
    accepted = [int(r['value']) for r in records if r['event'] == 'report']
    terminal = records[-1]
    terminal_complete = terminal['event'] in ('ready', 'timeout', 'power-down')
    summary[n] = {'records': len(records), 'terminal': terminal['event'],
                  'accepted_report_types': accepted,
                  'powered_irq_count': len(powered), 'gated_irq_count': len(gated),
                  'polls': int(terminal['poll']), 'headers': int(terminal['header']),
                  'reset_responses': int(terminal['reset']), 'descriptors': int(terminal['desc']),
                  'suppressed_records': int(terminal['suppressed']),
                  'terminal_record_present': terminal_complete,
                  'missing_power_anchors': [name for name, r in anchors.items() if r is None],
                  'power_anchor_return_codes': {name: int(r['ret']) for name, r in anchors.items() if r},
                  'assert_to_enable_return_ms': interval('reset-assert', 'regulator-enable'),
                  'enable_return_to_deassert_ms': interval('regulator-enable', 'reset-deassert'),
                  'assert_to_deassert_ms': interval('reset-assert', 'reset-deassert'),
                  'reset_deassert_kernel_seconds': deassert['kernel_seconds'] if deassert else None,
                  'first_powered_irq_kernel_seconds': powered[0]['kernel_seconds'] if powered else None,
                  'deassert_to_powered_irq_jiffies': int(powered[0]['now']) - int(deassert['now']) if powered and deassert else None,
                  'terminal_kernel_seconds': terminal['kernel_seconds'],
                  'armed_deadline_present': any(r['event'] == 'arm' for r in records)}
clean = all(s['terminal'] == 'ready' and s['accepted_report_types'] == [3, 7, 8]
            and s['powered_irq_count'] == 3 and s['polls'] == 0
            and s['suppressed_records'] == 0 for s in summary.values())
opens = [line for line in raw.splitlines() if 'spi_hid_ll_open:' in line]
timeouts = raw.count('spi_hid_ll_open: firmware did not become ready')
invalid = raw.count('Invalid input report sync constant')
assert timeouts == result['touch_startup_open_timeouts']
assert invalid == result['touch_startup_invalid_headers']
assert result['touch_startup_clean'] == (not timeouts and not invalid and
                                        'startup response polling timed out' not in raw)
state = json.loads((ROOT / 'touch-state.json').read_text())
report = {'attempt': '20261003ar', 'boot_id': result['boot_id'],
          'final_result_manifest_sha256': sha(ROOT / 'sha256.json'),
          'windows': summary, 'final_touch_state': state,
          'final_scoped_baseline_passed': result['passed_scoped_baseline'],
          'clean_logged_sequences': clean, 'clean_touch_startup': result['touch_startup_clean'],
          'logged_failed_open_count': timeouts, 'invalid_header_count': invalid,
          'open_lines_raw': opens, 'no_manual_restart_rebind_reset_or_pcm': True,
          'limits': ['All sequences belong to one boot; they are not independent reliability trials.',
                     'Software timing includes scheduling and existing 10ms pre-enable settling; it does not measure electrical rails or prove causality.',
                     'Software powered=0 handler invocations do not prove usable data or electrical edges.',
                     'Open caller identities are not traced; systemd NRestarts counts systemd restarts only.',
                     'Timing uses raw dmesg and jiffies, not journal reception timestamps.',
                     'Final readiness is the archived state; earlier ready records do not establish readiness at620s.',
                     'The startup-delay applies to the first hardware rail enable; another consumer may bypass it.']}
OUT.write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
