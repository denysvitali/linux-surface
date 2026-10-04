#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve BA's rejected preflight and freeze its reviewed new recovery identity."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ba_boot_guard as old

X = old.X
BASE = old.BASE
REPO = old.REPO
PLAN = X / 'runtime-plan-v2'
OUT = X / 'runtime-revision-v2'


def sha(path):
    return old.sha(path)


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def replace(path, value):
    temporary = path.with_name(path.name + '.runtime-v2-new')
    write(temporary, value)
    os.replace(temporary, path)


def verify_capsule(path):
    expected = json.loads((path / 'sha256.json').read_text())
    assert old.files(path) == expected | {'sha256.json': sha(path / 'sha256.json')}
    return sha(path / 'sha256.json')


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    a = old.load()
    assert a['state'] == 'prepared BA; no boot selection'
    assert a['preboot_id'] == '19cfd105-9780-4c85-995f-625bb1eb0529'
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot == '1f30baae-c6b5-403b-855d-6cf9d7040650'
    assert os.uname().release == a['preboot_release'] == '6.18.3-1-surface+'
    assert Path('/proc/cmdline').read_text().strip() == a['preboot_cmdline']
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '4096'
    assert old.recovery(a).get('next_entry', '') == ''
    old.artifacts(a)
    source_checked = old.source()
    assert not (X / 'reboot-requested').exists()
    failure_sha = verify_capsule(X / 'deployment-readiness-failure-v1')
    reboot_sha = verify_capsule(X / 'known-good-readiness-reboot-result')
    plan_sha = verify_capsule(PLAN)
    plan = json.loads((PLAN / 'sha256.json').read_text())
    changed = []
    for path, digest in a['runtime_sha256'].items():
        target = Path(path)
        if target.name not in plan:
            continue
        if plan[target.name] != digest:
            changed.append(path)
    guard = old.RUNTIME / 'ba_boot_guard.py'
    assert changed == [str(guard)], changed
    assert sha(REPO / 'tools/spx/boot-diagnostics/ba_boot_guard.py') == plan[guard.name]
    OUT.mkdir(mode=0o700)
    shutil.copy2(X / 'attempt.json', OUT / 'attempt-before.json')
    shutil.copy2(BASE / 'attempt.json', OUT / 'global-attempt-before.json')
    shutil.copy2(guard, OUT / 'installed-guard-v1.py')
    for name in ('ba_boot_guard.py', 'prepare-ba-runtime.py', 'review-ba-deployment.py',
                 'revise-ba-runtime-v2.py', 'ba-reboot-check.py'):
        shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, OUT / name)
    write(OUT / 'before-review.json', dict(utc=datetime.now(timezone.utc).isoformat(),
        current_boot_id=boot, original_preboot_id=a['preboot_id'],
        source_paths_verified=source_checked, changed_installed_helpers=changed,
        original_runtime_plan_manifest_sha256=a['runtime_plan_manifest_sha256'],
        revised_runtime_plan_manifest_sha256=plan_sha,
        deployment_failure_manifest_sha256=failure_sha,
        known_good_reboot_manifest_sha256=reboot_sha, boot_selected=False))
    os.sync()
    temporary = guard.with_name(guard.name + '.v2-new')
    assert not temporary.exists()
    shutil.copy2(PLAN / guard.name, temporary)
    os.chmod(temporary, 0o755)
    assert sha(temporary) == plan[guard.name]
    os.replace(temporary, guard)
    a['original_deployment_preboot_id'] = a['preboot_id']
    a['preboot_id'] = boot
    a['runtime_sha256'][str(guard)] = sha(guard)
    a['runtime_plan_path'] = str(PLAN)
    a['runtime_plan_manifest_sha256'] = plan_sha
    a['runtime_revision'] = dict(utc=datetime.now(timezone.utc).isoformat(),
        original_preboot_id=a['original_deployment_preboot_id'],
        known_good_touch_failed_on_both_boots=True,
        deployment_failure_manifest_sha256=failure_sha,
        known_good_reboot_manifest_sha256=reboot_sha,
        preboot_touch_is_recorded=True, strict_trial_touch_baseline_unchanged=True,
        revision_directory=str(OUT))
    replace(X / 'attempt.json', a)
    replace(BASE / 'attempt.json', a)
    shutil.copy2(X / 'attempt.json', OUT / 'attempt-after.json')
    write(OUT / 'sha256.json', old.files(OUT))
    os.sync()
    assert json.loads((BASE / 'attempt.json').read_text()) == a
    assert old.recovery(a).get('next_entry', '') == ''
    old.artifacts(a)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    print(json.dumps(dict(runtime_revision_manifest_sha256=sha(OUT / 'sha256.json'),
        runtime_plan_manifest_sha256=plan_sha, boot_id=boot,
        installed_guard_sha256=sha(guard), selected=False), indent=2))


if __name__ == '__main__':
    main()
