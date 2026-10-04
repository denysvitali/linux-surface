#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reject false candidate GPU verdicts using explicitly synthetic smoke-derived fixtures."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

from au_gpu_core import assess, digest

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC / 'gpu-workload-20261003'))
from collect import parse_result, FAULTS


def main():
    plan = json.loads((SRC / 'gpu-workload-20261003/plan.json').read_text())
    smoke = Path('/var/lib/spx-boot-diagnostics/gpu-workloads/20261003au/reference-smoke-v5')
    identity = {'boot_id': 'synthetic-AU', 'release': plan['candidate_release'],
                'cmdline': 'synthetic-AU-command', 'collector_sha256': 'synthetic-collector',
                'plan_sha256': 'synthetic-plan', 'fixture_manifest_sha256': 'synthetic-fixture'}
    with tempfile.TemporaryDirectory(prefix='spx-au-synthetic-gpu-') as tmp:
        root = Path(tmp) / 'workload'
        shutil.copytree(smoke, root)
        evidence = json.loads((root / 'progress.json').read_text())
        evidence.update(identity, reference_smoke=False, expected_render_seconds=1800)
        for run in evidence['runs']:
            scenes = [s for phase in plan['phases'] for s in phase] if run['validation'] else plan['phases'][int(run['label'].rsplit('-', 1)[1])]
            xml = root / 'user-results' / (run['label'] + '.xml')
            tree = ET.parse(xml)
            for row in tree.getroot().findall('benchmark'):
                name = row.find('name')
                assert 'duration=1' in name.text
                name.text = name.text.replace('duration=1', 'duration=60')
            tree.write(xml)
            run['xml_sha256'] = digest(xml)
            run['result'] = parse_result(xml, scenes, 60, plan['renderer'], run['validation'], run['api'])
            run['elapsed_seconds'] = 300 if not run['validation'] else 5
        for index, o in enumerate(evidence['observations']):
            o['taint'] = '0'
            o['monotonic'] = index * 31
        assert assess(evidence, root, plan, identity, parse_result, FAULTS)['planned_render_seconds_completed'] == 1800
        mutations = []

        def case(fn):
            item = copy.deepcopy(evidence)
            fn(item)
            mutations.append(item)

        case(lambda e: e.update(reference_smoke=True))
        case(lambda e: e.update(scoped_passed=False))
        for key in identity:
            case(lambda e, k=key: e.update({k: 'wrong'}))
        case(lambda e: e.update(hardware_acceptance_closed=True))
        case(lambda e: e.update(expected_render_seconds=30))
        case(lambda e: e['runs'].pop())
        case(lambda e: e['runs'].__setitem__(1, copy.deepcopy(e['runs'][2])))
        case(lambda e: e['runs'][1].update(returncode=1))
        case(lambda e: e['runs'][1].update(elapsed_seconds=299.9))
        case(lambda e: e['runs'][1].update(scene_count=4))
        case(lambda e: e['runs'][1].update(xml_sha256='wrong'))
        case(lambda e: e['runs'][1].update(log_sha256='wrong'))
        case(lambda e: e['runs'][1].update(fd_samples=[]))
        case(lambda e: e['runs'][1]['fd_samples'][0].update(nodes=['/dev/dri/card0']))
        case(lambda e: e['observations'][0].update(taint='4096'))
        case(lambda e: e['observations'][0].update(desktop=[]))
        case(lambda e: e['observations'][1]['desktop'][0].update(start_ticks='changed'))
        case(lambda e: e['observations'][1].update(monotonic=-1))
        case(lambda e: e['observations'][3].update(monotonic=e['observations'][4]['monotonic']-29.9))
        case(lambda e: e['observations'].pop())
        for item in mutations:
            try:
                assess(item, root, plan, identity, parse_result, FAULTS)
            except AssertionError:
                continue
            raise AssertionError('false GPU result accepted')
        kernel = root / 'kernel-after.log'
        text = kernel.read_text()
        kernel.write_text(text + '\nmsm GPU watchdog timeout\n')
        try:
            assess(evidence, root, plan, identity, parse_result, FAULTS)
        except AssertionError:
            pass
        else:
            raise AssertionError('GPU fault accepted')
        print(json.dumps({'synthetic_only': True, 'hardware_acceptance_closed': False,
                          'positive_cases': 1, 'negative_cases': len(mutations) + 1}))


if __name__ == '__main__':
    main()
