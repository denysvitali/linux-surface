#!/usr/bin/python3
"""Compare archived touch transitions without reading live input or resetting it."""
import hashlib
import json
import os
from pathlib import Path
import re

os.umask(0o077)
base = Path('/var/lib/spx-boot-diagnostics/attempts')
out = Path('/var/tmp/spx-touch-output-bounds-20261002/touch-reopen-audit.json')
assert os.geteuid() == 0 and not out.exists()


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


report = {}
for attempt in ('20261001am', '20261002ao', '20261002ap'):
    root = base / attempt / 'final-result'
    manifest = json.loads((root / 'sha256.json').read_text())
    actual = {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
              if p.is_file() and not p.is_symlink()}
    assert actual == manifest | {'sha256.json': sha(root / 'sha256.json')}
    result = json.loads((root / 'result.json').read_text())
    touch = json.loads((base / attempt / 'touch-startup-review.json').read_text())
    assert touch['final_result_manifest_sha256'] == sha(root / 'sha256.json')
    assert touch['boot_id'] == result['boot_id']
    windows, last_down = {}, None
    for line in (root / 'dmesg-raw.log').read_text().splitlines():
        if 'spi_hid spi0.0:' not in line:
            continue
        seconds = float(re.search(r'\[\s*(\d+\.\d+)\]', line)[1])
        if 'd0 -> d3' in line:
            last_down = dict(seconds=seconds, line=line)
        if 'startup-diag:' not in line:
            continue
        fields = dict(re.findall(r'([a-z-]+)=([a-z0-9-]+)', line))
        number = fields['window']
        if fields['event'] == 'begin':
            assert number not in windows
            windows[number] = dict(begin_seconds=seconds, previous_logged_down=last_down,
                                   logged_down_to_begin_ms=(seconds-last_down['seconds'])*1000
                                   if last_down else None, events=[])
        windows[number]['events'].append(fields | dict(seconds=seconds))
    summary = {}
    for number, window in windows.items():
        events = window.pop('events')
        operations = {name: next(e for e in events if e['event'] == name)
                      for name in ('reset-assert', 'regulator-enable', 'reset-deassert')}
        window['setup_return_codes'] = {n: int(e['ret']) for n, e in operations.items()}
        window['assert_to_deassert_ms'] = (operations['reset-deassert']['seconds']-
                                          operations['reset-assert']['seconds'])*1000
        window['terminal'] = events[-1]['event']
        window['powered_irqs'] = sum(e['event'] == 'irq' and e['powered'] == '1' for e in events)
        window['accepted_reports'] = [int(e['value']) for e in events if e['event'] == 'report']
        assert window['terminal'] == touch['windows'][number]['terminal']
        summary[number] = window
    report[attempt] = dict(boot_id=result['boot_id'], manifest_sha256=sha(root/'sha256.json'),
                           windows=summary)
report['limits'] = [
    'Logged software returns and timestamps do not measure electrical rail or GPIO state.',
    'The logger ends at ready; sleep-state selection and regulator-disable outcomes are not retained per close.',
    'The caller identities are not recorded; close messages occur after power-down, not at its start.',
    'AO has a failed reopen after a longer gap than its successful reopen; a simple minimum gap does not explain these samples.',
    'Command output bounds defects are separate findings and do not explain AO silence before any descriptor command.']
out.write_text(json.dumps(report, indent=2)+'\n')
for attempt, finding in report.items():
    if isinstance(finding, dict):
        for number, window in finding['windows'].items():
            print(attempt, number, window['terminal'], 'gap_ms=', window['logged_down_to_begin_ms'],
                  'reset_ms=', round(window['assert_to_deassert_ms'], 3),
                  'returns=', window['setup_return_codes'], 'powered_irqs=', window['powered_irqs'])
