#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assess identity-bound, read-only RTC synchronization observations."""


def assess(evidence, identity):
    for key in ('boot_id', 'release', 'cmdline', 'config_sha256', 'probe_sha256'):
        assert evidence[key] == identity[key], key
    assert evidence['attempt'] == '20261003ax'
    assert evidence['rtc_name'] == 'surface_rtc 01:01:01:00:00'
    assert evidence['rtc_device'].endswith('/01:01:01:00:00/rtc/rtc0')
    assert evidence['hctosys'] == '1'
    assert evidence['rtc_systohc_enabled'] and evidence['systohc_device'] == 'rtc0'
    assert evidence['observer_time_writes'] == 0
    samples = evidence['samples']
    assert 90 <= len(samples) <= 200
    assert 20 <= samples[0]['monotonic'] <= 180
    assert 2590 <= samples[-1]['monotonic'] <= 2680
    assert all(0 < b['monotonic'] - a['monotonic'] <= 45
               for a, b in zip(samples, samples[1:]))
    for sample in samples:
        assert sample['taint'] == '0'
        assert 0 <= sample['realtime_after'] - sample['realtime_before'] <= 1
        assert isinstance(sample['rtc_epoch'], int) and sample['rtc_epoch'] > 0
    # Observe chrony's reporting interface: adjtimex(modes=0) also prompts
    # ntp_notify_cmos_timer(), which could alter the RTC work being tested.
    def ntp_synchronized(sample):
        return (sample['ntp_leap_status'] == 'Normal' and
                1 <= sample['ntp_stratum'] <= 15 and
                abs(sample['ntp_system_offset_seconds']) <= 1 and
                0 <= sample['realtime_after'] - sample['ntp_reference_epoch'] <= 1800)

    synchronized = [s for s in samples if ntp_synchronized(s)]
    assert synchronized
    first = synchronized[0]['monotonic']
    settled = [s for s in samples if s['monotonic'] >= first + 60]
    assert len(settled) >= 45 and settled[-1]['monotonic'] - settled[0]['monotonic'] >= 660
    offsets = []
    for sample in settled:
        assert ntp_synchronized(sample)
        # Account for one-second RTC quantization and bracketed read latency.
        low = sample['rtc_epoch'] - sample['realtime_after']
        high = sample['rtc_epoch'] + 1 - sample['realtime_before']
        assert low >= -2 and high <= 2, (low, high)
        offsets.append((low, high))
    return {'scoped_passed': True, 'settled_samples': len(settled),
            'settled_span_seconds': settled[-1]['monotonic'] - settled[0]['monotonic'],
            'first_ntp_synchronized_uptime': first,
            'rtc_minus_system_interval_min_seconds': min(x[0] for x in offsets),
            'rtc_minus_system_interval_max_seconds': max(x[1] for x in offsets),
            'hardware_acceptance_closed': False,
            'limits': ['RTC write attribution is inferred from configuration and readback; no enabled RTC tracepoint is available.',
                       'Power-off retention, suspend timekeeping and independent long-term drift remain untested.']}
