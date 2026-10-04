#!/usr/bin/python3
"""Decode frozen submissions independently using little-endian protocol bytes."""
import hashlib
import json
import os
from pathlib import Path
import re

os.umask(0o077)
run = Path('/var/lib/spx-boot-diagnostics/attempts/20260930aj')
root = run / 'final-result'
out = run / 'command-history-review.json'
assert os.geteuid() == 0 and not out.exists()
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
manifest = json.loads((root / 'sha256.json').read_text())
assert {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
        if p.is_file() and not p.is_symlink()} == manifest | {'sha256.json': sha(root / 'sha256.json')}
result = json.loads((root / 'result.json').read_text())
assert result['boot_id'] == '66c4697f-70f5-4b02-bc76-da46c97afdfd'
raw = (root / 'dmesg-raw.log').read_text()
dumps = []
lines = [s.split('SPX cmd diag ', 1)[1] for s in raw.splitlines()
         if 'qcom-soundwire' in s and 'SPX cmd diag ' in s]
for s in lines:
    header = re.fullmatch(r'history count=(\d+) submission-only', s)
    if header:
        dumps.append({'declared_count': int(header[1]), 'records': []})
        continue
    m = re.fullmatch(r'seq=(\d+) submitted_ns=(\d+) op=([RW]) packed=([0-9a-f]{8}) bridge_rc=(-?\d+)', s)
    assert m and dumps, s
    b = int(m[4], 16).to_bytes(4, 'little')
    dumps[-1]['records'].append({'sequence': int(m[1]), 'submitted_ns': int(m[2]),
        'op': m[3], 'packed': m[4], 'bridge_rc': int(m[5]),
        'address': b[0] + 256*b[1], 'command_id': b[2] % 16,
        'device_number': b[2] // 16, 'data_or_length': b[3]})
assert 1 <= len(dumps) <= 2 and len(lines) <= 34
for d in dumps:
    rs = d['records']
    assert len(rs) == d['declared_count'] and 1 <= len(rs) <= 16
    assert all(b['sequence'] == a['sequence'] + 1 and b['submitted_ns'] >= a['submitted_ns']
               for a, b in zip(rs, rs[1:]))
assert dumps == result['command_history']['dumps']
assert result['command_diagnostic_passed'] and result['command_history']['well_formed']
rs = dumps[0]['records']
assert [r['sequence'] for r in rs] == list(range(41, 57))
assert all(r['op'] == 'W' and r['bridge_rc'] == 0 for r in rs)
assert all(r['device_number'] == 1 for r in rs[:-1])
assert rs[-1]['packed'] == '980b312a' and rs[-1]['device_number'] == 0 and rs[-1]['address'] == 0x312a
errors = [s for s in raw.splitlines() if 'qcom-soundwire' in s and 'SWR CMD error' in s]
assert errors and not result['native_force_off_path_passed']
report = {'attempt': '20260930aj', 'boot_id': result['boot_id'],
    'final_manifest_sha256': sha(root / 'sha256.json'), 'independently_decoded_dumps': dumps,
    'raw_command_errors': errors, 'penultimate_to_last_submission_ns': rs[-1]['submitted_ns'] - rs[-2]['submitted_ns'],
    'last_submission_is_device_zero_boost_enable_register_write': True,
    'limits': ['Bridge return zero records software submission, not codec or controller acknowledgment.',
               'The last submission is not proved to be the cause of an asynchronous command error.',
               'No caller, codec identity, physical GPIO level or routing is traced.',
               'submitted_ns uses ktime; raw dmesg uses a different clock. Absolute times are not compared.',
               'No live mixer, PCM, capture, input-event, reset or rebind operation is performed.']}
out.write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
