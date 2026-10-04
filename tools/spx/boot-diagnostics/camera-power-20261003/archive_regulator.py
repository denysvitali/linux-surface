#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze measured metadata and verified offline PMC8180 provider evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[4]
WORK = Path('/var/tmp/spx-camera-regulator-20261003')
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261002ap')
DEST = PARENT / 'camera-regulator-c01-20261003'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not DEST.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
        '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '0'
    assert Path('/sys/bus/spi/devices/spi0.0/ready').read_text().strip() == 'ready'
    driver = REPO / 'drivers/regulator/qcom_spmi-regulator.c'
    tests = json.loads((WORK / 'tests-final/result.json').read_text())
    assert tests['returncode'] == 0 and tests['source_sha256'] == sha(driver)
    assert sha(WORK / 'native-module/regulator_candidate.c') == sha(driver)
    assert json.loads((WORK / 'native-module/result.json').read_text())['returncode'] == 0
    assert json.loads((WORK / 'tests-original/result.json').read_text())['returncode'] != 0
    binding = json.loads((WORK / 'binding-complete/result.json').read_text())
    assert binding['positive_cases'] == binding['negative_cases'] == 2
    assert sha(WORK / 'binding-complete/schema/regulator/qcom,spmi-regulator.yaml') == \
        sha(REPO / 'Documentation/devicetree/bindings/regulator/qcom,spmi-regulator.yaml')
    for name in ('regulator-driver', 'regulator-binding'):
        assert 'total: 0 errors, 0 warnings, 0 checks' in (WORK / (name + '-checkpatch.log')).read_text()
    metadata = PARENT / 'camera-pmic-metadata-20261003'
    manifest = json.loads((metadata / 'sha256.json').read_text())
    for name, digest in manifest.items():
        assert sha(metadata / name) == digest
    assert sha(metadata / 'sha256.json') == \
        '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
    shutil.copytree(WORK, DEST, symlinks=True)
    sources = DEST / 'review-sources'
    sources.mkdir()
    for path in Path(__file__).parent.iterdir():
        if path.is_file():
            shutil.copy2(path, sources / path.name)
    for name in ('AGENTS.md', 'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md', '.config'):
        shutil.copy2(REPO / name, sources / Path(name).name)
    for args, name in [(['git', 'diff', '--binary', 'HEAD'], 'source.diff'),
                       (['git', 'rev-parse', 'HEAD'], 'source-head')]:
        (DEST / name).write_bytes(subprocess.check_output(args, cwd=REPO))
    report = {'checklist_ids': ['C01'], 'hardware_acceptance_closed': False,
              'runtime_actions_for_offline_candidate': [], 'new_trial_queued': False,
              'pmic_metadata_manifest_sha256': sha(metadata / 'sha256.json'),
              'driver_sha256': sha(driver), 'voltage_codes_tested': 196608,
              'schema_positive_cases': 2, 'schema_negative_cases': 2,
              'native_compile_link_passed': True,
              'native_export_basis': '/var/tmp/spx-camera-power-20261003/native-build/build',
              'native_limit': 'Historical kernel exports; this standalone test module is not deployable.',
              'registration_review': 'Default pin configuration retains all control bytes. '
                  'Core applies voltage only if out of constraints, enables only boot/always-on rails; '
                  'late cleanup skips disabled rails. Current controls match exact DT constraints.',
              'limits': ['No candidate registration, write, enable, camera probe or capture yet.',
                         'Initial binding test used an incorrect RPMh node path.',
                         'Supply and voltage size mutations were accepted by the limited schema; '
                         'final tests reject pin-control overflow and unknown supply.',
                         'Front/IR and CAMSS supply ownership remains unresolved.']}
    (DEST / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {str(p.relative_to(DEST)): sha(p) for p in sorted(DEST.rglob('*'))
              if p.is_file() and not p.is_symlink()}
    (DEST / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    for name, digest in hashes.items():
        assert sha(DEST / name) == digest
    os.sync()
    print(json.dumps({'archive': str(DEST), 'files_verified': len(hashes),
                      'manifest_sha256': sha(DEST / 'sha256.json')}))


if __name__ == '__main__':
    main()
