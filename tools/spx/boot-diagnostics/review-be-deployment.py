#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently compare actual installed BE paths, units and recovery with its plan."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from be_boot_guard import X, RUNTIME, load, preboot, files, links, sha


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    a = load()
    assert a['state'] == 'prepared BE; no boot selection'
    current = preboot(a)
    plan = X / 'preparation/runtime-plan'
    expected = read(plan / 'sha256.json')
    assert files(plan) == expected | {'sha256.json': sha(plan / 'sha256.json')}
    assert sha(plan / 'sha256.json') == a['runtime_plan_manifest_sha256']
    spec = importlib.util.spec_from_file_location('be_installed_plan', plan / 'prepare-be-runtime.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    assert len(config.HELPERS) == 13 and len(config.ACTIONS) == 6
    for name in config.HELPERS:
        assert sha(RUNTIME / name) == expected[name]
        assert (RUNTIME / name).stat().st_mode & 0o777 == 0o755
    units = sorted(plan.glob('spx-be-*.service')) + sorted(plan.glob('spx-be-*.timer'))
    assert len(units) == 12
    installed = []
    for path in units:
        target = Path('/etc/systemd/system') / path.name
        assert target.read_bytes() == path.read_bytes()
        assert 'ConditionKernelCommandLine=spx_attempt=20261004be' in target.read_text()
        installed.append(str(target))
    result = subprocess.run(['systemd-analyze', 'verify'] + installed, capture_output=True, timeout=60)
    assert result.returncode == 0 and not result.stderr.strip(), result.stderr.decode(errors='replace')
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/124-be-exclude.conf')
    assert exclude.read_bytes() == (plan / exclude.name).read_bytes()
    for path in plan.glob('spx-be-*.timer'):
        assert subprocess.check_output(['systemctl', 'is-enabled', path.name], text=True).strip() == 'enabled'
    entry = Path('/boot/grub/custom.cfg').read_text()
    assert entry == (plan / 'entry.cfg').read_text() == (X / 'entry.cfg').read_text()
    linux = re.findall(r'^\s*if linux (\S+) (.*); then$', entry, re.M)
    dtb = re.findall(r'^\s*if devicetree (\S+); then$', entry, re.M)
    initrd = re.findall(r'^\s*if initrd (\S+); then$', entry, re.M)
    assert linux == [('/spx-trial-20261004bc/vmlinuz', a['cmdline'])]
    assert dtb == ['/spx-trial-20261004be/spx.dtb'] and initrd == ['/spx-trial-20261004bc/initramfs.img']
    assert entry.count('--id spx-trial-20261004be') == 1
    subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)
    assert set(files(Path('/boot/spx-trial-20261004be'))) == {'spx.dtb'}
    assert sha('/boot/spx-trial-20261004be/spx.dtb') == '2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252'
    assert sha('/boot/spx-trial-20261004bc/vmlinuz') == '706da79ad142c4f09d54d47b43bb68281cdf167545e56652b19771ba855fb33e'
    assert sha('/boot/spx-trial-20261004bc/initramfs.img') == '6628dd3b7d54c52719e3fc02b13241fe41fb0924e89b91b5dbb7f8d5afb54be1'
    assert sha(X / 'independent-runtime-preparation-review.json') == a['independent_runtime_preparation_review_sha256']
    prep = X / 'deployment-preparation'
    assert files(prep) == read(prep / 'sha256.json') | {'sha256.json': sha(prep / 'sha256.json')}
    assert sha(prep / 'sha256.json') == a['deployment_preparation_manifest_sha256']
    assert Path('/boot/grub/grub.cfg').read_bytes() == (prep / 'previous-grub.cfg').read_bytes()
    assert Path(a['source_diff']).is_file()
    assert not (X / 'reboot-requested').exists()
    assert preboot(a)['boot_id'] == current['boot_id']
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=current['boot_id'],
        source_paths_checked=current['compiled_source_paths_verified'],
        helpers_exact_plan=13, units_exact_plan=12, installed_unit_verify_passed=True,
        timers_enabled=True, distinct_be_dtb_verified=True, exact_bc_kernel_initrd_paths_verified=True,
        exact_bc_module_files_verified=217, live_source_config_verified=True,
        recovery_files_links_verified=5183, known_good_touch_state=current['known_good_touch_state'],
        persistent_default='spx-known-good', next_entry_empty=True, efi_bootnext_absent=True,
        boot_selected=False, hardware_acceptance_closed=False)
    with (X / 'independent-deployment-review.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
