#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze verified offline C01 evidence without changing boot or runtime hardware."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[4]
WORK = Path('/var/tmp/spx-camera-power-20261003')
DEST = Path('/var/lib/spx-boot-diagnostics/attempts/20261002ap/camera-power-c01-20261003')
BOOT = '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def command(*args):
    return subprocess.check_output(args, cwd=REPO, text=True, timeout=60)


def main():
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '0'
    assert Path('/sys/bus/spi/devices/spi0.0/ready').read_text().strip() == 'ready'
    env = dict(line.split('=', 1) for line in
               command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert env['saved_entry'] == 'spx-known-good' and not env.get('next_entry')
    assert 'BootNext:' not in command('efibootmgr')
    assert sha(REPO / '.config') == sha(WORK / 'active.config')
    driver = REPO / 'drivers/media/i2c/ov13858.c'
    assert sha(driver) == sha(WORK / 'ov13858-after.c')
    assert sha(driver) == sha(WORK / 'native-build/source/drivers/media/i2c/ov13858.c')
    tests = json.loads((WORK / 'candidate-final/result.json').read_text())
    assert tests['returncode'] == 0 and tests['source_sha256'] == sha(driver)
    cci = json.loads((WORK / 'cci/result.json').read_text())
    assert cci['positive_cases'] == 5 and cci['negative_cases'] == 4
    assert cci['schema_sha256'] == sha(REPO / 'Documentation/devicetree/bindings/i2c/qcom,i2c-cci.yaml')
    assert json.loads((WORK / 'native-link.json').read_text())['returncode'] == 0
    assert json.loads((WORK / 'before/result.json').read_text())['returncode'] != 0
    DEST.mkdir(mode=0o700, exist_ok=False)
    for path in WORK.iterdir():
        if path.is_file():
            shutil.copy2(path, DEST / path.name)
    for name in ('candidate', 'candidate-final', 'before', 'cci'):
        shutil.copytree(WORK / name, DEST / name)
    shutil.copy2('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl',
                 DEST / 'firmware-dsdt.dsl')
    firmware = json.loads((DEST / 'firmware-power.json').read_text())
    assert sha(DEST / 'firmware-dsdt.dsl') == firmware['source_sha256']
    src = DEST / 'review-sources'
    src.mkdir()
    for path in Path(__file__).parent.iterdir():
        if path.is_file():
            shutil.copy2(path, src / path.name)
    for name in ('AGENTS.md', 'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md'):
        shutil.copy2(REPO / name, src / name)
    (DEST / 'source-head').write_text(command('git', 'rev-parse', 'HEAD'))
    (DEST / 'current-source.diff').write_text(command('git', 'diff', '--binary'))
    build = WORK / 'native-build/build'
    artifacts = DEST / 'native-artifacts'
    artifacts.mkdir()
    for name in ('.config', 'Module.symvers', 'include/generated/autoconf.h'):
        target = artifacts / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / name, target)
    modules = {}
    for path in sorted(build.rglob('*.ko')):
        relative = path.relative_to(build)
        target = artifacts / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        obj = path.with_suffix('.o')
        shutil.copy2(obj, target.with_suffix('.o'))
        modules[str(relative)] = {'sha256': sha(path),
                                 'vermagic': command('modinfo', '-F', 'vermagic', str(path)).strip()}
    assert len(modules) == 16
    (DEST / 'native-module-provenance.json').write_text(json.dumps(modules, indent=2) + '\n')
    exports = WORK / 'native-build/build/vmlinux.o'
    old_exports = Path('/var/tmp/spx-camera-config-20260922-6x_9qvel/build/vmlinux.o')
    assert sha(exports) == sha(old_exports)
    versions = {'gcc': command('gcc', '--version'), 'ld': command('ld', '--version'),
                'dtc': command('dtc', '--version'),
                'dtschema': command('/var/tmp/spx-dtschema-venv-20260915/bin/python', '-c',
                                    'import importlib.metadata; print(importlib.metadata.version("dtschema"))')}
    (DEST / 'tool-versions.json').write_text(json.dumps(versions, indent=2) + '\n')
    report = {'checklist_ids': ['C01'], 'boot_id': BOOT, 'hardware_acceptance_closed': False,
              'runtime_hardware_actions': [], 'new_trial_queued': False,
              'actual_source_sha256': sha(driver), 'power_fault_injection_cases': 11,
              'old_source_ordering_test_rejected': True,
              'cci_positive_cases': 5, 'cci_negative_cases': 4,
              'native_modules_strict_linked': len(modules),
              'historical_kernel_export_sha256': sha(exports),
              'historical_build_snapshot': str(old_exports.parent.parent),
              'kernel_export_provenance_limit': 'Compile/link check with preserved September exports; '
                                                  'no full current kernel build or deployable module set.',
              'live_integrity_record_sha256': sha(DEST / 'live-integrity.json'),
              'grubenv': env, 'current_config_unchanged': True,
              'remaining': ['PMIC metadata/ownership', 'front/IR physical supplies',
                            'CAMSS analog providers', 'controller/sensor bindings and SID scope',
                            'complete distinct build and hardware validation']}
    (DEST / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    files = {str(path.relative_to(DEST)): sha(path) for path in sorted(DEST.rglob('*'))
             if path.is_file()}
    manifest = DEST / 'sha256.json'
    manifest.write_text(json.dumps(files, indent=2) + '\n')
    for name, digest in json.loads(manifest.read_text()).items():
        assert sha(DEST / name) == digest, name
    os.sync()
    print(json.dumps({'archive': str(DEST), 'files_verified': len(files),
                      'manifest_sha256': sha(manifest)}))


if __name__ == '__main__':
    main()
