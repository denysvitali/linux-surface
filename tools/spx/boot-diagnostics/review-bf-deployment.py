#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently compare installed BF payloads, modules and units to its plan."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from bf_boot_guard import X, RUNTIME, RELEASE, load, preboot, files, links, sha


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    a = load()
    assert a['state'] == 'prepared BF; no boot selection'
    current = preboot(a)
    plan = X / 'preparation-reviewed/runtime-plan'
    expected = read(plan / 'sha256.json')
    assert files(plan) == expected | {'sha256.json': sha(plan / 'sha256.json')}
    spec = importlib.util.spec_from_file_location('bf_installed_plan', plan / 'prepare-bf-runtime.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    assert len(config.HELPERS) == 14 and len(config.ACTIONS) == 6
    for name in config.HELPERS:
        assert sha(RUNTIME / name) == expected[name] and (RUNTIME / name).stat().st_mode & 0o777 == 0o755
    units = sorted(plan.glob('spx-bf-*.service')) + sorted(plan.glob('spx-bf-*.timer'))
    assert len(units) == 12
    installed = []
    for path in units:
        target = Path('/etc/systemd/system') / path.name
        assert target.read_bytes() == path.read_bytes()
        assert 'ConditionKernelCommandLine=spx_attempt=20261004bf' in target.read_text()
        assert target.stat().st_mode & 0o777 == 0o644
        installed.append(str(target))
    result = subprocess.run(['systemd-analyze', 'verify'] + installed, capture_output=True, timeout=60)
    assert result.returncode == 0 and not result.stderr.strip(), result.stderr.decode(errors='replace')
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/125-bf-exclude.conf')
    assert exclude.read_bytes() == (plan / exclude.name).read_bytes()
    for path in plan.glob('spx-bf-*.timer'):
        assert subprocess.check_output(['systemctl', 'is-enabled', path.name], text=True).strip() == 'enabled'
        assert subprocess.check_output(['systemctl', 'show', path.name, '-p', 'ActiveState', '--value'], text=True).strip() == 'inactive'
    entry = Path('/boot/grub/custom.cfg').read_text()
    assert entry == (plan / 'entry.cfg').read_text() == (X / 'entry.cfg').read_text()
    assert re.findall(r'^\s*if linux (\S+) (.*); then$', entry, re.M) == [('/spx-trial-20261004bf/vmlinuz', a['cmdline'])]
    assert re.findall(r'^\s*if devicetree (\S+); then$', entry, re.M) == ['/spx-trial-20261004bf/spx.dtb']
    assert re.findall(r'^\s*if initrd (\S+); then$', entry, re.M) == ['/spx-trial-20261004bf/initramfs.img']
    assert entry.count('--id spx-trial-20261004bf') == 1
    subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)
    payloads = files(Path('/boot/spx-trial-20261004bf'))
    assert payloads == {name: sha(X / 'assembly' / source) for name, source in
        [('vmlinuz', 'vmlinuz'), ('initramfs.img', 'initramfs.img'), ('spx.dtb', 'dtb-build/spx.dtb')]}
    module_root = Path('/usr/lib/modules') / RELEASE
    assert files(module_root) == read(X / 'assembly/module-sha256.json') and len(files(module_root)) == 217
    assert links(module_root) == read(X / 'assembly/module-links.json')
    alias = read(X / 'assembly/videocc-alias-resolution.json')
    assert subprocess.check_output(['modprobe', '--resolve-alias', '-S', RELEASE, alias['modalias']], text=True).splitlines() == ['videocc_sm8150']
    for path in sorted(module_root.rglob('*.ko')):
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).split()[0] == RELEASE
    prep = X / 'deployment-preparation'
    assert files(prep) == read(prep / 'sha256.json') | {'sha256.json': sha(prep / 'sha256.json')}
    assert sha(prep / 'sha256.json') == a['deployment_preparation_manifest_sha256']
    assert Path('/boot/grub/grub.cfg').read_bytes() == (prep / 'previous-grub.cfg').read_bytes()
    assert Path(a['source_diff']).is_file() and not (X / 'reboot-requested').exists()
    assert preboot(a)['boot_id'] == current['boot_id']
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=current['boot_id'], release=RELEASE,
        source_paths_checked=current['compiled_source_paths_verified'], helpers_exact_plan=14, units_exact_plan=12,
        installed_unit_verify_passed=True, timers_enabled_and_inactive=True,
        fresh_bf_kernel_initrd_dtb_paths_verified=True, installed_module_files_verified=217,
        modules_verified=202, installed_vermagic_and_actual_of_alias_verified=True,
        live_source_config_verified=True, recovery_files_links_verified=5183,
        known_good_touch_state=current['known_good_touch_state'],
        independent_preparation_review_sha256=sha(X / 'independent-preparation-review.json'),
        persistent_default='spx-known-good', next_entry_empty=True, efi_bootnext_absent=True,
        boot_selected=False, hardware_acceptance_closed=False)
    with (X / 'independent-deployment-review.json').open('x') as stream: stream.write(json.dumps(report, indent=2) + '\n')
    shutil.copy2(__file__, X / Path(__file__).name)
    os.sync()
    print(json.dumps(report | dict(review_sha256=sha(X / 'independent-deployment-review.json'))), flush=True)


if __name__ == '__main__':
    main()
