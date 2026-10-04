#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash installed BA and compare actual helper/unit content with its frozen plan."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ba_boot_guard import X, RUNTIME, load, preboot, files, sha


def main():
    os.umask(0o077)
    a = load()
    current = preboot(a)
    plan = Path(a.get('runtime_plan_path', str(X / 'build/runtime-plan')))
    assert plan in (X / 'build/runtime-plan', X / 'runtime-plan-v2')
    expected = json.loads((plan / 'sha256.json').read_text())
    assert files(plan) == expected | {'sha256.json': sha(plan / 'sha256.json')}
    assert sha(plan / 'sha256.json') == a['runtime_plan_manifest_sha256']
    helpers = ('ba_boot_guard.py', 'ba-video.py', 'ba-return.py', 'ba-baseline.py',
               'ba-camera-provider.py', 'ba-camera-control.py', 'ba_camera_core.py',
               'review-ba-baseline.py', 'ba-media.py', 'ba-media-run.py')
    for name in helpers:
        assert sha(RUNTIME / name) == expected[name]
    units = sorted(plan.glob('spx-ba-*.service')) + sorted(plan.glob('spx-ba-*.timer'))
    assert len(units) == 12
    installed = []
    for path in units:
        target = Path('/etc/systemd/system') / path.name
        assert target.read_bytes() == path.read_bytes()
        installed.append(str(target))
    result = subprocess.run(['systemd-analyze', 'verify'] + installed, capture_output=True, timeout=60)
    assert result.returncode == 0 and not result.stderr.strip(), result.stderr.decode(errors='replace')
    assert Path('/etc/systemd/system/spx-diag-long-return.timer.d/123-ba-exclude.conf').read_bytes() == (plan / '123-ba-exclude.conf').read_bytes()
    for path in plan.glob('spx-ba-*.timer'):
        assert subprocess.check_output(['systemctl', 'is-enabled', path.name], text=True).strip() == 'enabled'
    assert not (X / 'reboot-requested').exists()
    assert preboot(a)['boot_id'] == current['boot_id']
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=current['boot_id'],
                  source_paths_checked=current['compiled_source_paths_verified'],
                  helpers_exact_plan=len(helpers), units_exact_plan=len(units),
                  installed_unit_verify_passed=True, timers_enabled=True,
                  persistent_default='spx-known-good', next_entry_empty=True,
                  efi_bootnext_absent=True, boot_selected=False,
                  hardware_acceptance_closed=False)
    with (X / 'independent-deployment-review.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
