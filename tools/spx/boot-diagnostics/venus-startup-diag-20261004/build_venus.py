#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile/link actual diagnostic Venus constituents in a verified private tree."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('startup_verify', HERE / 'verify.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
g = v.g
BASE = Path('/var/tmp/spx-mainline-trial-20261004bc/source')
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'
BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    native_manifest = g.sha(args.native / 'sha256.json')
    assert g.files(args.native) == v.read(args.native / 'sha256.json') | {'sha256.json': native_manifest}
    native = v.read(args.native / 'report.json')
    assert sum(r['hfi_comparisons'] + r['firmware_comparisons'] for r in native['native_actual_body_results']) == 79296
    assert len(native['rejected_candidate_controls']) == 6
    changes = native['exact_three_source_changes']
    rows = v.read(g.X / 'dtb-build/candidate-source-files.json')
    bc_rows = v.read(g.X / 'build/source-files.json')
    assert set(rows) == set(bc_rows) and len(rows) == 96938
    assert {n for n in rows if rows[n] != bc_rows[n]} == {BOARD}
    root = args.output
    root.mkdir(mode=0o700)
    shutil.copy2(__file__, root / Path(__file__).name)
    shutil.copy2(HERE / 'verify.py', root / 'verify.py')
    shutil.copy2(g.RUNTIME / 'be_boot_guard.py', root / 'be_boot_guard.py')
    shutil.copy2(g.X / 'dtb-build/candidate-source-files.json', root / 'parent-source-files.json')
    commands = []

    def guard():
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
        assert os.uname().release == '6.18.3-1-surface+'
        assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
        assert not g.recovery(a).get('next_entry', '')
        checked = v.live(rows, changes)
        g.artifacts(a)
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
        return checked

    def run(label, argv, timeout=180):
        start = time.monotonic()
        with (root / (label + '.stdout')).open('xb') as stdout, (root / (label + '.stderr')).open('xb') as stderr:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout)
        commands.append(dict(label=label, argv=argv, exit_code=result.returncode, seconds=round(time.monotonic() - start, 3)))
        (root / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        print(json.dumps(commands[-1]), flush=True)
        assert result.returncode == 0, label

    def verify_source(source, expected):
        actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
        assert actual == set(expected)
        for name, row in expected.items():
            path = source / name
            if 'sha256' in row:
                assert not path.is_symlink() and g.sha(path) == row['sha256'], name
                assert stat.S_IMODE(path.stat().st_mode) == row['mode'], name
            else:
                assert path.is_symlink() and os.readlink(path) == row['symlink'], name
        return len(actual)

    guard()
    source, output = root / 'source', root / 'output'
    run('snapshot', ['cp', '-a', '--reflink=auto', str(BASE), str(source)])
    verify_source(source, bc_rows)
    # BC executable source precedes BE's sole external-DTB edit.
    assert g.sha(g.REPO / BOARD) == rows[BOARD]['sha256']
    shutil.copyfile(g.REPO / BOARD, source / BOARD)
    assert verify_source(source, rows) == 96938
    expected = {name: dict(row) for name, row in rows.items()}
    for name, delta in changes.items():
        assert g.sha(source / name) == delta['before_sha256']
        assert g.sha(g.REPO / name) == delta['after_sha256']
        shutil.copyfile(g.REPO / name, source / name)
        shutil.copy2(g.REPO / name, root / Path(name).name)
        expected[name]['sha256'] = delta['after_sha256']
        if 'bytes' in expected[name]:
            expected[name]['bytes'] = (source / name).stat().st_size
    assert verify_source(source, expected) == 96938
    (root / 'candidate-source-files.json').write_text(json.dumps(expected, indent=2) + '\n')
    output.mkdir(mode=0o700)
    config = g.X / 'build/config-extracted'
    shutil.copy2(config, output / '.config')
    shutil.copy2(config, root / 'config')
    make = ['make', '-C', str(source), 'O=' + str(output), 'ARCH=arm64', 'LOCALVERSION=+']
    run('olddefconfig', make + ['olddefconfig'])
    assert g.sha(output / '.config') == g.sha(config)
    run('prepare', make + ['-j6', 'modules_prepare'], 300)
    makefile = (source / v.VENUS / 'Makefile').read_text()
    match = re.search(r'venus-core-objs \+= (.*?)\n\n', makefile, re.S)
    assert match
    names = re.findall(r'\b[\w-]+\.o\b', match[1])
    assert len(names) == len(set(names)) == 14
    (root / 'Makefile.venus').write_text(makefile)
    objects = [output / v.VENUS / name for name in names]
    run('objects', make + ['-j6'] + [str(p.relative_to(output)) for p in objects], 300)
    for path in objects:
        shutil.copy2(path, root / path.name)
        shutil.copy2(path.parent / ('.' + path.name + '.cmd'), root / ('.' + path.name + '.cmd'))
    run('relocatable-link', ['ld', '-r', '-o', str(root / 'venus-core.o')] + [str(root / n) for n in names], 30)
    for label, options in [('headers', ['-h']), ('symbols', ['-sW']), ('sections', ['-SW'])]:
        run(label, ['readelf'] + options + [str(root / 'venus-core.o')], 15)
    run('strings', ['strings', str(root / 'venus-core.o')], 15)
    assert 'AArch64' in (root / 'headers.stdout').read_text()
    strings = (root / 'strings.stdout').read_text().splitlines()
    assert 'spx_hfi_startup_diag' in strings
    cmd = (root / '.hfi_venus.o.cmd').read_text().splitlines()[0]
    assert '-DMODULE' in cmd and '-DKBUILD_MODNAME=' in cmd and 'venus_core' in cmd
    assert 'parmtype=spx_hfi_startup_diag:bool' in strings
    for word in ('poll', 'buffers', 'remote-state', 'auth-reset'):
        assert any('SPX Venus startup ' + word in line for line in strings)
    symbols = [line.split() for line in (root / 'symbols.stdout').read_text().splitlines()
               if line.strip().endswith('venus_hfi_startup_diag')]
    assert len(symbols) == 1 and symbols[0][3] == 'FUNC' and symbols[0][6] != 'UND'
    assert verify_source(source, expected) == 96938
    assert g.sha(output / '.config') == g.sha(config)
    checked = guard()
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
        native_manifest_sha256=native_manifest, native_comparisons=79296,
        parent_and_final_private_records_verified=96938, live_source_paths_verified=checked,
        exact_three_source_changes=changes, parent_manifest_sha256=g.sha(g.X / 'dtb-build/candidate-source-files.json'),
        config_sha256=g.sha(config), private_and_live_config_unchanged=True,
        actual_kbuild_aarch64_constituent_objects=14, independent_relocatable_link_sha256=g.sha(root / 'venus-core.o'),
        parameter_prefix_verified='venus_core.spx_hfi_startup_diag', internal_diagnostic_gate_link_resolved=True,
        known_good_recovery_rehashed=True, pending_selection_empty=True,
        full_kernel_linked=False, deployed=False, boot_selected=False, hardware_operations=0,
        hardware_acceptance_closed=False)
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {p.name: g.sha(p) for p in sorted(root.iterdir()) if p.is_file() and not p.is_symlink()}
    (root / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    os.sync()
    print(json.dumps(report | {'manifest_sha256': g.sha(root / 'sha256.json')}), flush=True)


if __name__ == '__main__':
    main()
