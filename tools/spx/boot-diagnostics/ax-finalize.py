#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive/recompute the actual AX GPU run and preserve post-load regression state."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from ax_boot_guard import X, RUNTIME, RESULT, load, recovery, artifacts, trial_identity, files, sha


def main():
    os.umask(0o077)
    a = load()
    bid = trial_identity(a)
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    assert 2750 <= uptime < 3300
    assert not (X / 'gpu-final-result').exists()
    assert not recovery(a).get('next_entry', '')
    artifacts(a)
    out = X / 'gpu-final-result.partial'
    out.mkdir(mode=0o700)
    report = {'attempt': a['attempt'], 'boot_id': bid, 'release': a['release'],
              'uptime_seconds': uptime, 'scoped_passed': False,
              'gpu_scoped_passed': False, 'rtc_sync_scoped_passed': False,
              'hardware_acceptance_closed': False, 'fallback_stopped': False,
              'limits': ['Sustained GL/GLES offscreen rendering uses the explicitly selected high-precision conditional scene.',
                         'Default-precision GLES oracle discrepancy remains unresolved.',
                         'The GNOME process staying alive does not prove heavy desktop compositing or visual correctness.',
                         'Other hardware acceptance and common final-candidate regression remain open.']}
    try:
        state = subprocess.check_output(['systemctl', 'show', 'spx-ax-gpu.service',
            '-p', 'ActiveState', '--value'], text=True).strip()
        assert state in ('inactive', 'failed'), state
        assert (RESULT / 'sha256.json').is_file()
        expected = json.loads((RESULT / 'sha256.json').read_text())
        assert files(RESULT) == expected | {'sha256.json': sha(RESULT / 'sha256.json')}
        shutil.copytree(RESULT, out / 'workload')
        evidence = json.loads((out / 'workload/progress.json').read_text())
        sys.path.insert(0, str(RUNTIME / 'gpu-workload-20261003ax'))
        from collect import parse_result, FAULTS
        from ax_gpu_core import assess, clean_touch
        plan = json.loads((RUNTIME / 'gpu-workload-20261003ax/plan.json').read_text())
        verdict = assess(evidence, out / 'workload', plan, {
            'boot_id': bid, 'release': a['release'],
            'cmdline': 'BOOT_IMAGE=/spx-trial-20261003ax/vmlinuz ' + a['cmdline'],
            'plan_sha256': sha(RUNTIME / 'gpu-workload-20261003ax/plan.json'),
            'collector_sha256': sha(RUNTIME / 'gpu-workload-20261003ax/collect.py'),
            'fixture_manifest_sha256': a['gpu_fixture_manifest_sha256']}, parse_result, FAULTS)
        report.update({'gpu_scoped_passed': True, **verdict})
        assert subprocess.check_output(['systemctl', 'show', 'spx-ax-rtc.service',
            '-p', 'ActiveState', '--value'], text=True).strip() in ('inactive', 'failed')
        shutil.copytree(X / 'rtc-result', out / 'rtc-result')
        from ax_rtc_review import review as review_rtc
        rtc_review = review_rtc(out / 'rtc-result', {
            'boot_id': bid, 'release': a['release'],
            'cmdline': 'BOOT_IMAGE=/spx-trial-20261003ax/vmlinuz ' + a['cmdline'],
            'config_sha256': sha(X / 'build/artifacts/.config'),
            'probe_sha256': a['rtc_probe_sha256']})
        report.update(rtc_sync_scoped_passed=True, rtc_review=rtc_review)
        baseline = json.loads((X / 'independent-result-review.json').read_text())
        assert baseline['boot_id'] == bid and baseline['scoped_passed'] and baseline['trial_passed']
        touch = {n: (Path('/sys/bus/spi/devices/spi0.0') / n).read_text().strip()
                 for n in ('ready', 'bus_error_count', 'logic_error_count', 'regulator_error_count', 'device_initiated_reset_count')}
        (out / 'touch-state.json').write_text(json.dumps(touch, indent=2) + '\n')
        assert clean_touch(touch), touch
        network = subprocess.check_output(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'], text=True)
        (out / 'network').write_text(network)
        assert 'wlan0:wifi:connected' in network.splitlines()
        assert Path('/proc/sys/kernel/tainted').read_text().strip() == '0'
        kernel = subprocess.check_output(['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], text=True)
        (out / 'kernel-at-finalize.log').write_text(kernel)
        assert not FAULTS.findall(kernel)
        report.update({'scoped_passed': True, **verdict,
                       'baseline_review_sha256': sha(X / 'independent-result-review.json'),
                       'wifi_connected': True, 'touch_ready_zero_counters': True})
    except BaseException as error:
        report['failure'] = repr(error)
        state = subprocess.check_output(['systemctl', 'show', 'spx-ax-gpu.service',
            '-p', 'ActiveState', '--value'], text=True).strip()
        if state in ('inactive', 'failed') and RESULT.exists() and not (out / 'workload').exists():
            shutil.copytree(RESULT, out / 'workload', symlinks=True)
        if (X / 'rtc-result').exists() and not (out / 'rtc-result').exists():
            shutil.copytree(X / 'rtc-result', out / 'rtc-result', symlinks=True)
    finally:
        try:
            subprocess.run([str(RUNTIME / 'collect.sh')], check=True, timeout=120)
        except BaseException as error:
            report['scoped_passed'] = False
            report['final_collection_failure'] = repr(error)
        assert trial_identity(a) == bid
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
        os.sync()
        out.rename(X / 'gpu-final-result')
    # Keep recovery armed even after a scoped GPU pass; no feature was accepted.
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
