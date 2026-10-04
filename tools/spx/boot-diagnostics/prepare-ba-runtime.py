#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze BA's helpers/units and exercise actual identity/frame parser bodies."""
import ast
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
SRC = REPO / 'tools/spx/boot-diagnostics'
STAGE = Path('/var/tmp/spx-mainline-trial-20261004ba')
RUNTIME = Path('/usr/local/lib/spx-boot-diagnostics')
FIXTURE = Path('/var/lib/spx-boot-diagnostics/fixtures/video-media-20261003')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(path, name, namespace):
    tree = ast.parse(path.read_text())
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(body) == 1
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=STAGE / 'runtime-plan')
    out = parser.parse_args().output
    out.mkdir(mode=0o700)
    helpers = ('ba_boot_guard.py', 'ba-video.py', 'ba-return.py', 'ba-baseline.py',
               'ba-camera-provider.py', 'ba-camera-control.py', 'ba_camera_core.py',
               'review-ba-baseline.py', 'ba-media.py', 'ba-media-run.py',
               'ba-reboot-check.py', 'deploy-ba.py', 'review-ba-preparation.py',
               'review-ba-deployment.py', 'prepare-ba-runtime.py')
    for name in helpers:
        path = SRC / name
        ast.parse(path.read_text())
        shutil.copy2(path, out / name)

    # Run the actual trial_identity function with only OS reads replaced.
    parent = json.loads(Path('/var/lib/spx-boot-diagnostics/attempt.json').read_text())
    assert parent['attempt'] in ('20261003az', '20261004ba')
    cmdline = parent['cmdline'].replace('spx_attempt=20261003az', 'spx_attempt=20261004ba')
    a = dict(preboot_id='19cfd105-9780-4c85-995f-625bb1eb0529', cmdline=cmdline)
    expected = 'BOOT_IMAGE=/spx-trial-20261004ba/vmlinuz ' + cmdline
    state = dict(boot='00000000-0000-0000-0000-000000000001',
                 release='7.3.0-rc2-spx-mainline-20261004ba+', cmdline=expected)

    class FakePath:
        def __init__(self, path):
            self.path = path

        def read_text(self):
            return state[{'/proc/sys/kernel/random/boot_id': 'boot',
                          '/proc/cmdline': 'cmdline'}[self.path]]

    identity = function(out / 'ba_boot_guard.py', 'trial_identity',
                        dict(Path=FakePath, os=SimpleNamespace(uname=lambda: SimpleNamespace(
                            release=state['release'])), RELEASE=state['release']))
    original = dict(state)
    assert identity(a) == state['boot']
    rejected = []
    for name, change in [
            ('same-preboot', dict(boot=a['preboot_id'])),
            ('wrong-release', dict(release='6.18.3-1-surface+')),
            ('wrong-image', dict(cmdline=expected.replace('BOOT_IMAGE=/spx-trial-20261004ba/',
                                                        'BOOT_IMAGE=/spx-trial-20261003az/'))),
            ('wrong-attempt', dict(cmdline=expected.replace('spx_attempt=20261004ba',
                                                          'spx_attempt=20261003az'))),
            ('duplicate-attempt', dict(cmdline=expected + ' spx_attempt=20261004ba')),
            ('missing-attempt', dict(cmdline=expected.replace(' spx_attempt=20261004ba', ''))),
            ('changed-root', dict(cmdline=expected.replace('root=/dev/spx/root', 'root=/dev/wrong'))),
            ('extra-option', dict(cmdline=expected + ' unexpected=1'))]:
        state.clear()
        state.update(original | change)
        try:
            identity(a)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError(f'Accepted invalid trial identity: {name}')
    state.clear()
    state.update(original)
    assert identity(a) == original['boot']
    (out / 'identity-review.json').write_text(json.dumps(dict(
        positive_cases=1, rejected_cases=rejected, mocked_os_reads=True), indent=2) + '\n')

    frames = function(out / 'ba-media-run.py', 'frames', dict(re=re))
    for name in ('baseline', 'high-bframes'):
        assert frames(FIXTURE / (name + '-reference.framemd5')) == frames(
            FIXTURE / (name + '-repeat.framemd5'))
    reference = FIXTURE / 'baseline-reference.framemd5'
    good = frames(reference)
    rows = [line for line in reference.read_text().splitlines() if line and not line.startswith('#')]
    controls = out / 'frame-controls'
    controls.mkdir()
    negative = []
    for name in ('drop', 'reorder', 'pixels', 'size', 'hash', 'timestamp', 'duration'):
        changed = list(rows)
        if name == 'drop':
            changed.pop()
        elif name == 'reorder':
            changed[0], changed[1] = changed[1], changed[0]
        else:
            parts = [part.strip() for part in changed[0].split(',')]
            index, value = {'pixels': (5, '0' * 32), 'size': (4, '1'),
                            'hash': (5, 'invalid'), 'timestamp': (2, '1'),
                            'duration': (3, '2')}[name]
            parts[index] = value
            changed[0] = ', '.join(parts)
        path = controls / (name + '.framemd5')
        path.write_text('\n'.join(changed) + '\n')
        try:
            bad = frames(path)
        except (AssertionError, ValueError):
            negative.append(dict(name=name, parser_rejected=True))
        else:
            assert bad != good, f'Accepted corrupt output: {name}'
            negative.append(dict(name=name, pixel_comparison_rejected=True))
    (out / 'media-reference-review.json').write_text(json.dumps(dict(
        reference_pairs=2, invalid_outputs=negative, hardware_operations=0), indent=2) + '\n')

    actions = {'camera-provider': ('ba-camera-provider.py', 60), 'video': ('ba-video.py', 90),
               'camera-control': ('ba-camera-control.py', 120), 'media': ('ba-media.py', 180),
               'baseline': ('ba-baseline.py', 620), 'fallback': ('ba-return.py', 900)}
    units = []
    for action, (helper, delay) in actions.items():
        service = out / f'spx-ba-{action}.service'
        service.write_text(f'[Unit]\nDescription=BA Iris1 startup {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261004ba\nAfter=local-fs.target\n'
            'RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot /var/tmp\n\n'
            f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {RUNTIME / helper}\n'
            'TimeoutStartSec=300\nKillMode=control-group\n')
        timer = out / f'spx-ba-{action}.timer'
        timer.write_text(f'[Unit]\nDescription=BA {action} timer\nConditionKernelCommandLine=spx_attempt=20261004ba\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ba-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
        units.extend([str(service), str(timer)])
    result = subprocess.run(['systemd-analyze', 'verify'] + units, capture_output=True, timeout=60)
    (out / 'unit-verify.stdout').write_bytes(result.stdout)
    (out / 'unit-verify.stderr').write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr.strip(), result.stderr.decode(errors='replace')
    (out / '123-ba-exclude.conf').write_text('[Unit]\nConditionKernelCommandLine=!spx_attempt=20261004ba\n')
    review = dict(helpers_parsed=len(helpers), units_verified=len(units),
                  identity_positive_cases=1, identity_negative_cases=len(rejected),
                  media_reference_pairs=2, media_negative_controls=len(negative),
                  startup_seconds=90, media_seconds=180, baseline_seconds=620,
                  fallback_seconds=900, installed=False, boot_selected=False,
                  hardware_operations=0, hardware_acceptance_closed=False)
    (out / 'result.json').write_text(json.dumps(review, indent=2) + '\n')
    hashes = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*')) if path.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps(review | {'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
