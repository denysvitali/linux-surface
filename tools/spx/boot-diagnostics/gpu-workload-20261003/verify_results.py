#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Recompute reference results and test rejection of misleading GPU evidence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from collect import FAULTS, parse_result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(Path(__file__).with_name('plan.json').read_text())
    hashes = json.loads((args.evidence / 'sha256.json').read_text())
    for name, digest in hashes.items():
        assert sha(args.evidence / name) == digest, name
    evidence = json.loads((args.evidence / 'progress.json').read_text())
    assert evidence['reference_smoke'] and evidence['scoped_passed']
    assert len(evidence['runs']) == 10 and not evidence['kernel_faults']
    assert evidence['hardware_acceptance_closed'] is False
    assert evidence['release'] == '6.18.3-1-surface+'
    assert {o['taint'] for o in evidence['observations']} == {'4096'}
    seconds = 1
    verified, image_checks, stress_rows = 0, 0, 0
    for run in evidence['runs']:
        api = run['api']
        assert api in plan['apis'] and run['returncode'] == 0
        if run['validation']:
            scenes = [s for phase in plan['phases'] for s in phase]
            image_checks += len(scenes)
        else:
            index = int(run['label'].rsplit('-', 1)[1])
            scenes = plan['phases'][index]
            stress_rows += len(scenes)
            assert run['elapsed_seconds'] >= seconds * len(scenes)
        xml = args.evidence / 'user-results' / (run['label'] + '.xml')
        assert sha(xml) == run['xml_sha256']
        actual = parse_result(xml, scenes, seconds, plan['renderer'], run['validation'], api)
        assert actual == run['result']
        assert all(set(sample['nodes']) <= {plan['render_node']} for sample in run['fd_samples'])
        assert any(plan['render_node'] in sample['nodes'] for sample in run['fd_samples'])
        verified += 1
    desktop = evidence['observations'][0]['desktop']
    assert all(o['desktop'] == desktop for o in evidence['observations'])
    after = (args.evidence / 'kernel-after.log').read_text()
    assert not FAULTS.findall(after)
    args.output.mkdir(mode=0o700)
    source = args.evidence / 'user-results/glmark2-gbm-phase-0.xml'
    original = ET.parse(source).getroot()
    rejected = []
    for label in ('software-renderer', 'unknown-status', 'failed-status', 'zero-fps',
                  'wrong-duration', 'missing-scene', 'wrong-scene', 'wrong-api'):
        root = copy.deepcopy(original)
        row = root.find('benchmark')
        if label == 'software-renderer':
            root.find('info/gl_renderer').text = 'llvmpipe'
        elif label == 'unknown-status':
            row.find('status').text = 'Unknown'
        elif label == 'failed-status':
            row.find('status').text = 'Failure'
        elif label == 'zero-fps':
            row.find('fps').text = '0'
        elif label == 'wrong-duration':
            row.find('name').text = row.find('name').text.replace('duration=1', 'duration=0')
        elif label == 'missing-scene':
            root.remove(row)
        elif label == 'wrong-scene':
            row.find('name').text = row.find('name').text.replace('[build]', '[texture]')
        elif label == 'wrong-api':
            root.find('info/gl_version').text = 'OpenGL ES 3.2 Mesa'
        target = args.output / (label + '.xml')
        ET.ElementTree(root).write(target, encoding='utf-8', xml_declaration=True)
        try:
            parse_result(target, plan['phases'][0], 1, plan['renderer'], False, 'glmark2-gbm')
        except AssertionError as error:
            rejected.append({'case': label, 'reason': str(error)})
        else:
            raise AssertionError('Accepted bad evidence: ' + label)
    benign = '[2.13] kernel: iommu: Default domain type: Translated'
    assert not FAULTS.findall(benign)
    fault_lines = ['adreno GPU hangcheck timer expired', 'GMU: fault detected',
                   'msm: GPU reset', 'arm-smmu: page fault', 'kernel: BUG: failed',
                   'kernel: Oops: 96000004', 'remoteproc adsp crash',
                   'GMU watchdog expired', 'msm: hangcheck detected gpu lockup rb 0!']
    assert all(FAULTS.findall(line) for line in fault_lines)
    report = {'reference_smoke_only': True, 'hardware_acceptance_closed': False,
              'recomputed_runs': verified, 'successful_image_checks': image_checks,
              'successful_timed_scene_rows': stress_rows,
              'software_or_false_result_cases_rejected': rejected,
              'benign_default_word_rejected_as_fault': False,
              'positive_fault_signatures_detected': fault_lines,
              'reference_manifest_sha256': sha(args.evidence / 'sha256.json')}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.output / 'sha256.json').write_text(json.dumps({p.name: sha(p) for p in
        sorted(args.output.iterdir()) if p.is_file()}, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
