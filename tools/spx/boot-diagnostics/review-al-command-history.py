#!/usr/bin/python3
"""Decode frozen submissions independently using little-endian protocol bytes."""
import hashlib
import json
import os
from pathlib import Path
import re

os.umask(0o077)
run = Path('/var/lib/spx-boot-diagnostics/attempts/20260930al')
root = run / 'final-result'
out = run / 'command-history-review.json'
assert os.geteuid() == 0 and not out.exists()
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
manifest = json.loads((root / 'sha256.json').read_text())
assert {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
        if p.is_file() and not p.is_symlink()} == manifest | {'sha256.json': sha(root / 'sha256.json')}
result = json.loads((root / 'result.json').read_text())
assert result['boot_id'] == 'c812b302-6fc7-4ad2-9a9a-a1fff17ef4e6'
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
assert 0 <= len(dumps) <= 2 and len(lines) <= 34
for d in dumps:
    rs = d['records']
    assert len(rs) == d['declared_count'] and 1 <= len(rs) <= 16
    assert all(b['sequence'] == a['sequence'] + 1 and b['submitted_ns'] >= a['submitted_ns']
               for a, b in zip(rs, rs[1:]))
assert dumps == result['command_history']['dumps']
assert result['command_diagnostic_passed'] and result['command_history']['well_formed']
errors = [s for s in raw.splitlines() if 'qcom-soundwire' in s and 'SWR CMD error' in s]
report = {'attempt': '20260930al', 'boot_id': result['boot_id'],
    'final_manifest_sha256': sha(root / 'sha256.json'), 'independently_decoded_dumps': dumps,
    'raw_command_errors': errors, 'history_dump_count': len(dumps), 'history_line_count': len(lines),
    'hardware_acknowledgment_verified': False,
    'no_error_triggered_dump_is_allowed': True,
    'limits': ['Bridge return zero records software submission, not codec or controller acknowledgment.',
               'The last submission is not proved to be the cause of an asynchronous command error.',
               'No caller, codec identity, physical GPIO level or routing is traced.',
               'submitted_ns uses ktime; raw dmesg uses a different clock. Absolute times are not compared.',
               'No live mixer, PCM, capture, input-event, reset or rebind operation is performed.']}
out.write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
