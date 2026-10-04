#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash AT camera evidence and recompute its normal probe/idle findings offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from at_camera_core import assess, decode, trial_findings

X = Path('/var/lib/spx-boot-diagnostics/attempts/20261003at')
AP = X.parent / '20261002ap/camera-pmic-metadata-20261003'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def evidence(name):
    root = X / name
    h = json.loads((root / 'sha256.json').read_text())
    actual = {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
              if p.is_file() and not p.is_symlink()}
    assert actual == h | {'sha256.json': sha(root / 'sha256.json')}
    return json.loads((root / 'report.json').read_text()), h


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final', action='store_true')
    args = parser.parse_args()
    label = 'camera-control-final-result' if args.final else 'camera-control-result'
    output = 'camera-control-final-review.json' if args.final else 'camera-control-review.json'
    assert os.geteuid() == 0 and not (X / output).exists()
    a = json.loads((X / 'attempt.json').read_text())
    control, h = evidence(label)
    providers, hp = evidence('camera-provider-result')
    for name in ('at-camera-control.py', 'at_camera_core.py'):
        assert sha(X / label / name) == a['runtime_sha256'][
            '/usr/local/lib/spx-boot-diagnostics/' + name]
    assert sha(Path(__file__).with_name('at_camera_core.py')) == sha(X / label / 'at_camera_core.py')
    assert sha(AP / 'sha256.json') == '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
    for name, digest in json.loads((AP / 'sha256.json').read_text()).items():
        assert sha(AP / name) == digest
    reference = decode(json.loads((AP / 'result.json').read_text())['reads'])
    before = control['identity_before']
    assert before['boot_id'] != a['preboot_id'] and before['release'] == a['release']
    assert before['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261003at/vmlinuz'] + a['cmdline'].split()
    findings = trial_findings(control, providers, reference, before)
    report = {'attempt': a['attempt'], 'boot_id': before['boot_id'], 'release': before['release'],
              **assess(control, reference), **findings,
              'control_files_verified': len(h), 'provider_files_verified': len(hp),
              'collection_phase': control['collection_phase'],
              'control_manifest_sha256': sha(X / label / 'sha256.json'),
              'provider_manifest_sha256': sha(X / 'camera-provider-result/sha256.json'),
              'normal_probe_identity_check_completed': control['checks']['rear_normal_probe_completed'],
              'raw_sensor_chip_id_bytes_verified': False,
              'camera_functional_acceptance': False, 'collector_hardware_writes': 0,
              'limits': control['limits']}
    os.umask(0o077)
    with (X / output).open('x') as f:
        f.write(json.dumps(report, indent=2) + '\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
