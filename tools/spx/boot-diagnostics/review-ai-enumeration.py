#!/usr/bin/python3
"""Independently decode AI's archived controller-table words; never touch hardware."""
import hashlib
import json
import os
from pathlib import Path
import re

os.umask(0o077)
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ai')
SOURCE = RUN / 'final-result'
OUT = RUN / 'enumeration-word-review.json'
assert SOURCE.is_dir() and not OUT.exists()
manifest = json.loads((SOURCE / 'sha256.json').read_text())
for name, digest in manifest.items():
    assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest, name
kernel = (SOURCE / 'kernel.log').read_text()
raw_re = re.compile(r'SPX enum diag slot=(\d+) status_snapshot=(0x[0-9a-f]+|0) used_status=(\d+) force_pending=(\d+) forced=(\d+) rc=(-?\d+)/(-?\d+) words=([0-9a-f]{8})/([0-9a-f]{8})')
dec_re = re.compile(r'SPX enum diag slot=(\d+) decoded=([0-9a-f]{4}):([0-9a-f]{4}) unique=([0-9a-f]+) version=([0-9a-f]+) class=([0-9a-f]+)')
transactions = []
pending = None
for line in kernel.splitlines():
    raw = raw_re.search(line)
    dec = dec_re.search(line)
    if raw:
        slot, status, used, force_pending, forced, rc1, rc2, w1, w2 = raw.groups()
        word1, word2 = int(w1, 16), int(w2, 16)
        # Recover the six ID bytes in protocol order independently of FIELD_GET.
        low = word1.to_bytes(4, 'little')
        high = word2.to_bytes(4, 'little')
        id_bytes = low + high[:2]
        identity = {'version': id_bytes[0] >> 4, 'unique_id': id_bytes[0] & 15,
                    'manufacturer': (id_bytes[1] << 8) | id_bytes[2],
                    'part': (id_bytes[3] << 8) | id_bytes[4], 'class': id_bytes[5]}
        pending = {'slot': int(slot), 'raw_status_snapshot': int(status, 0),
                   'raw_slot_status': (int(status, 0) >> (int(slot) * 2)) & 3,
                   'used_status': int(used), 'force_pending': bool(int(force_pending)),
                   'forced': bool(int(forced)), 'read_return_codes': [int(rc1), int(rc2)],
                   'words': [w1, w2], 'id_bytes_hex': id_bytes.hex(' '),
                   'independent_decoded_id': identity if int(rc1) == int(rc2) == 0 else None,
                   'decoded_line_matches': None, 'raw_line': line}
        transactions.append(pending)
    if dec:
        assert pending is not None, 'Decoded line without preceding raw transaction'
        slot, mfg, part, unique, version, class_id = dec.groups()
        decoded = {'version': int(version, 16), 'unique_id': int(unique, 16),
                   'manufacturer': int(mfg, 16), 'part': int(part, 16), 'class': int(class_id, 16)}
        assert int(slot) == pending['slot'] and decoded == pending['independent_decoded_id']
        pending['decoded_line_matches'] = True
        pending['decoded_line'] = line
        pending = None
assert 1 <= len(transactions) <= 8
assert sum(t['decoded_line_matches'] is True for t in transactions) >= 1
result = json.loads((SOURCE / 'result.json').read_text())
report = {'attempt': '20260930ai', 'boot_id': result['boot_id'],
          'result_manifest_sha256': hashlib.sha256((SOURCE / 'sha256.json').read_bytes()).hexdigest(),
          'transactions': transactions,
          'enum_worker_entries': kernel.count('SPX enum work enter'),
          'force_attach_markers': kernel.count('SPX FORCE-ATTACH:'),
          'limits': ['Raw status is a previous hardware snapshot, not a contemporaneous independent slave read.',
                     'AHB bridge read-data registers are volatile, but rc=0 does not prove completion or exclude torn/stale hardware data.',
                     'This parser performs no bus read, write, reset, GPIO operation or PCM activity.']}
report['native_bus_error_lines'] = result['native_bus_error_lines']
report['right_wsa_cold_init_markers'] = result['right_wsa_cold_init_markers']
report['all_initialization_lines'] = [line for line in kernel.splitlines() if 'SPX: initializing amplifier at SoundWire device' in line]
report['pin2_enumeration_diagnostic_passed'] = result['pin2_enumeration_diagnostic_passed']
report['left_initialization_lines'] = [line for line in kernel.splitlines() if 'wsa881x-codec sdw:0:0:0217:2110:00:3: SPX: initializing amplifier at SoundWire device 1' in line]
report['native_force_off_path_passed'] = result['native_force_off_path_passed']
report['runtime_pm'] = json.loads((SOURCE / 'runtime-pm.json').read_text())
OUT.write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
