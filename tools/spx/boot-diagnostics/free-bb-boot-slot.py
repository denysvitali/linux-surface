#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve/verify BB's unreferenced terminal duplicate slot, then free /boot."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

BB = g.BASE / 'attempts/20261004bb'
SLOT = Path('/boot/spx-trial-20261004bb')
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert os.uname().release == '6.18.3-1-surface+'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    b = read(BB / 'attempt.json')
    assert b['state'].startswith('BB terminal;') and b['terminal_return_boot_id'] == 'e00a2d25-03f7-4265-b56e-0eac05b234d3'
    assert b['terminal_return_review_sha256'] == g.sha(BB / 'return-review/sha256.json')
    assert b['build_manifest_sha256'] == g.sha(BB / 'build-sha256.json')
    assert b['archive_review_sha256'] == g.sha(BB / 'archive-review.json')
    manifest = read(BB / 'build-sha256.json')
    assert not SLOT.is_symlink()
    assert {p.name for p in SLOT.iterdir()} == {'vmlinuz', 'initramfs.img', 'spx.dtb'}
    recovery = read(g.X / 'working-recovery.json')
    assert all(not str(p).startswith(str(SLOT) + '/') for p in recovery['payload_sha256'])
    assert str(SLOT) not in json.dumps(recovery)
    configs = [Path('/boot/grub/grub.cfg'), Path('/boot/grub/custom.cfg')]
    configs += [p for p in sorted(Path('/etc/grub.d').iterdir()) if p.is_file() and os.access(p, os.X_OK)]
    for path in configs:
        assert SLOT.name not in path.read_text(), path
    efi = g.command('efibootmgr', '-v')
    assert 'BootNext:' not in efi and SLOT.name not in efi
    units = {}
    assert 'spx_attempt=20261004bb' not in Path('/proc/cmdline').read_text().split()
    for phase in ('camera-provider', 'video', 'camera-control', 'media', 'baseline', 'fallback'):
        for kind in ('timer', 'service'):
            unit = 'spx-bb-' + phase + '.' + kind
            path = Path('/etc/systemd/system') / unit
            assert 'ConditionKernelCommandLine=spx_attempt=20261004bb\n' in path.read_text()
            state = g.command('systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'SubState', '-p', 'ConditionResult')
            assert 'ActiveState=inactive\n' in state + '\n' and 'SubState=dead\n' in state + '\n'
            units[unit] = dict(sha256=g.sha(path), state=state)
    root = g.X / 'housekeeping-boot-bb-20261004'
    root.mkdir(mode=0o700)
    shutil.copy2(__file__, root / Path(__file__).name)
    files = {}
    for filename, archived in [('vmlinuz', 'vmlinuz'), ('initramfs.img', 'initramfs.img'), ('spx.dtb', 'dtb-build/spx.dtb')]:
        path = SLOT / filename
        assert path.is_file() and not path.is_symlink()
        digest = g.sha(path)
        assert digest == b['sha256'][str(path)] == manifest[archived] == g.sha(BB / 'build' / archived)
        target = root / 'restore' / filename
        target.parent.mkdir(mode=0o700, exist_ok=True)
        shutil.copy2(path, target)
        assert g.sha(target) == digest
        files[str(path)] = dict(sha256=digest, bytes=path.stat().st_size,
                               original_mode=path.stat().st_mode & 0o777,
                               durable_archive=str(BB / 'build' / archived), restore_copy=str(target))
    snapshots = root / 'before'
    snapshots.mkdir(mode=0o700)
    for i, path in enumerate(configs):
        shutil.copy2(path, snapshots / (str(i) + '-' + path.name))
    (snapshots / 'efi.txt').write_text(efi + '\n')
    (snapshots / 'grubenv.txt').write_text(g.command('grub-editenv', '/boot/grub/grubenv', 'list') + '\n')
    shutil.copy2(BB / 'attempt.json', snapshots / 'bb-attempt.json')
    shutil.copy2(g.X / 'working-recovery.json', snapshots / 'working-recovery.json')
    before_free = shutil.disk_usage('/boot').free
    prepared = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT, slot=str(SLOT),
        files=files, terminal_bb=True, active_reference_absent=True, bb_units_gated_inactive=units,
        boot_free_before=before_free, parent_terminal_return_review=b['terminal_return_review_sha256'])
    (root / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    (root / 'pre-removal-sha256.json').write_text(json.dumps(g.files(root), indent=2) + '\n')
    os.sync()
    # Final identity and empty-selection recheck immediately before deletion.
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    env = dict(line.split('=', 1) for line in g.command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert env.get('saved_entry') == 'spx-known-good' and not env.get('next_entry', '')
    assert 'BootNext:' not in g.command('efibootmgr')
    for path, row in files.items():
        assert g.sha(path) == row['sha256'] == g.sha(row['restore_copy'])
    for path in files:
        Path(path).unlink()
    SLOT.rmdir()
    os.sync()
    assert not SLOT.exists()
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    for i, path in enumerate(configs):
        assert path.read_bytes() == (snapshots / (str(i) + '-' + path.name)).read_bytes()
    assert g.command('efibootmgr', '-v') == efi
    after_free = shutil.disk_usage('/boot').free
    assert after_free - before_free >= sum(row['bytes'] for row in files.values())
    report = prepared | dict(utc_complete=datetime.now(timezone.utc).isoformat(), boot_free_after=after_free,
        freed_bytes=after_free - before_free, archived_restore_copies_verified=True,
        persistent_default='spx-known-good', next_entry_empty=True, recovery_and_active_be_artifacts_exact=True,
        compiled_source_changed=False, boot_selected=False, hardware_acceptance_closed=False)
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (root / 'sha256.json').write_text(json.dumps(g.files(root), indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(manifest_sha256=g.sha(root / 'sha256.json'), report=report)), flush=True)


if __name__ == '__main__':
    main()
