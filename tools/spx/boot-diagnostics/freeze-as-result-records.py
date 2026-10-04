#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze AS's actual combined result, camera evidence and reviewed dependencies."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from as_boot_guard import X, REPO, command, files, load, recovery, sha


def verify(root, manifest_name='sha256.json'):
    expected = json.loads((root / manifest_name).read_text())
    assert files(root) == expected | {manifest_name: sha(root / manifest_name)}


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    a = load()
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '29748fff-2312-42c5-982e-04bbd2304b52' != a['preboot_id']
    assert os.uname().release == a['release']
    assert Path('/proc/cmdline').read_text().split() == [
        'BOOT_IMAGE=/spx-trial-20261003as/vmlinuz'] + a['cmdline'].split()
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '0'
    assert not recovery(a).get('next_entry', '')
    directories = ('final-result', 'camera-provider-result', 'camera-control-result',
                   'camera-control-final-result', 'handoff-review', 'startup-discovery',
                   'initial-result-review-failure')
    for name in directories:
        verify(X / name)
    audit = X / 'offline-capture-dependency-audit-20261003'
    verify(audit, 'archive-sha256.json')
    result = json.loads((X / 'final-result/result.json').read_text())
    review = json.loads((X / 'independent-result-review.json').read_text())
    action = json.loads((X / 'finalizer-action.json').read_text())
    provider = json.loads((X / 'camera-provider-review.json').read_text())
    touch = json.loads((X / 'touch-startup-review.json').read_text())
    cameras = [json.loads((X / name).read_text()) for name in (
        'camera-control-review.json', 'camera-control-final-review.json')]
    assert all(r['boot_id'] == bid for r in (result, review, action, provider, touch, *cameras))
    assert result['passed_scoped_baseline'] is True and review['scoped_passed'] is True
    assert result['passed_trial'] is True and review['trial_passed'] is True
    assert action['fallback_stopped'] is True and review['fallback_stopped'] is True
    for key in ('camera_control_initial_passed', 'camera_control_final_passed',
                'camera_observations_ordered', 'camera_control_passed',
                'camera_provider_idle_passed', 'camera_trial_passed'):
        assert result[key] is True and review[key] is True
    assert action['result_sha256'] == sha(X / 'final-result/result.json')
    assert action['manifest_sha256'] == review['result_manifest_sha256'] == sha(
        X / 'final-result/sha256.json')
    assert provider['result_manifest_sha256'] == sha(X / 'camera-provider-result/sha256.json')
    assert touch['final_result_manifest_sha256'] == sha(X / 'final-result/sha256.json')
    assert touch['final_scoped_baseline_passed'] is True
    assert touch['clean_logged_sequences'] is True and touch['clean_touch_startup'] is True
    for camera, label in zip(cameras, ('camera-control-result', 'camera-control-final-result')):
        assert camera['control_passed'] is True and camera['normal_probe_identity_check_completed'] is True
        assert camera['control_manifest_sha256'] == sha(X / label / 'sha256.json')
        assert camera['provider_manifest_sha256'] == provider['result_manifest_sha256']
        assert camera['camera_functional_acceptance'] is False
    assert cameras[0]['collection_phase'] == 'initial' and cameras[1]['collection_phase'] == 'final'
    fallback_armed = command('systemctl', 'show', 'spx-as-fallback.timer',
                             '-p', 'ActiveState', '--value') == 'active'
    assert not fallback_armed
    helpers = REPO / 'tools/spx/boot-diagnostics'
    original = (helpers / 'review-as-result.py').read_text()
    revised = (helpers / 'review-as-result-v2.py').read_text()
    expected_v2 = original.replace("archive['build_symlinks_verified']", "archive['build_links_verified']").replace(
        "Rehash AS's right command-history diagnostic and bounded touch diagnostic result.",
        'Rehash AS result; v2 uses the explicit-reuse archive build_links_verified key.')
    assert revised == expected_v2
    assert sha(helpers / 'review-as-result.py') == sha(X / 'initial-result-review-failure/review-as-result.py')
    for name, digest in json.loads((X / 'deployment-sources-sha256.json').read_text()).items():
        assert sha(helpers / name) == digest
    checklist = (REPO / 'PORT-CHECKLIST.md').read_text()
    assert sum(line.startswith('- [ ] **') for line in checklist.splitlines()) == 47
    out = X / 'post-result-records'
    assert not out.exists()
    inputs = {name: X / name for name in (
        'attempt.json', 'independent-result-review.json', 'camera-provider-review.json',
        'camera-control-review.json', 'camera-control-final-review.json',
        'touch-startup-review.json', 'finalizer-action.json', 'archive-review.json',
        'reboot-check-passed.json', 'deployment-sources-sha256.json')}
    inputs |= {name + '-sha256.json': X / name / 'sha256.json' for name in directories}
    inputs['offline-capture-dependency-audit-archive-sha256.json'] = audit / 'archive-sha256.json'
    inputs |= {name: REPO / name for name in ('PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md')}
    inputs |= {name: helpers / name for name in (
        'RESULT-20261003as.md', 'PREPARED-20261003as.md', 'snapshot-as-startup.py',
        'review-as-touch.py', 'review-as-result.py', 'review-as-result-v2.py',
        'review-as-camera-control.py', 'review-as-camera-provider.py',
        'as_camera_core.py', Path(__file__).name)}
    assert all(p.is_file() and not p.is_symlink() for p in inputs.values())
    expected = {name: sha(p) for name, p in inputs.items()}
    out.mkdir(mode=0o700)
    for name, path in inputs.items():
        shutil.copy2(path, out / name)
    assert files(out) == expected
    report = {
        'attempt': a['attempt'], 'boot_id': bid,
        'uptime': Path('/proc/uptime').read_text().strip(),
        'baseline_passed': True, 'combined_trial_passed': True,
        'initial_and_final_camera_verified': True,
        'provider_idle_verified': True, 'clean_touch_verified': True,
        'original_deployment_sources_unchanged': True,
        'v2_reviewer_delta_limited_to_archive_key_and_docstring': True,
        'fallback_armed': False, 'actual_recovery_return_observed': False,
        'known_good_default_verified': True, 'next_entry_empty': True,
        'camera_capture_verified': False, 'hardware_acceptance_checks_remaining': 47}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = files(out)
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    verify(out)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert not recovery(a).get('next_entry', '')
    os.sync()
    print(json.dumps(report | {'files_verified': len(hashes),
                              'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
