#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive only an actual AT failure followed by verified known-good recovery."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from at_boot_guard import BASE, X, artifacts, command, files, load, recovery, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-boot-id', required=True)
    args = parser.parse_args()
    bid = str(uuid.UUID(args.recovery_boot_id))
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert os.uname().release == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    os.umask(0o077)
    a = load()
    env = recovery(a)
    assert not env.get('next_entry', '')
    artifacts(a)
    for name in ('final-result', 'camera-provider-result', 'handoff-review',
                 'startup-discovery', 'post-result-records', 'camera-control-result', 'camera-control-final-result',
                 'camera-led-observer-v2-initial', 'camera-led-observer-v2-final'):
        root = X / name
        expected = json.loads((root / 'sha256.json').read_text())
        assert files(root) == expected | {'sha256.json': sha(root / 'sha256.json')}
    result = json.loads((X / 'final-result/result.json').read_text())
    review = json.loads((X / 'independent-result-review.json').read_text())
    trial = result['boot_id']
    assert trial == '1cf4d1ac-a076-4f3f-b89a-b0690e487528' != bid
    assert review['boot_id'] == trial and review['scoped_passed'] and not review['trial_passed']
    assert result['spi_hid_ready'] and result['passed_scoped_baseline'] and not result['passed_trial']
    assert review['scoped_failure_reasons'] == []
    assert not review['camera_control_initial_passed'] and not review['camera_control_final_passed']
    assert result['native_force_off_path_passed'] and result['fd680_renderer'] and result['wifi_connected']
    assert not json.loads((X / 'finalizer-action.json').read_text())['fallback_stopped']
    gate = json.loads((X / 'fallback-recovery-check.json').read_text())
    assert gate['boot_id'] == trial and gate['uptime_seconds'] >= 900
    assert all(gate[k] for k in ('known_good_payloads_modules_entry_verified',
                                'next_entry_empty', 'efi_bootnext_absent'))
    root = BASE / 'boots' / trial
    assert (root / 'return-requested').read_text().strip() == trial
    assert 'next_entry=' in (root / 'pre-return-grubenv').read_text().splitlines()
    fallback = command('journalctl', '--boot=' + trial.replace('-', ''), '-u',
                       'spx-at-fallback.service', '-o', 'short-monotonic', '--no-pager')
    assert 'Evidence saved' in fallback and 'Deactivated successfully' in fallback
    out = X / 'recovery-return'
    assert not out.exists()
    subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'], check=True, timeout=90)
    out.mkdir(mode=0o700)
    for label, boot in (('trial', trial), ('recovery', bid)):
        collector = BASE / 'boots' / boot
        with (collector / 'collect.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            shutil.copytree(collector, out / (label + '-collector'), symlinks=True,
                            ignore=shutil.ignore_patterns('collect.lock'))
        for suffix, opts in (('kernel.log', ['-k', '-o', 'short-monotonic']),
                             ('journal.log', ['-o', 'short-monotonic']),
                             ('journal.export', ['-o', 'export'])):
            with (out / (label + '-' + suffix)).open('wb') as stream:
                subprocess.run(['journalctl', '--boot=' + boot.replace('-', ''),
                                *opts, '--no-pager'], stdout=stream, check=True, timeout=90)
    (out / 'fallback.log').write_text(fallback + '\n')
    (out / 'grubenv').write_text(command('grub-editenv', '/boot/grub/grubenv', 'list') + '\n')
    (out / 'efibootmgr').write_text(command('efibootmgr') + '\n')
    (out / 'cmdline').write_text(Path('/proc/cmdline').read_text())
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(X / 'fallback-recovery-check.json', out / 'fallback-recovery-check.json')
    report = {'attempt': a['attempt'], 'trial_boot_id': trial, 'recovery_boot_id': bid,
              'recovery_release': os.uname().release, 'userspace_fallback_return_verified': True,
              'efi_early_kernel_recovery_validated': False, 'known_good_default': True,
              'next_entry_empty': True, 'efi_bootnext_absent': True,
              'result_manifest_sha256': sha(X / 'final-result/sha256.json'),
              'provider_manifest_sha256': sha(X / 'camera-provider-result/sha256.json'),
              'post_result_manifest_sha256': sha(X / 'post-result-records/sha256.json'),
              'touch_ready_at_trial_snapshot': True, 'no_manual_restart_rebind_or_pcm': True}
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
