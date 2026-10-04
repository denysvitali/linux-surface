#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive actual AX startup and one-use selection; leave timed collectors alone."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ax_boot_guard as guard
from ax_camera_core import decode, trial_findings


def main():
    os.umask(0o077)
    a = guard.load()
    bid = guard.trial_identity(a)
    env = guard.recovery(a)
    assert env.get('next_entry', '') == ''
    guard.artifacts(a)
    guard.frozen_prequeue(a)
    root = guard.X
    out = root / 'startup-review.partial'
    assert not out.exists() and not (root / 'startup-review').exists()
    out.mkdir(mode=0o700)
    read = lambda p: json.loads(p.read_text())
    queue = read(root / 'queue-review.json')
    immediate = read(root / 'reboot-check-passed.json')
    assert queue['preboot_id'] == immediate['boot_id'] == a['preboot_id']
    assert queue['selected_once'] and queue['request_marker_exclusive']
    assert queue['guarded_reboot_timer_active'] and queue['known_good_default']
    assert immediate['queued_entry'] == queue['entry'] == a['entry']
    assert immediate['saved_entry'] == 'spx-known-good'
    assert immediate['working_module_files_links_verified'] == 5183
    assert immediate['trial_module_files_verified'] == 208
    for name in ('queue-review.json', 'reboot-check-passed.json', 'grubenv.queued.txt',
                 'grubenv.immediate-preboot.txt', 'reboot-requested',
                 'outgoing-identity-marker.txt', 'deployment-sources-sha256.json'):
        shutil.copy2(root / name, out / name)
    manifests = {}
    for name in ('camera-provider-result', 'camera-control-result'):
        original = root / name
        expected = read(original / 'sha256.json')
        assert guard.files(original) == expected | {'sha256.json': guard.sha(original / 'sha256.json')}
        shutil.copytree(original, out / name)
        manifests[name] = {'files': len(expected), 'manifest_sha256': guard.sha(original / 'sha256.json')}
    reference_root = Path('/var/lib/spx-boot-diagnostics/attempts/20261002ap/camera-pmic-metadata-20261003')
    assert guard.sha(reference_root / 'sha256.json') == '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
    reference_hashes = read(reference_root / 'sha256.json')
    assert guard.files(reference_root) == reference_hashes | {'sha256.json': guard.sha(reference_root / 'sha256.json')}
    reference = read(reference_root / 'result.json')
    identity = {'boot_id': bid, 'release': a['release'], 'cmdline': Path('/proc/cmdline').read_text().strip(), 'taint': '0'}
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '0'
    camera = trial_findings(read(root / 'camera-control-result/report.json'),
                            read(root / 'camera-provider-result/report.json'),
                            decode(reference['reads']), identity)
    assert camera['camera_trial_passed']
    shutil.copy2(root / 'rtc-result.partial/progress.json', out / 'rtc-progress-snapshot.json')
    progress = read(out / 'rtc-progress-snapshot.json')
    assert all(progress[k] == identity[k] for k in ('boot_id', 'release', 'cmdline'))
    assert progress['observer_time_writes'] == 0
    samples = progress['samples']
    offsets = [{'monotonic': s['monotonic'], 'offset_lower_seconds': s['rtc_epoch'] - s['realtime_after'],
                'offset_upper_seconds': s['rtc_epoch'] + 1 - s['realtime_before'],
                'ntp_leap_status': s['ntp_leap_status']} for s in samples]
    for name, args in {
        'kernel-startup.log': ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'],
        'chrony-startup.log': ['journalctl', '-b', '-u', 'chronyd', '--no-pager', '-o', 'short-monotonic'],
        'systemd-services.txt': ['systemctl', 'show', *[f'spx-ax-{t}.service' for t in guard.TIMERS],
                                 'spx-ax-fallback.timer', '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState',
                                 '-p', 'Result', '-p', 'MainPID'],
        'timers.txt': ['systemctl', 'list-timers', '--all', '--no-pager'],
        'network.txt': ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device'],
        'efi.txt': ['efibootmgr'],
    }.items():
        (out / name).write_text(subprocess.check_output(args, text=True, timeout=30))
    assert guard.trial_identity(a) == bid
    report = dict(identity, uptime_seconds=float(Path('/proc/uptime').read_text().split()[0]),
                  queue_and_immediate_guard_verified=True, recovery_files_links_verified=5183,
                  candidate_files_verified=208, preparation_files_verified=518,
                  build_files_verified=499, prequeue_manifest_sha256=guard.sha(root / 'prequeue-records/sha256.json'),
                  saved_entry=env['saved_entry'], next_entry=env.get('next_entry', ''),
                  camera_initial=camera, camera_manifests=manifests,
                  rtc_samples_snapshotted=len(samples), rtc_sample_offsets=offsets,
                  rtc_final_result_pending=True, gpu_final_result_pending=True,
                  actual_return_pending=True, hardware_acceptance_closed=False)
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    shutil.copy2(Path(__file__), out / Path(__file__).name)
    (out / 'sha256.json').write_text(json.dumps(guard.files(out), indent=2) + '\n')
    os.sync()
    out.rename(root / 'startup-review')
    print(json.dumps({k: v for k, v in report.items() if k != 'rtc_sample_offsets'}, indent=2))
    print('startup_manifest_sha256', guard.sha(root / 'startup-review/sha256.json'))


if __name__ == '__main__':
    main()
