#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify AW's sealed baseline/workload and archive the actual known-good return.

This runs after recovery. It never selects a boot or changes a frozen observer.
The frozen baseline review is replayed with only its output filename redirected;
its findings must equal the review made on the actual trial.
"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from aw_boot_guard import X, RUNTIME, RESULT, REPO, load, recovery, artifacts, files, sha
from aw_gpu_core import assess, clean_touch


def read(path):
    return json.loads(path.read_text())


def sealed(root):
    expected = read(root / 'sha256.json')
    assert files(root) == expected | {'sha256.json': sha(root / 'sha256.json')}, root
    return {'files': len(expected), 'manifest_sha256': sha(root / 'sha256.json')}


def command(*args):
    return subprocess.check_output(args, text=True, timeout=180)


def main():
    os.umask(0o077)
    a = load()
    current = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert os.uname().release == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    assert current != a['preboot_id']
    out = X / 'return-result.partial'
    assert not out.exists() and not (X / 'return-result').exists()
    out.mkdir(mode=0o700)
    env = recovery(a)
    assert not env.get('next_entry', '')
    artifacts(a)
    frozen = {}
    for attempt, count in (('20261003at', 24), ('20261003au', 25),
                           ('20261003av', 25), ('20261003aw', 26)):
        parent = X.parent / attempt
        manifest = read(parent / 'deployment-sources-sha256.json')
        assert len(manifest) == count
        for name, digest in manifest.items():
            assert sha(parent / 'deployment-sources' / name) == digest
            assert sha(REPO / 'tools/spx/boot-diagnostics' / name) == digest
        frozen[attempt] = {'files': count, 'manifest_sha256': sha(parent / 'deployment-sources-sha256.json')}
    preparation = read(X / 'preparation-sha256.json')
    assert len(preparation) == 514
    for name, digest in preparation.items():
        assert sha(X / name) == digest, name
    baseline = sealed(X / 'final-result')
    original = read(X / 'independent-result-review.json')
    script = X / 'deployment-sources/review-aw-baseline.py'
    tree = ast.parse(script.read_text())

    class Redirect(ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value == 'independent-result-review.json':
                return ast.copy_location(ast.Constant('offline-baseline-review.json'), node)
            return node

    tree = ast.fix_missing_locations(Redirect().visit(tree))
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(tree, str(script), 'exec'), {'__name__': '__main__'})
    recomputed = read(X / 'offline-baseline-review.json')
    assert original == recomputed and recomputed['trial_passed'] and recomputed['scoped_passed']
    gpu = sealed(X / 'gpu-final-result')
    workload = X / 'gpu-final-result/workload'
    workload_manifest = sealed(workload)
    assert files(workload) == files(RESULT)
    sys.path.insert(0, str(RUNTIME / 'gpu-workload-20261003aw'))
    from collect import parse_result, FAULTS
    plan = read(RUNTIME / 'gpu-workload-20261003aw/plan.json')
    evidence = read(workload / 'progress.json')
    bid = original['boot_id']
    assert current != bid
    verdict = assess(evidence, workload, plan, {
        'boot_id': bid, 'release': a['release'],
        'cmdline': 'BOOT_IMAGE=/spx-trial-20261003aw/vmlinuz ' + a['cmdline'],
        'plan_sha256': sha(RUNTIME / 'gpu-workload-20261003aw/plan.json'),
        'collector_sha256': sha(RUNTIME / 'gpu-workload-20261003aw/collect.py'),
        'fixture_manifest_sha256': a['gpu_fixture_manifest_sha256']}, parse_result, FAULTS)
    final = read(X / 'gpu-final-result/result.json')
    assert final['boot_id'] == bid and final['scoped_passed']
    assert final['baseline_review_sha256'] == sha(X / 'independent-result-review.json')
    assert all(final[k] == v for k, v in verdict.items())
    assert final['hardware_acceptance_closed'] is False and final['fallback_stopped'] is False
    assert clean_touch(read(X / 'gpu-final-result/touch-state.json'))
    assert 'wlan0:wifi:connected' in (X / 'gpu-final-result/network').read_text().splitlines()
    assert not FAULTS.findall((X / 'gpu-final-result/kernel-at-finalize.log').read_text())
    load_runs = []
    for run in evidence['runs']:
        if run['validation']:
            continue
        samples = run['fd_samples']
        active = [s for s in samples if s['gpu_power']['runtime_status'] == 'active']
        assert active and all(plan['render_node'] in s['nodes'] for s in active)
        delta = int(samples[-1]['gpu_power']['runtime_active_time']) - int(samples[0]['gpu_power']['runtime_active_time'])
        assert delta >= 290000
        load_runs.append({'label': run['label'], 'elapsed_seconds': run['elapsed_seconds'],
                          'active_samples': len(active), 'active_time_delta_ms': delta})
    for idle in verdict['idle_windows']:
        start, end = idle['start_gpu_power'], idle['end_gpu_power']
        assert start['runtime_status'] == end['runtime_status'] == 'suspended'
        assert int(end['runtime_suspended_time']) - int(start['runtime_suspended_time']) >= 29000
    fallback = read(X / 'fallback-recovery-check.json')
    assert fallback['boot_id'] == bid and fallback['uptime_seconds'] >= 3300
    assert all(fallback[k] for k in ('known_good_payloads_modules_entry_verified', 'next_entry_empty', 'efi_bootnext_absent'))
    journal_bid = bid.replace('-', '')
    kernel = command('journalctl', '-b', journal_bid, '-k', '--no-pager', '-o', 'short-monotonic')
    journal = command('journalctl', '-b', journal_bid, '--no-pager', '-o', 'short-monotonic')
    entries = [json.loads(line) for line in command('journalctl', '-b', journal_bid, '-k', '--no-pager', '-o', 'json').splitlines()]
    assert entries and all(e['_BOOT_ID'] == bid.replace('-', '') for e in entries)
    assert a['release'] in kernel and 'spx_attempt=20261003aw' in kernel
    assert not FAULTS.findall(kernel)
    assert 'Reached target System Reboot' in journal and 'spx-aw-fallback.service' in journal
    for name, data in {'trial-kernel-through-return.log': kernel, 'trial-journal-through-return.log': journal,
                       'current-kernel.log': command('journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'),
                       'grubenv': command('grub-editenv', '/boot/grub/grubenv', 'list'),
                       'efibootmgr': command('efibootmgr'), 'current-cmdline': Path('/proc/cmdline').read_text(),
                       'current-boot-id': current + '\n', 'current-release': os.uname().release + '\n',
                       'current-taint': Path('/proc/sys/kernel/tainted').read_text()}.items():
        (out / name).write_text(data)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current
    assert not recovery(a).get('next_entry', '')
    report = {'attempt': a['attempt'], 'trial_boot_id': bid, 'returned_boot_id': current,
              'returned_release': os.uname().release, 'baseline': baseline,
              'baseline_recomputed_exact': True, 'gpu': gpu, 'workload': workload_manifest,
              'original_workload_exact': True, 'gpu_verdict': verdict, 'load_runtime_pm': load_runs,
              'recovery_module_files_links_verified': 5183, 'build_files_verified': 498,
              'installed_module_files_verified': 208, 'preparation_files_verified': 514,
              'frozen_sources': frozen, 'fallback_uptime_seconds': fallback['uptime_seconds'],
              'trial_kernel_faults_through_shutdown': [],
              'trial_last_kernel_monotonic_seconds': max(int(e['__MONOTONIC_TIMESTAMP']) for e in entries) / 1e6,
              'persistent_default': env['saved_entry'], 'next_entry_empty': True, 'efi_bootnext_absent': True,
              'hardware_acceptance_closed': False, 'reviewer_sha256': sha(Path(__file__))}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
    os.sync()
    out.rename(X / 'return-result')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
