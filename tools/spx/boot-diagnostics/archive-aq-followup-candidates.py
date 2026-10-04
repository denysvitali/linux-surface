#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze offline touch timing and rear lifecycle candidates after actual AQ recovery."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from aq_boot_guard import X, REPO, files, load, recovery, sha


def main():
    os.umask(0o077)
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '991a6fbd-2217-4f93-8185-287a223a13f6'
    assert os.uname().release == '6.18.3-1-surface+'
    a = load()
    assert not recovery(a).get('next_entry', '')
    prior = json.loads((X / 'recovery-return/report.json').read_text())
    assert prior['recovery_boot_id'] == bid and prior['userspace_fallback_return_verified']
    assert sha(REPO / '.config') == 'f0c4a7ff7ed3659f1f44ede2348d7333803721b5bc1229d57744f7999e619288'
    rear = Path('/var/tmp/spx-rear-lifecycle-20261003')
    touch = Path('/var/tmp/spx-touch-firmware-20261003')
    source = REPO / 'drivers/media/i2c/ov13858.c'
    original = json.loads((rear / 'aq-source-files.json').read_text())
    assert sha(rear / 'ov13858-before.c') == original['drivers/media/i2c/ov13858.c']['sha256']
    assert sha(source) == sha(rear / 'ov13858-after.c') == sha(rear / 'native-build/source/drivers/media/i2c/ov13858.c')
    for name in ('native-object.json', 'native-link.json', 'candidate-final/result.json'):
        assert json.loads((rear / name).read_text())['returncode'] == 0
    tested = json.loads((rear / 'candidate-final/result.json').read_text())
    assert tested['source_sha256'] == sha(source) and 'PASS 171 cases' in tested['stdout']
    assert json.loads((rear / 'before/result.json').read_text())['returncode'] != 0
    for name in ('native-object.log', 'native-link.log'):
        log = (rear / name).read_text().lower()
        assert 'warning:' not in log and 'error:' not in log
    timing = json.loads((touch / 'dt-review.json').read_text())
    assert timing['all_other_nodes_properties_and_memory_reservations_exact_aq']
    assert timing['fixed_regulator_schema_passed'] and timing['value_microseconds'] == 300000
    assert timing['candidate_dtb_sha256'] == sha(touch / 'candidate.dtb')
    assert (touch / 'board-after.dts').read_bytes() == (REPO / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts').read_bytes()
    out = X / 'offline-followup-candidates-20261003'
    assert not out.exists()
    out.mkdir(mode=0o700)
    shutil.copytree(touch, out / 'touch-timing')
    sensor = out / 'rear-lifecycle'
    sensor.mkdir()
    for path in rear.iterdir():
        if path.is_file():
            shutil.copy2(path, sensor / path.name)
    for name in ('candidate-v1', 'candidate-final', 'before'):
        shutil.copytree(rear / name, sensor / name)
    native = sensor / 'native-artifacts'
    native.mkdir()
    build = rear / 'native-build/build'
    for name in ('.config', 'Module.symvers', 'include/generated/autoconf.h'):
        target = native / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / name, target)
    modules = {}
    for module in sorted(build.rglob('*.ko')):
        relative = module.relative_to(build)
        target = native / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module, target)
        shutil.copy2(module.with_suffix('.o'), target.with_suffix('.o'))
        modules[str(relative)] = {'sha256': sha(module), 'vermagic': subprocess.check_output(
            ['modinfo', '-F', 'vermagic', str(module)], text=True).strip()}
    assert len(modules) == 16
    (sensor / 'native-module-provenance.json').write_text(json.dumps(modules, indent=2) + '\n')
    helpers = out / 'sources'
    helpers.mkdir()
    paths = ['AGENTS.md', 'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md',
             'tools/spx/boot-diagnostics/audit-touch-firmware.py',
             'tools/spx/boot-diagnostics/TOUCH-FIRMWARE-TIMING-20261003.md',
             'tools/spx/boot-diagnostics/RESULT-20261003aq.md',
             'tools/spx/boot-diagnostics/camera-power-20261003/check_rear_lifecycle.py',
             'tools/spx/boot-diagnostics/camera-power-20261003/audit_firmware.py',
             'tools/spx/boot-diagnostics/camera-power-20261003/README.md',
             'drivers/regulator/core.c', 'drivers/regulator/fixed.c',
             'Documentation/devicetree/bindings/regulator/fixed-regulator.yaml']
    for name in paths:
        target = helpers / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / name, target)
    shutil.copy2(__file__, helpers / Path(__file__).name)
    shutil.copy2('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl', out / 'firmware-dsdt.dsl')
    assert sha(out / 'firmware-dsdt.dsl') == json.loads((touch / 'firmware.json').read_text())['source_sha256']
    report = {'boot_id': bid, 'scope': ['I01', 'C01'], 'new_trial_selected': False,
              'hardware_acceptance_closed': False, 'source_sha256': sha(source),
              'lifecycle_cases': 171, 'original_suspend_error_test_rejected': True,
              'native_camera_modules_strict_linked': 16,
              'native_exports_sha256': sha(build / 'vmlinux.o'),
              'native_exports_scope': 'Retained historical source/config exports; compile evidence only.',
              'touch_timing_dtb_sha256': sha(touch / 'candidate.dtb'),
              'touch_firmware_delay_ms': 300,
              'electrical_state_or_ownership_validated': False,
              'runtime_hardware_actions': []}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    h = files(out)
    (out / 'sha256.json').write_text(json.dumps(h, indent=2) + '\n')
    assert files(out) == h | {'sha256.json': sha(out / 'sha256.json')}
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert not recovery(a).get('next_entry', '')
    os.sync()
    print(json.dumps(report | {'files_verified': len(h), 'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
