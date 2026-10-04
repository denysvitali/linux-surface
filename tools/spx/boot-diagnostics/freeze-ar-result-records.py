#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze the actual independently reviewed AR outcome without changing fallback."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ar_boot_guard import X, REPO, command, files, load, recovery, sha


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    a = load()
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '5b14cce2-951f-4b43-a786-3cd2339f79b5' != a['preboot_id']
    assert os.uname().release == a['release']
    assert Path('/proc/cmdline').read_text().split() == [
        'BOOT_IMAGE=/spx-trial-20261003ar/vmlinuz'] + a['cmdline'].split()
    assert not recovery(a).get('next_entry', '')
    directories = ('final-result', 'camera-provider-result', 'handoff-review',
                   'startup-discovery')
    for name in directories:
        root = X / name
        expected = json.loads((root / 'sha256.json').read_text())
        assert files(root) == expected | {'sha256.json': sha(root / 'sha256.json')}
    result = json.loads((X / 'final-result/result.json').read_text())
    review = json.loads((X / 'independent-result-review.json').read_text())
    action = json.loads((X / 'finalizer-action.json').read_text())
    provider = json.loads((X / 'camera-provider-review.json').read_text())
    touch = json.loads((X / 'touch-startup-review.json').read_text())
    assert all(r['boot_id'] == bid for r in (result, review, action, provider, touch))
    passed = result['passed_scoped_baseline']
    assert type(passed) is bool and review['scoped_passed'] == passed
    assert action['fallback_stopped'] == review['fallback_stopped'] == passed
    assert action['result_sha256'] == sha(X / 'final-result/result.json')
    assert action['manifest_sha256'] == review['result_manifest_sha256'] == sha(
        X / 'final-result/sha256.json')
    assert provider['result_manifest_sha256'] == sha(X / 'camera-provider-result/sha256.json')
    assert touch['final_result_manifest_sha256'] == sha(X / 'final-result/sha256.json')
    assert touch['final_scoped_baseline_passed'] == passed
    fallback_armed = command('systemctl', 'show', 'spx-ar-fallback.timer',
                             '-p', 'ActiveState', '--value') == 'active'
    assert fallback_armed != passed
    out = X / 'post-result-records'
    assert not out.exists()
    inputs = {name: X / name for name in (
        'attempt.json', 'independent-result-review.json', 'camera-provider-review.json',
        'touch-startup-review.json', 'finalizer-action.json')}
    inputs |= {name + '-sha256.json': X / name / 'sha256.json' for name in directories}
    inputs |= {name: REPO / name for name in ('PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md')}
    helpers = REPO / 'tools/spx/boot-diagnostics'
    inputs |= {name: helpers / name for name in (
        'RESULT-20261003ar.md', 'PREPARED-20261003ar.md', 'snapshot-ar-startup.py',
        'review-ar-touch.py', 'review-ar-result.py', 'archive-ar-return.py',
        Path(__file__).name)}
    assert all(p.is_file() and not p.is_symlink() for p in inputs.values())
    expected = {name: sha(p) for name, p in inputs.items()}
    out.mkdir(mode=0o700)
    for name, path in inputs.items():
        shutil.copy2(path, out / name)
    assert files(out) == expected
    report = {
        'attempt': a['attempt'], 'boot_id': bid,
        'uptime': Path('/proc/uptime').read_text().strip(),
        'baseline_passed': passed,
        'provider_registration_verified': provider['provider_registration_verified'],
        'fallback_armed': fallback_armed, 'actual_recovery_return_observed': False,
        'known_good_default_verified': True, 'next_entry_empty': True,
        'hardware_acceptance_checks_remaining': 47}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = files(out)
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    assert files(out) == hashes | {'sha256.json': sha(out / 'sha256.json')}
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert not recovery(a).get('next_entry', '')
    os.sync()
    print(json.dumps(report | {'files_verified': len(hashes),
                              'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
