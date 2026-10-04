#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify the BB parent and build/link only the area-query SCM constituents."""
import argparse
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bb_boot_guard as g

SOURCE = Path('/var/tmp/spx-mainline-trial-20261004bb/source')
BOOT = 'e00a2d25-03f7-4265-b56e-0eac05b234d3'
RELS = ('drivers/firmware/qcom/qcom_scm.c', 'drivers/firmware/qcom/qcom_scm.h')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    root = parser.parse_args().output
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    a = g.load()
    assert a['state'] == 'BB terminal; scoped baseline and guarded return verified; PAS memory setup raw SCM error unresolved'
    assert g.sha(g.X / 'return-review/sha256.json') == \
        'a3e8476226a06d9ea452fe958b9fb73b61d03171c82287e77bc7df8d56a9cdaa'
    rows = json.loads((g.X / 'build/source-files.json').read_text())
    assert len(rows) == 96938
    live_config = g.sha(g.REPO / '.config')
    changes, steps = {}, []
    os.umask(0o077)
    root.mkdir(mode=0o700)
    shutil.copy2(__file__, root / Path(__file__).name)
    shutil.copy2(g.RUNTIME / 'bb_boot_guard.py', root / 'bb_boot_guard.py')

    def live_guard():
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
        assert os.uname().release == '6.18.3-1-surface+'
        assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
        assert not g.recovery(a).get('next_entry', '')
        checked = 0
        for name, row in rows.items():
            top = Path(name).parts[0]
            if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or
                    (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                    name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
                continue
            path = g.REPO / name
            if name in RELS:
                if changes:
                    assert g.sha(path) == changes[name]['after_sha256'], name
                else:
                    assert g.sha(path) != row['sha256'], name
            elif 'sha256' in row:
                assert g.sha(path) == row['sha256'], name
            else:
                assert path.is_symlink() and os.readlink(path) == row['symlink'], name
            checked += 1
        assert checked == 84669
        assert g.sha(g.REPO / '.config') == live_config == g.sha(g.X / 'build/live-config-before')
        g.artifacts(a)
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
        return checked

    def run(label, argv, timeout):
        start = time.monotonic()
        with (root / (label + '.stdout')).open('xb') as stdout, (root / (label + '.stderr')).open('xb') as stderr:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout)
        steps.append(dict(label=label, argv=argv, exit_code=result.returncode,
                          seconds=time.monotonic() - start))
        (root / 'commands.json').write_text(json.dumps(steps, indent=2) + '\n')
        print(json.dumps(steps[-1]), flush=True)
        assert result.returncode == 0, label

    live_guard()
    source, output = root / 'source', root / 'output'
    run('snapshot', ['cp', '-a', '--reflink=auto', str(SOURCE), str(source)], 180)
    actual = {str(path.relative_to(source)) for path in source.rglob('*') if path.is_file() or path.is_symlink()}
    assert actual == set(rows)
    for name, row in rows.items():
        path = source / name
        if 'sha256' in row:
            assert not path.is_symlink() and g.sha(path) == row['sha256'], name
            assert stat.S_IMODE(path.stat().st_mode) == row['mode'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
    print(json.dumps(dict(parent_records_verified=len(rows))), flush=True)
    diff = []
    for name in RELS:
        original, updated = source / name, g.REPO / name
        assert original.read_bytes() != updated.read_bytes()
        changes[name] = dict(before_sha256=g.sha(original), after_sha256=g.sha(updated))
        diff.extend(difflib.unified_diff(original.read_text().splitlines(keepends=True),
                    updated.read_text().splitlines(keepends=True), fromfile='a/' + name, tofile='b/' + name))
        shutil.copy2(updated, root / updated.name)
        shutil.copyfile(updated, original)
    (root / 'source.patch').write_text(''.join(diff))
    shutil.copy2(source / 'drivers/firmware/qcom/qcom_scm-smc.c', root / 'qcom_scm-smc.c')
    shutil.copy2(source / 'drivers/firmware/qcom/Makefile', root / 'Makefile.qcom')
    shutil.copy2(g.X / 'build/source-files.json', root / 'parent-source-files.json')
    output.mkdir(mode=0o700)
    config = g.X / 'build/config-extracted'
    shutil.copy2(config, output / '.config')
    shutil.copy2(config, root / 'config')
    make = ['make', '-C', str(source), 'O=' + str(output), 'ARCH=arm64', 'LOCALVERSION=+']
    run('olddefconfig', make + ['olddefconfig'], 120)
    assert g.sha(output / '.config') == g.sha(config)
    run('prepare', make + ['-j6', 'modules_prepare'], 300)
    names = ('qcom_scm.o', 'qcom_scm-smc.o', 'qcom_scm-legacy.o')
    objects = [output / 'drivers/firmware/qcom' / name for name in names]
    run('objects', make + ['-j6'] + [str(path.relative_to(output)) for path in objects], 240)
    for path in objects:
        shutil.copy2(path, root / path.name)
    run('relocatable-link', ['ld', '-r', '-o', str(root / 'qcom-scm.o')] +
        [str(root / name) for name in names], 30)
    run('headers', ['readelf', '-h', str(root / 'qcom-scm.o')], 10)
    run('symbols', ['readelf', '-sW', str(root / 'qcom-scm.o')], 10)
    run('sections', ['readelf', '-SW', str(root / 'qcom-scm.o')], 10)
    run('strings', ['strings', str(root / 'qcom-scm.o')], 10)
    assert 'AArch64' in (root / 'headers.stdout').read_text()
    strings = (root / 'strings.stdout').read_text().splitlines()
    for parameter in ('qcom_scm.spx_pas_diag', 'qcom_scm.spx_pas_area_diag'):
        assert parameter in strings, parameter
    assert any('SPX PAS area query transport' in line for line in strings)
    assert any('SPX PAS diag smc done' in line for line in strings)
    symbols = [line.split() for line in (root / 'symbols.stdout').read_text().splitlines()
               if line.strip().endswith('qcom_scm_spx_pas_diag')]
    assert len(symbols) == 1 and symbols[0][3] == 'FUNC' and symbols[0][6] != 'UND'
    for name, row in rows.items():
        path = source / name
        if name in RELS:
            assert g.sha(path) == g.sha(g.REPO / name) == changes[name]['after_sha256']
        elif 'sha256' in row:
            assert g.sha(path) == row['sha256'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
    assert g.sha(output / '.config') == g.sha(config)
    checked = live_guard()
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                  parent_and_final_private_records_verified=len(rows), live_source_paths_verified=checked,
                  exact_two_source_changes=changes, scm_smc_source_exact_bb=True,
                  parent_manifest_sha256=g.sha(g.X / 'build/source-files.json'),
                  config_sha256=g.sha(config), private_and_live_config_unchanged=True,
                  actual_kbuild_aarch64_constituent_objects=3,
                  independent_relocatable_link_sha256=g.sha(root / 'qcom-scm.o'),
                  parameter_prefixes_verified=['qcom_scm.spx_pas_diag', 'qcom_scm.spx_pas_area_diag'],
                  internal_diagnostic_gate_link_resolved=True,
                  known_good_recovery_rehashed=True, persistent_known_good_default=True,
                  pending_selection_empty=True, full_kernel_linked=False, deployed=False,
                  boot_selected=False, hardware_operations=0, hardware_acceptance_closed=False)
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {path.name: g.sha(path) for path in sorted(root.iterdir()) if path.is_file()}
    (root / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    os.sync()
    print(json.dumps(report | {'manifest_sha256': g.sha(root / 'sha256.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
