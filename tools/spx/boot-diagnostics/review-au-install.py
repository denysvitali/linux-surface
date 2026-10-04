#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify installed AU, strict inherited criteria and fresh outgoing known-good evidence."""
import ast
import fcntl
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

SRC = Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from au_boot_guard import BASE, X, load, preboot, files, sha, command


def assignment(tree, name):
    return next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not (X / 'installed-review.json').exists()
    a = load()
    assert a['state'] == 'prepared AU; no boot selection'
    env = preboot(a)
    old = ast.parse((SRC / 'ar-finalize.py').read_text())
    new = ast.parse((SRC / 'au-baseline.py').read_text())
    same = ('passed', 'native_path_passed', 'touch_diag_passed', 'healthy', 'power_path_passed',
            'pin_state_passed', 'pin2_diagnostic', 'topology_preserved', 'declared_names',
            'firmware_identity_match', 'identity_diag_passed', 'right_init')
    for name in same:
        assert ast.dump(assignment(old, name)) == ast.dump(assignment(new, name)), name
    exp = assignment(new, 'passed')
    scope = {n.id: True for n in ast.walk(exp) if isinstance(n, ast.Name) and n.id != 'len'}
    scope.update(right_init=1, slim_devices=['a', 'b'], no_cards=False, force_start=0,
                 force_done=0, force_slaves=0, attached=1, wsa_mode='Y', wsa_init=1,
                 wsa_init_fail=0, wsa_status_fail=0, wsa_write_overflows=0,
                 wsa_read_underflows=0, taint='0')
    judge = compile(ast.Expression(exp), 'AU-scope', 'eval')
    assert eval(judge, {}, scope)
    negatives = ({'cmd_diag_passed': False}, {'native_path_passed': False}, {'right_init': 0},
                 {'topology_preserved': False}, {'pin_state_passed': False}, {'touch': False},
                 {'taint': '1'}, {'graph': False}, {'wifi': False})
    for patch in negatives:
        assert not eval(judge, {}, scope | patch), patch
    units = []
    for action, delay in (('baseline', 620), ('fallback', 3300), ('camera-provider', 60), ('camera-control', 120), ('gpu', 660), ('finalize', 2800)):
        timer = Path('/etc/systemd/system') / f'spx-au-{action}.timer'
        assert f'OnBootSec={delay}\n' in timer.read_text()
        for p in (timer, timer.with_suffix('.service')):
            assert 'ConditionKernelCommandLine=spx_attempt=20261003au\n' in p.read_text()
            units.append(str(p))
    with (X / 'units-verify.log').open('wb') as log:
        subprocess.run(['systemd-analyze', 'verify'] + units, stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=30)
    for path in ('/boot/grub/grub.cfg', '/boot/grub/custom.cfg'):
        subprocess.run(['grub-script-check', path], check=True, timeout=30)
    with (X / 'boot-guards-test.log').open('wb') as log:
        subprocess.run(['/usr/bin/python3', str(SRC / 'verify-au-boot-guards.py')],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    names = ('deploy-au.py', 'au_boot_guard.py', 'au_camera_core.py', 'au-return.py',
             'au-baseline.py', 'au-reboot-check.py', 'au-camera-provider.py', 'au-camera-control.py',
             'review-au-baseline.py', 'review-au-install.py', 'check-au-service-context.py',
             'verify-au-boot-guards.py', 'verify-au-criteria.py', 'freeze-au-prequeue.py',
             'queue-au-once.py', 'au-gpu.py', 'au-finalize.py', 'au_gpu_core.py',
             'verify-au-gpu-core.py', 'check-at-native-continuation.py', 'build-au.py',
             'assemble-au.py', 'archive-au.py', 'gpu-workload-20261003/collect.py',
             'gpu-workload-20261003/plan.json')
    with (X / 'gpu-core-test.log').open('wb') as log:
        subprocess.run(['/usr/bin/python3', str(SRC / 'verify-au-gpu-core.py')],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    gpu_test = json.loads((X / 'gpu-core-test.log').read_text())
    assert gpu_test['negative_cases'] == 26 and gpu_test['synthetic_only']
    # Verify the exact public fixture is readable by the benchmark account.
    from au_boot_guard import FIXTURE
    for path in sorted(FIXTURE.rglob('*')):
        if path.is_file():
            subprocess.run(['runuser', '-u', 'dvitali', '--', 'test', '-r', str(path)], check=True, timeout=30)
    with (X / 'criteria-test.log').open('wb') as log:
        subprocess.run(['/usr/bin/python3', str(SRC / 'verify-au-criteria.py')], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    criteria = json.loads((X / 'criteria-test.log').read_text())
    assert criteria['strict_scope_expressions_unchanged'] == 12 and criteria['camera_negative_cases'] == 39 and criteria['privacy_negative_cases'] == 18
    assert criteria['camera_final_negative_cases'] == 39 and criteria['camera_phase_timing_negative_cases'] == 6
    deployment = X / 'deployment-sources'
    deployment.mkdir(mode=0o700)
    for name in names:
        if name.endswith('.py'):
            ast.parse((SRC / name).read_text())
        (deployment / name).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(SRC / name, deployment / name)
    (X / 'deployment-sources-sha256.json').write_text(json.dumps(files(deployment), indent=2) + '\n')
    # Preserve the current known-good observations under the collector lock before reboot.
    subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'], check=True, timeout=90)
    snapshot = X / 'preboot-snapshot'
    snapshot.mkdir(mode=0o700)
    collector = BASE / 'boots' / a['preboot_id']
    with (collector / 'collect.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        shutil.copytree(collector, snapshot / 'collector', symlinks=True)
    for name, path in [('boot-id', '/proc/sys/kernel/random/boot_id'),
                       ('cmdline', '/proc/cmdline'), ('uptime', '/proc/uptime')]:
        (snapshot / name).write_text(Path(path).read_text())
    (snapshot / 'kernel.log').write_text(command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager') + '\n')
    (snapshot / 'dmesg-raw.log').write_text(command('dmesg', '--raw') + '\n')
    (snapshot / 'grubenv').write_text(command('grub-editenv', '/boot/grub/grubenv', 'list') + '\n')
    (snapshot / 'pstore-baseline-sha256.json').write_text(json.dumps(
        {name: files(snapshot / 'collector' / name) for name in ('pstore', 'pstore-archive')}, indent=2) + '\n')
    h = files(snapshot)
    (snapshot / 'sha256.json').write_text(json.dumps(h, indent=2) + '\n')
    assert files(snapshot) == h | {'sha256.json': sha(snapshot / 'sha256.json')}
    preboot(a)
    report = {'preboot_id': a['preboot_id'], 'release': a['release'], 'modules_verified': 208,
              'working_module_files_links_verified': 5183,
              'build_files_verified': len(json.loads((X / 'build-sha256.json').read_text())),
              'strict_ap_scope_unchanged': True, 'strict_scope_expressions': len(same),
              'strict_positive_cases': 1, 'strict_negative_cases': len(negatives),
              'guard_state_positive_cases': 2, 'guard_state_negative_cases': 10,
              'guard_freeze_positive_cases': 1, 'guard_freeze_negative_cases': 8, 'camera_positive_cases': 1,
              'camera_negative_cases': criteria['camera_negative_cases'], 'trial_truth_table_cases': 4,
              'trial_identity_negative_cases': 1, 'current_exports_full_build': True, 'gpu_core_negative_cases': 26,
              'camera_final_negative_cases': 39, 'privacy_negative_cases': 18, 'camera_phase_timing_negative_cases': 6,
              'outgoing_snapshot_files_verified': len(h),
              'outgoing_snapshot_manifest_sha256': sha(snapshot / 'sha256.json'),
              'deployment_sources_manifest_sha256': sha(X / 'deployment-sources-sha256.json'),
              'known_good_default': True, 'next_entry_empty': not env.get('next_entry', ''),
              'efi_bootnext_absent': True, 'boot_selected': False,
              'camera_registration_verified': False, 'hardware_acceptance_closed': False}
    (X / 'installed-review.json').write_text(json.dumps(report, indent=2) + '\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
