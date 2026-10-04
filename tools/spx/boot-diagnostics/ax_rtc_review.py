#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash RTC evidence and independently replay its raw tracking/readback verdict."""
import csv
import hashlib
import json

from ax_rtc_core import assess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(root, identity):
    assert not any(p.is_symlink() for p in root.rglob('*'))
    manifest = json.loads((root / 'sha256.json').read_text())
    actual = {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}
    assert actual == manifest | {'sha256.json': sha(root / 'sha256.json')}
    evidence = json.loads((root / 'progress.json').read_text())
    result = json.loads((root / 'result.json').read_text())
    for key, value in identity.items():
        assert result[key] == evidence[key] == value, key
    for sample in evidence['samples']:
        columns = next(csv.reader([sample['ntp_tracking_csv']]))
        assert len(columns) == 14
        assert sample['ntp_stratum'] == int(columns[2])
        assert sample['ntp_reference_epoch'] == float(columns[3])
        assert sample['ntp_system_offset_seconds'] == float(columns[4])
        assert sample['ntp_leap_status'] == columns[13]
    verdict = assess(evidence, identity)
    assert all(result[key] == value for key, value in verdict.items())
    assert result['scoped_passed'] and 'failure' not in result
    return {'verdict': verdict, 'files_verified': len(manifest),
            'manifest_sha256': sha(root / 'sha256.json')}
