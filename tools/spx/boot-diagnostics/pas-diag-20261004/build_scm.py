#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the diagnostic SCM aggregate in a verified fresh private BA snapshot."""
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
import ba_boot_guard as g

SOURCE = Path('/var/tmp/spx-mainline-trial-20261004ba/source')
BOOT = 'a824008e-cf43-4287-84f8-4e930fa41a06'
RELS = ('drivers/firmware/qcom/qcom_scm.c',
        'drivers/firmware/qcom/qcom_scm-smc.c',
        'drivers/firmware/qcom/qcom_scm.h')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    root = parser.parse_args().output
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert a['state'] == 'BA terminal; guarded return verified'
    assert g.sha(g.X / 'return-review/sha256.json') == \
        'f1324030e2dc1361bae3565ce416e1d65fb1d875a02947131393347d1eefd3e0'
    assert not g.recovery(a).get('next_entry', '')
    os.umask(0o077)
    root.mkdir(mode=0o700)
    source, output = root / 'source', root / 'output'
    rows = json.loads((g.X / 'build/source-files.json').read_text())
    assert len(rows) == 96938
    steps = []
    live_config_sha = g.sha(g.REPO / '.config')

    def run(label, argv, timeout):
        start = time.monotonic()
        with (root / (label + '.stdout')).open('xb') as stdout, (root / (label + '.stderr')).open('xb') as stderr:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout)
        steps.append(dict(label=label, argv=argv, exit_code=result.returncode,
                          seconds=time.monotonic() - start))
        (root / 'commands.json').write_text(json.dumps(steps, indent=2) + '\n')
        print(json.dumps(steps[-1]), flush=True)
        assert result.returncode == 0, label

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
    changes, diff = {}, []
    for name in RELS:
        original, updated = source / name, g.REPO / name
        assert original.read_bytes() != updated.read_bytes()
        changes[name] = dict(before_sha256=g.sha(original), after_sha256=g.sha(updated))
        diff.extend(difflib.unified_diff(original.read_text().splitlines(keepends=True),
                    updated.read_text().splitlines(keepends=True), fromfile='a/' + name, tofile='b/' + name))
        shutil.copy2(updated, root / updated.name)
        shutil.copyfile(updated, original)
    (root / 'source.patch').write_text(''.join(diff))
    shutil.copy2(g.X / 'build/source-files.json', root / 'parent-source-files.json')
    output.mkdir(mode=0o700)
    config = g.X / 'build/config-extracted'
    shutil.copy2(config, output / '.config')
    shutil.copy2(config, root / 'config-before')
    make = ['make', '-C', str(source), 'O=' + str(output), 'ARCH=arm64', 'LOCALVERSION=+']
    run('olddefconfig', make + ['olddefconfig'], 120)
    assert g.sha(output / '.config') == g.sha(config)
    run('prepare', make + ['-j6', 'modules_prepare'], 180)
    run('aggregate', make + ['-j6', 'drivers/firmware/qcom/qcom-scm.o'], 240)
    obj = output / 'drivers/firmware/qcom/qcom-scm.o'
    shutil.copy2(obj, root / obj.name)
    run('object-header', ['readelf', '-h', str(root / obj.name)], 10)
    run('object-symbols', ['readelf', '-sW', str(root / obj.name)], 10)
    run('object-strings', ['strings', str(root / obj.name)], 10)
    strings = (root / 'object-strings.stdout').read_text().splitlines()
    assert 'qcom_scm.spx_pas_diag' in strings
    assert any('SPX PAS diag smc done' in line for line in strings)
    assert 'AArch64' in (root / 'object-header.stdout').read_text()
    assert 'qcom_scm_spx_pas_diag' in (root / 'object-symbols.stdout').read_text()
    for name in RELS:
        assert g.sha(SOURCE / name) == changes[name]['before_sha256']
        assert g.sha(source / name) == g.sha(g.REPO / name) == changes[name]['after_sha256']
    assert g.sha(output / '.config') == g.sha(config)
    assert g.sha(g.REPO / '.config') == live_config_sha
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    shutil.copy2(__file__, root / Path(__file__).name)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                  parent_records_verified=len(rows), exact_three_source_changes=changes,
                  parent_manifest_sha256=g.sha(g.X / 'build/source-files.json'),
                  config_sha256=g.sha(config), private_config_unchanged=True,
                  live_config_unchanged=True, aggregate_sha256=g.sha(obj),
                  aggregate_bytes=obj.stat().st_size, aarch64_aggregate_linked=True,
                  diagnostic_parameter_prefix_verified='qcom_scm.spx_pas_diag',
                  full_kernel_linked=False, deployed=False, boot_selected=False,
                  hardware_operations=0, hardware_acceptance_closed=False)
    (root / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {path.name: g.sha(path) for path in sorted(root.iterdir()) if path.is_file()}
    (root / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    os.sync()
    print(json.dumps(report | {'manifest_sha256': g.sha(root / 'sha256.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
