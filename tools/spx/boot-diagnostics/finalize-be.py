#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify BE's actual terminal return and preserve recovered known-good evidence."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def sealed(path):
    expected = read(path / 'sha256.json')
    assert g.files(path) == expected | {'sha256.json': g.sha(path / 'sha256.json')}


def replace(path, value):
    temporary = path.with_name(path.name + '.be-terminal-new')
    write(temporary, value)
    os.replace(temporary, path)


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'] == 'BE selected once; startup trial pending'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert os.uname().release == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '4096'
    review = read(g.X / 'return-review/report.json')
    assert review['returned_boot_id'] == BOOT
    assert review['boot_id'] == '11e69e59-c493-498a-9dde-d056f13ccc18'
    assert review['baseline_replay_exact'] and review['scoped_baseline_passed']
    assert review['known_good_recovery_verified']
    assert review['firmware_reservation'] == dict(base='0x8d300000', inclusive_end='0x8d7fffff', bytes=5242880)
    assert review['pas_init_returns'] == review['pas_memory_returns'] == [0]
    assert review['probe_errnos'] == [-110] and review['measured_aperture_nomap_retained']
    assert not review['normal_venus_driver_bound'] and not review['decoder_encoder_nodes_observed']
    for name in ('return-review', 'startup-review', 'final-result', 'actual-handoff-records', 'actual-media-boundary', 'offline-core-reset-v2', 'offline-core-reset-crosscheck', 'post-startup-records'):
        sealed(g.X / name)
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    checked = g.source()
    assert checked == 84669
    out = g.X / 'actual-known-good-return'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(g.X / 'attempt.json', out / 'attempt-before-terminal.json')
    for label, argv in {
        'kernel': ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'],
        'journal': ['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'],
        'grubenv': ['grub-editenv', '/boot/grub/grubenv', 'list'],
        'efibootmgr': ['efibootmgr'],
        'network': ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status'],
    }.items():
        result = subprocess.run(argv, capture_output=True, timeout=90, check=True)
        (out / (label + '.stdout')).write_bytes(result.stdout)
        (out / (label + '.stderr')).write_bytes(result.stderr)
    for name, path in {'boot-id': '/proc/sys/kernel/random/boot_id', 'cmdline': '/proc/cmdline',
                       'taint': '/proc/sys/kernel/tainted', 'uptime': '/proc/uptime'}.items():
        (out / name).write_bytes(Path(path).read_bytes())
    touch = {name: (Path('/sys/bus/spi/devices/spi0.0') / name).read_text().strip()
             for name in ('ready', 'bus_error_count', 'logic_error_count',
                          'regulator_error_count', 'device_initiated_reset_count')}
    write(out / 'touch-state.json', touch)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
        release=os.uname().release, taint='4096', compiled_source_paths_verified=checked,
        live_config_exact_candidate_prebuild=True, candidate_recovery_runtime_rehashed=True,
        baseline_replay_exact=True, guarded_return_seconds=read(g.X / 'fallback-recovery-check.json')['uptime_seconds'],
        last_trial_kernel_uptime_seconds=review['last_kernel_uptime_seconds'],
        return_review_manifest_sha256=g.sha(g.X / 'return-review/sha256.json'),
        known_good_touch_state=touch, known_good_touch_accepted_as_mainline=False,
        persistent_default='spx-known-good', next_entry_empty=True, efi_bootnext_absent=True,
        early_hang_recovery_validated=False, hardware_acceptance_closed=False)
    write(out / 'report.json', report)
    write(out / 'sha256.json', g.files(out))
    sealed(out)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    a.update(state='BE terminal; scoped baseline and guarded return verified; PAS9 memory setup succeeded, Venus core startup timed out',
        actual_boot_id=review['boot_id'], returned_boot_id=BOOT,
        terminal_utc=report['utc'], terminal_source_paths_verified=checked,
        actual_return_manifest_sha256=report['return_review_manifest_sha256'],
        actual_known_good_return_manifest_sha256=g.sha(out / 'sha256.json'),
        hardware_acceptance_closed=False)
    replace(g.X / 'attempt.json', a)
    replace(g.BASE / 'attempt.json', a)
    assert g.load() == a
    os.sync()
    print(json.dumps(report | dict(state=a['state'], manifest_sha256=g.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
