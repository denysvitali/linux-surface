#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check independent RTC replay rejects damaged archives and false summaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from ax_rtc_core import assess
from ax_rtc_review import review


def main():
    identity = {'boot_id': 'synthetic', 'release': 'synthetic', 'cmdline': 'synthetic',
                'config_sha256': 'synthetic', 'probe_sha256': 'synthetic'}
    samples = []
    for i in range(30, 2611, 15):
        ref = 1791020000 + i - 20
        samples.append({'monotonic': i, 'realtime_before': 1791020000 + i + .25,
                        'realtime_after': 1791020000 + i + .253, 'rtc_epoch': 1791020000 + i,
                        'ntp_leap_status': 'Normal', 'ntp_stratum': 2,
                        'ntp_system_offset_seconds': .0001, 'ntp_reference_epoch': ref,
                        'ntp_tracking_csv': f'C0216066,192.33.96.102,2,{ref},0.0001,0,0,0,0,0,0,0,15,Normal',
                        'taint': '0'})
    evidence = dict(identity, attempt='20261003ax', rtc_name='surface_rtc 01:01:01:00:00',
                    rtc_device='/sys/devices/platform/hub/01:01:01:00:00/rtc/rtc0',
                    hctosys='1', rtc_systohc_enabled=True, systohc_device='rtc0',
                    observer_time_writes=0, samples=samples)
    result = assess(evidence, identity) | identity
    cases = 0
    with tempfile.TemporaryDirectory(prefix='spx-ax-rtc-review-synthetic-') as tmp:
        root = Path(tmp)

        def seal(e=evidence, r=result):
            for path in root.iterdir():
                path.unlink()
            (root / 'progress.json').write_text(json.dumps(e))
            (root / 'result.json').write_text(json.dumps(r))
            (root / 'sha256.json').write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                       for p in root.iterdir()}))

        def reject(fn):
            nonlocal cases
            seal()
            fn()
            try:
                review(root, identity)
            except (AssertionError, KeyError, FileNotFoundError):
                cases += 1
                return
            raise AssertionError('false RTC archive accepted')

        seal()
        assert review(root, identity)['verdict']['scoped_passed']
        reject(lambda: (root / 'progress.json').write_text('{}'))
        reject(lambda: (root / 'extra').write_text('not archived'))
        reject(lambda: seal(r=result | {'scoped_passed': False}))
        reject(lambda: seal(r=result | {'boot_id': 'other'}))
        reject(lambda: seal(r=result | {'settled_samples': 1}))
        reject(lambda: seal(r=result | {'failure': 'collector failed'}))
        bad = copy.deepcopy(evidence)
        bad['samples'][40]['ntp_stratum'] = 3
        reject(lambda: seal(e=bad))
        bad = copy.deepcopy(evidence)
        bad['samples'][40]['ntp_tracking_csv'] = 'wrong'
        reject(lambda: seal(e=bad))
        reject(lambda: (root / 'progress.json').unlink())
    assert cases == 9
    print(json.dumps({'synthetic_only': True, 'positive_cases': 1, 'negative_cases': cases,
                      'hardware_acceptance_closed': False}))


if __name__ == '__main__':
    main()
