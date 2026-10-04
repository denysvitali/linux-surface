#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run sustained AW GPU validation after the independently verified baseline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from aw_boot_guard import X, RUNTIME, FIXTURE, RESULT, load, recovery, artifacts, trial_identity, sha


def main():
    os.umask(0o077)
    a = load()
    bid = trial_identity(a)
    assert 650 <= float(Path('/proc/uptime').read_text().split()[0]) < 900
    assert not (X / 'gpu-launch.json').exists() and not RESULT.exists()
    review = X / 'independent-result-review.json'
    if not review.exists():
        subprocess.run([sys.executable, str(RUNTIME / 'review-aw-baseline.py')], check=True, timeout=180)
    baseline = json.loads(review.read_text())
    assert baseline['boot_id'] == bid and baseline['scoped_passed'] and baseline['trial_passed']
    assert not baseline['fallback_stopped']
    assert not recovery(a).get('next_entry', '')
    artifacts(a)
    command = [sys.executable, str(RUNTIME / 'gpu-workload-20261003aw/collect.py'),
               '--fixture', str(FIXTURE), '--output', str(RESULT)]
    launch = {'boot_id': bid, 'release': a['release'], 'started': time.time(),
              'baseline_review_sha256': sha(review), 'command': command,
              'scene_seconds': 60, 'planned_render_seconds': 1800,
              'planned_idle_seconds': 180, 'hardware_acceptance_closed': False}
    (X / 'gpu-launch.json').write_text(json.dumps(launch, indent=2) + '\n')
    os.sync()
    result = {'boot_id': bid, 'returncode': None, 'hardware_acceptance_closed': False}
    try:
        with (X / 'gpu-service.log').open('xb') as out:
            completed = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, timeout=2250)
        result['returncode'] = completed.returncode
    except BaseException as error:
        result['failure'] = repr(error)
        raise
    finally:
        result['finished'] = time.time()
        (X / 'gpu-service-result.json').write_text(json.dumps(result, indent=2) + '\n')
        assert trial_identity(a) == bid
        os.sync()
    raise SystemExit(result['returncode'])


if __name__ == '__main__':
    main()
