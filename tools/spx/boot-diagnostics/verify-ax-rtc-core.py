#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise RTC verdict failures; synthetic positives are never hardware evidence."""
import copy
import json
from ax_rtc_core import assess


def main():
    identity = {'boot_id': 'synthetic-AX', 'release': 'synthetic-release',
                'cmdline': 'synthetic-cmdline', 'config_sha256': 'synthetic-config',
                'probe_sha256': 'synthetic-probe'}
    samples = [{'monotonic': i, 'realtime_before': 1791020000 + i + .25,
                'realtime_after': 1791020000 + i + .253, 'rtc_epoch': 1791020000 + i,
                'ntp_leap_status': 'Normal', 'ntp_stratum': 2,
                'ntp_system_offset_seconds': .0001, 'ntp_reference_epoch': 1791020000 + i - 20,
                'taint': '0'} for i in range(30, 2611, 15)]
    evidence = dict(identity, attempt='20261003ax', rtc_name='surface_rtc 01:01:01:00:00',
                    rtc_device='/sys/devices/platform/hub/01:01:01:00:00/rtc/rtc0',
                    hctosys='1', rtc_systohc_enabled=True, systohc_device='rtc0',
                    observer_time_writes=0, samples=samples)
    assert assess(evidence, identity)['scoped_passed']
    cases = []

    def rejected(label, change):
        candidate = copy.deepcopy(evidence)
        change(candidate)
        try:
            assess(candidate, identity)
        except (AssertionError, KeyError, TypeError):
            cases.append(label)
            return
        raise AssertionError(label + ' was accepted')

    for key in identity:
        rejected('wrong ' + key, lambda e, k=key: e.update({k: 'other'}))
    for key, value in {'attempt': 'other', 'rtc_name': 'pmic-rtc', 'rtc_device': '/other/rtc0',
                       'hctosys': '0', 'rtc_systohc_enabled': False, 'systohc_device': 'rtc1',
                       'observer_time_writes': 1}.items():
        rejected(key, lambda e, k=key, v=value: e.update({k: v}))
    rejected('incomplete sample window', lambda e: e.update(samples=e['samples'][:50]))
    rejected('excessive sample count', lambda e: e.update(samples=e['samples'] * 2))
    rejected('late observer', lambda e: e['samples'][0].update(monotonic=200))
    rejected('nonmonotonic sample', lambda e: e['samples'][2].update(monotonic=30))
    rejected('observation gap', lambda e: e['samples'][3].update(monotonic=105))
    rejected('tainted candidate', lambda e: e['samples'][40].update(taint='4096'))
    rejected('slow read', lambda e: e['samples'][40].update(realtime_after=e['samples'][40]['realtime_before'] + 2))
    rejected('clock step during RTC read', lambda e: e['samples'][40].update(realtime_after=e['samples'][40]['realtime_before'] - 1))
    rejected('noninteger RTC', lambda e: e['samples'][40].update(rtc_epoch=1.5))
    rejected('UNSYNC status after settling', lambda e: e['samples'][40].update(ntp_leap_status='Not synchronised'))
    rejected('unsynchronized stratum after settling', lambda e: e['samples'][40].update(ntp_stratum=0))
    rejected('no NTP synchronized sample', lambda e: [s.update(ntp_leap_status='Not synchronised') for s in e['samples']])
    rejected('insufficient synchronized span', lambda e: [s.update(ntp_leap_status='Not synchronised') for s in e['samples'][:-25]])
    rejected('system correction still large', lambda e: e['samples'][40].update(ntp_system_offset_seconds=4))
    rejected('stale NTP reference', lambda e: e['samples'][40].update(ntp_reference_epoch=1))
    rejected('future NTP reference', lambda e: e['samples'][40].update(ntp_reference_epoch=e['samples'][40]['realtime_after'] + 5))
    rejected('one bad RTC readback', lambda e: e['samples'][40].update(rtc_epoch=e['samples'][40]['rtc_epoch'] + 4))
    rejected('RTC behind system', lambda e: [s.update(rtc_epoch=s['rtc_epoch'] - 4) for s in e['samples']])
    # The existing approximately791s offset is rejected even with TIME_OK.
    rejected('retained791s offset despite synchronized NTP', lambda e: [s.update(rtc_epoch=s['rtc_epoch'] + 791) for s in e['samples']])
    print(json.dumps({'synthetic_only': True, 'positive_cases': 1,
                      'negative_cases': len(cases), 'rejected_cases': cases,
                      'hardware_acceptance_closed': False}, indent=2))


if __name__ == '__main__':
    main()
