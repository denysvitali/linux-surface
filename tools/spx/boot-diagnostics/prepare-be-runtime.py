#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze BE's distinct identities, reused BC payload paths and bounded timers."""
import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as old

SRC = Path(__file__).resolve().parent
X = old.X.with_name('20261004be')
RUNTIME = old.RUNTIME
BOOT = '433a78d6-9748-422f-a1a7-aac43c784a7d'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bc+'
FIXTURE = Path('/var/lib/spx-boot-diagnostics/fixtures/video-media-20261003')
HELPERS = ('be_boot_guard.py', 'be-video.py', 'be-return.py', 'be-baseline.py',
           'be-camera-provider.py', 'be-camera-control.py', 'be_camera_core.py',
           'review-be-baseline.py', 'be-media.py', 'be-media-run.py',
           'be-reboot-check.py', 'be_startup_review.py', 'review-be-result.py')
ACTIONS = {'camera-provider': ('be-camera-provider.py', 60), 'video': ('be-video.py', 90),
           'camera-control': ('be-camera-control.py', 120), 'media': ('be-media.py', 180),
           'baseline': ('be-baseline.py', 620), 'fallback': ('be-return.py', 900)}


def write(path, data):
    with path.open('x') as stream:
        stream.write(data)


def write_json(path, value):
    write(path, json.dumps(value, indent=2) + '\n')


def function(path, name, namespace):
    bodies = [n for n in ast.parse(path.read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(bodies) == 1
    exec(compile(ast.Module(body=bodies, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    out = p.parse_args().out
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    parent = old.load()
    assert parent['state'].startswith('BD terminal;')
    assert not old.recovery(parent).get('next_entry', '')
    old.artifacts(parent)
    out.mkdir(mode=0o700)
    for name in HELPERS + ('prepare-be-runtime.py', 'verify-be-result-review.py', 'verify-be-startup-review.py'):
        ast.parse((SRC / name).read_text())
        shutil.copy2(SRC / name, out / name)
    cmdline = parent['cmdline'].replace('spx_attempt=20261004bd', 'spx_attempt=20261004be')
    assert set(cmdline.split()) - set(parent['cmdline'].split()) == {'spx_attempt=20261004be'}
    assert set(parent['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20261004bd'}
    for flag in ('qcom_scm.spx_pas_diag=1', 'qcom_scm.spx_pas_area_diag=1'):
        assert cmdline.split().count(flag) == 1
    entry = (old.X / 'entry.cfg').read_text().replace('/spx-trial-20261004bc/vmlinuz', '__EXACT_BC_KERNEL__')
    entry = entry.replace('/spx-trial-20261004bc/initramfs.img', '__EXACT_BC_INITRD__')
    entry = entry.replace('20261004bd', '20261004be').replace('BD bounded video allocation', 'BE static video reservation')
    entry = entry.replace('__EXACT_BC_KERNEL__', '/spx-trial-20261004bc/vmlinuz')
    entry = entry.replace('__EXACT_BC_INITRD__', '/spx-trial-20261004bc/initramfs.img')
    assert entry.count('--id spx-trial-20261004be') == 1
    assert ('linux /spx-trial-20261004bc/vmlinuz ' + cmdline + '; then') in entry
    assert 'devicetree /spx-trial-20261004be/spx.dtb; then' in entry
    assert 'initrd /spx-trial-20261004bc/initramfs.img; then' in entry
    write(out / 'entry.cfg', entry)
    write(out / 'cmdline', cmdline + '\n')
    subprocess.run(['grub-script-check', str(out / 'entry.cfg')], check=True, timeout=30)

    a = dict(preboot_id=BOOT, cmdline=cmdline)
    expected = 'BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz ' + cmdline
    state = dict(boot='00000000-0000-0000-0000-000000000001', release=RELEASE, cmdline=expected)

    class FakePath:
        def __init__(self, path):
            self.path = path

        def read_text(self):
            return state[{'/proc/sys/kernel/random/boot_id': 'boot', '/proc/cmdline': 'cmdline'}[self.path]]

    identity = function(out / 'be_boot_guard.py', 'trial_identity', dict(Path=FakePath, RELEASE=RELEASE,
        os=SimpleNamespace(uname=lambda: SimpleNamespace(release=state['release']))))
    original = dict(state)
    assert identity(a) == original['boot']
    corruptions = [('same-preboot', dict(boot=BOOT)),
                   ('wrong-release', dict(release='6.18.3-1-surface+')),
                   ('wrong-BE-release', dict(release='7.3.0-rc2-spx-mainline-20261004be+')),
                   ('wrong-image', dict(cmdline=expected.replace('BOOT_IMAGE=/spx-trial-20261004bc/', 'BOOT_IMAGE=/spx-trial-20261004be/'))),
                   ('old-attempt', dict(cmdline=expected.replace('spx_attempt=20261004be', 'spx_attempt=20261004bc'))),
                   ('parent-attempt', dict(cmdline=expected.replace('spx_attempt=20261004be', 'spx_attempt=20261004bd'))),
                   ('duplicate-attempt', dict(cmdline=expected + ' spx_attempt=20261004be')),
                   ('missing-attempt', dict(cmdline=expected.replace(' spx_attempt=20261004be', ''))),
                   ('changed-root', dict(cmdline=expected.replace('root=/dev/spx/root', 'root=/dev/wrong'))),
                   ('extra-option', dict(cmdline=expected + ' unexpected=1'))]
    for name, flag in (('pas', 'qcom_scm.spx_pas_diag=1'), ('area', 'qcom_scm.spx_pas_area_diag=1')):
        corruptions += [(name + '-missing', dict(cmdline=expected.replace(' ' + flag, ''))),
                        (name + '-disabled', dict(cmdline=expected.replace(flag, flag[:-1] + '0'))),
                        (name + '-duplicate', dict(cmdline=expected + ' ' + flag))]
    rejected = []
    for name, change in corruptions:
        state.clear()
        state.update(original | change)
        try:
            identity(a)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('Accepted invalid identity: ' + name)
    state.clear()
    state.update(original)
    assert identity(a) == original['boot']
    write_json(out / 'identity-review.json', dict(positive=1, rejected=rejected, mocked_os_reads=True))

    # Reuse BC's already verified frame comparison function byte-for-byte.
    frozen = old.X / 'build/runtime-plan/bc-media-run.py'
    before = next(n for n in ast.parse(frozen.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'frames')
    after = next(n for n in ast.parse((out / 'be-media-run.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'frames')
    assert ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False)
    assert old.sha(FIXTURE / 'sha256.json') == parent['media_fixture_manifest_sha256']
    for name, digest in json.loads((FIXTURE / 'sha256.json').read_text()).items():
        assert old.sha(FIXTURE / name) == digest
    write_json(out / 'media-review.json', dict(frame_parser_exact_frozen_bc=True,
        fixture_verified=True, reference_controls_reused=str(old.X / 'build/runtime-plan/media-reference-review.json'),
        reference_controls_sha256=old.sha(old.X / 'build/runtime-plan/media-reference-review.json')))

    units = []
    for action, (helper, delay) in ACTIONS.items():
        after_unit = ' spx-be-video.service' if action == 'media' else ''
        service, timer = out / ('spx-be-' + action + '.service'), out / ('spx-be-' + action + '.timer')
        write(service, f'[Unit]\nDescription=BE static reservation {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261004be\n'
            f'After=local-fs.target{after_unit}\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot /var/tmp\n\n'
            f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {RUNTIME / helper}\n'
            'TimeoutStartSec=300\nKillMode=control-group\n')
        write(timer, f'[Unit]\nDescription=BE {action} timer\nConditionKernelCommandLine=spx_attempt=20261004be\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-be-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
        units.extend([str(service), str(timer)])
    result = subprocess.run(['systemd-analyze', 'verify'] + units, capture_output=True, timeout=60)
    (out / 'unit-verify.stdout').write_bytes(result.stdout)
    (out / 'unit-verify.stderr').write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr.strip(), result.stderr.decode(errors='replace')
    write(out / '124-be-exclude.conf', '[Unit]\nConditionKernelCommandLine=!spx_attempt=20261004be\n')
    review = dict(utc=datetime.now(timezone.utc).isoformat(), helpers=len(HELPERS), units=len(units),
                  identity_positive_cases=1, identity_negative_cases=len(rejected),
                  cmdline_delta_exactly_attempt=True, exact_bc_executable_paths=True,
                  distinct_be_dtb_path=True, media_ordered_after_video=True,
                  timer_seconds={k: v[1] for k, v in ACTIONS.items()},
                  frame_parser_and_fixtures_verified=True, boot_id=BOOT,
                  installed=False, boot_selected=False, hardware_acceptance_closed=False)
    write_json(out / 'result.json', review)
    write_json(out / 'sha256.json', old.files(out))
    assert old.files(out) == json.loads((out / 'sha256.json').read_text()) | {'sha256.json': old.sha(out / 'sha256.json')}
    os.sync()
    print(json.dumps(review | dict(manifest_sha256=old.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
