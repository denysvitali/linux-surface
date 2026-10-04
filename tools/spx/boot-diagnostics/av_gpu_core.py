#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Recompute AV's bounded GPU verdict from immutable workload evidence."""
import hashlib


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_touch(touch):
    # spi-hid-core.c exposes count and last errno for the three error counters.
    return touch == {'ready': 'ready', 'bus_error_count': '0 (0)',
                     'logic_error_count': '0 (0)', 'regulator_error_count': '0 (0)',
                     'device_initiated_reset_count': '0'}


def assess(evidence, root, plan, identity, parse_result, faults):
    assert evidence['reference_smoke'] is False and evidence['scoped_passed']
    for key in ('boot_id', 'release', 'cmdline', 'plan_sha256', 'collector_sha256',
                'fixture_manifest_sha256'):
        assert evidence[key] == identity[key], key
    assert evidence['hardware_acceptance_closed'] is False
    assert plan['scene_seconds'] == 60 and plan['idle_seconds'] == 30
    assert evidence['expected_render_seconds'] == 1800
    expected = []
    for api in plan['apis']:
        expected.append((api, api + '-validate-before', True, None))
        expected.extend((api, api + '-phase-' + str(i), False, phase)
                        for i, phase in enumerate(plan['phases']))
        expected.append((api, api + '-validate-after', True, None))
    assert len(evidence['runs']) == len(expected) == 10
    images, timed, seconds = 0, 0, 0
    for run, (api, label, validation, phase) in zip(evidence['runs'], expected):
        assert (run['api'], run['label'], run['validation']) == (api, label, validation)
        assert run['returncode'] == 0
        scenes = [s for p in plan['phases'] for s in p] if validation else phase
        assert run['scene_count'] == len(scenes)
        xml = root / 'user-results' / (label + '.xml')
        actual = parse_result(xml, scenes, 60, plan['renderer'], validation, api)
        assert actual == run['result'] and digest(xml) == run['xml_sha256']
        assert digest(root / (label + '.log')) == run['log_sha256']
        samples = run['fd_samples']
        assert all(set(s['nodes']) <= {plan['render_node']} for s in samples)
        assert any(plan['render_node'] in s['nodes'] for s in samples)
        if validation:
            images += len(scenes)
        else:
            assert run['elapsed_seconds'] >= len(scenes) * 60
            seconds += len(scenes) * 60
            timed += len(scenes)
    assert (images, timed, seconds) == (60, 30, 1800)
    observations = evidence['observations']
    labels = ['before']
    for api in plan['apis']:
        labels.append(api + '-validate-before-complete')
        for i in range(len(plan['phases'])):
            labels.extend([api + '-phase-' + str(i) + '-complete',
                           api + '-idle-' + str(i) + '-start',
                           api + '-idle-' + str(i) + '-end'])
        labels.append(api + '-validate-after-complete')
    labels.append('after')
    assert [o['label'] for o in observations] == labels
    assert all(o['taint'] == '0' for o in observations)
    assert all(b['monotonic'] >= a['monotonic'] for a, b in zip(observations, observations[1:]))
    desktop = [(d['pid'], d['start_ticks']) for d in observations[0]['desktop']]
    assert len(desktop) == 1
    assert all([(d['pid'], d['start_ticks']) for d in o['desktop']] == desktop for o in observations)
    by_label = {o['label']: o for o in observations}
    idle_windows = []
    for api in plan['apis']:
        for i in range(len(plan['phases'])):
            prefix = api + '-idle-' + str(i)
            start, end = by_label[prefix + '-start'], by_label[prefix + '-end']
            elapsed = end['monotonic'] - start['monotonic']
            assert elapsed >= 30
            idle_windows.append({'label': prefix, 'elapsed_seconds': elapsed,
                                 'start_gpu_power': start['gpu_power'], 'end_gpu_power': end['gpu_power']})
    assert not faults.findall((root / 'kernel-after.log').read_text())
    return {'successful_image_checks': images, 'timed_scene_rows': timed,
            'planned_render_seconds_completed': seconds, 'idle_windows': idle_windows,
            'idle_seconds_observed': sum(i['elapsed_seconds'] for i in idle_windows),
            'unchanged_gnome_process': True, 'kernel_faults': []}
