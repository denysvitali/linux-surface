#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze and syntax-check AZ collection/recovery helpers while its build runs."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
SRC = REPO / 'tools/spx/boot-diagnostics'
STAGE = Path('/var/tmp/spx-mainline-trial-20261003az')
RUNTIME = Path('/usr/local/lib/spx-boot-diagnostics')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    out = STAGE / 'runtime-plan'
    out.mkdir(mode=0o700)
    helpers = ('az_boot_guard.py', 'az-video.py', 'az-return.py', 'az-baseline.py',
               'az-camera-provider.py', 'az-camera-control.py', 'az_camera_core.py',
               'review-az-baseline.py', 'az-media.py', 'az-media-run.py',
               'az-reboot-check.py', 'deploy-az.py', 'review-az-preparation.py',
               'prepare-az-runtime.py')
    for name in helpers:
        path = SRC / 'video-media-20261003/run-az.py' if name == 'az-media-run.py' else SRC / name
        ast.parse(path.read_text())
        shutil.copy2(path, out / name)
    actions = {'camera-provider': ('az-camera-provider.py', 60), 'video': ('az-video.py', 90),
               'camera-control': ('az-camera-control.py', 120), 'media': ('az-media.py', 180),
               'baseline': ('az-baseline.py', 620), 'fallback': ('az-return.py', 900)}
    units = []
    for action, (helper, delay) in actions.items():
        service = out / f'spx-az-{action}.service'
        service.write_text(f'[Unit]\nDescription=AZ Iris1 startup {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261003az\nAfter=local-fs.target\n'
            'RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot /var/tmp\n\n'
            f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {RUNTIME / helper}\n'
            'TimeoutStartSec=300\nKillMode=control-group\n')
        timer = out / f'spx-az-{action}.timer'
        timer.write_text(f'[Unit]\nDescription=AZ {action} timer\nConditionKernelCommandLine=spx_attempt=20261003az\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-az-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
        units.extend([str(service), str(timer)])
    result = subprocess.run(['systemd-analyze', 'verify'] + units, capture_output=True, timeout=60)
    (out / 'unit-verify.stdout').write_bytes(result.stdout)
    (out / 'unit-verify.stderr').write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr.strip(), result.stderr.decode(errors='replace')
    (out / '122-az-exclude.conf').write_text('[Unit]\nConditionKernelCommandLine=!spx_attempt=20261003az\n')
    for name in ('spx-az-identity-review.json', 'spx-media-reference-review-20261003.json'):
        shutil.copy2(Path('/var/tmp') / name, out / name)
    review = dict(helpers_parsed=len(helpers), units_verified=len(units),
                  identity_positive_cases=1, identity_negative_cases=6,
                  media_reference_pairs=2, media_negative_controls=5,
                  startup_seconds=90, media_seconds=180, baseline_seconds=620,
                  fallback_seconds=900, installed=False, boot_selected=False,
                  hardware_operations=0, hardware_acceptance_closed=False)
    (out / 'result.json').write_text(json.dumps(review, indent=2) + '\n')
    hashes = {path.name: sha(path) for path in sorted(out.iterdir()) if path.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps(review | {'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
