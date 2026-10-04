#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build actual builtin SCM constituents and independently check their relocatable link."""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ba_boot_guard as g

PREPARED = Path('/var/tmp/spx-pas-diag-20261004/object-build')
RELS = ('drivers/firmware/qcom/qcom_scm.c', 'drivers/firmware/qcom/qcom_scm-smc.c',
        'drivers/firmware/qcom/qcom_scm.h')
BOOT = 'a824008e-cf43-4287-84f8-4e930fa41a06'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    root = p.parse_args().output
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert a['state'] == 'BA terminal; guarded return verified'
    assert not g.recovery(a).get('next_entry', '')
    os.umask(0o077)
    root.mkdir(mode=0o700)
    shutil.copy2(__file__, root / Path(__file__).name)
    rows = json.loads((g.X / 'build/source-files.json').read_text())
    original_failure = json.loads((PREPARED / 'failed-target-sha256.json').read_text())
    assert {path.name: g.sha(path) for path in PREPARED.iterdir() if path.is_file()} == \
        original_failure | {'failed-target-sha256.json': g.sha(PREPARED / 'failed-target-sha256.json')}
    source, output = PREPARED / 'source', PREPARED / 'output'
    paths = {str(path.relative_to(source)) for path in source.rglob('*') if path.is_file() or path.is_symlink()}
    assert paths == set(rows) and len(rows) == 96938
    changes = {}
    for name, row in rows.items():
        path = source / name
        if name in RELS:
            assert g.sha(path) == g.sha(g.REPO / name) == original_failure[Path(name).name]
            changes[name] = dict(before_sha256=row['sha256'], after_sha256=g.sha(path))
        elif 'sha256' in row:
            assert not path.is_symlink() and g.sha(path) == row['sha256'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
    print(json.dumps(dict(final_private_source_records_verified=len(rows), exact_changes=3)), flush=True)
    config = g.X / 'build/config-extracted'
    assert g.sha(output / '.config') == g.sha(config)
    live_config = g.sha(g.REPO / '.config')
    makefile = source / 'drivers/firmware/qcom/Makefile'
    assert g.sha(makefile) == rows['drivers/firmware/qcom/Makefile']['sha256']
    assert 'qcom-scm-objs += qcom_scm.o qcom_scm-smc.o qcom_scm-legacy.o' in makefile.read_text()
    shutil.copy2(makefile, root / 'Makefile.qcom')
    shutil.copy2(config, root / 'config')
    for name in RELS:
        shutil.copy2(source / name, root / Path(name).name)
    shutil.copy2(PREPARED / 'source.patch', root / 'source.patch')
    steps = []

    def run(label, argv, timeout):
        start = time.monotonic()
        with (root / (label + '.stdout')).open('xb') as stdout, (root / (label + '.stderr')).open('xb') as stderr:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout)
        steps.append(dict(label=label, argv=argv, exit_code=result.returncode,
                          seconds=time.monotonic() - start))
        (root / 'commands.json').write_text(json.dumps(steps, indent=2) + '\n')
        print(json.dumps(steps[-1]), flush=True)
        assert result.returncode == 0, label

    names = ('qcom_scm.o', 'qcom_scm-smc.o', 'qcom_scm-legacy.o')
    objects = [output / 'drivers/firmware/qcom' / name for name in names]
    targets = [str(path.relative_to(output)) for path in objects]
    run('objects', ['make', '-C', str(source), 'O=' + str(output), 'ARCH=arm64',
                    'LOCALVERSION=+', '-j6'] + targets, 240)
    for path in objects:
        shutil.copy2(path, root / path.name)
    run('relocatable-link', ['ld', '-r', '-o', str(root / 'qcom-scm.o')] +
        [str(root / name) for name in names], 30)
    run('headers', ['readelf', '-h', str(root / 'qcom-scm.o')], 10)
    run('symbols', ['readelf', '-sW', str(root / 'qcom-scm.o')], 10)
    run('strings', ['strings', str(root / 'qcom-scm.o')], 10)
    assert 'AArch64' in (root / 'headers.stdout').read_text()
    strings = (root / 'strings.stdout').read_text().splitlines()
    assert 'qcom_scm.spx_pas_diag' in strings
    assert any('SPX PAS diag smc done' in line for line in strings)
    symbols = [line.split() for line in (root / 'symbols.stdout').read_text().splitlines()
               if line.strip().endswith('qcom_scm_spx_pas_diag')]
    assert len(symbols) == 1 and symbols[0][3] == 'FUNC' and symbols[0][6] != 'UND'
    assert g.sha(output / '.config') == g.sha(config) and g.sha(g.REPO / '.config') == live_config
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                  private_source_records_verified=len(rows), exact_three_source_changes=changes,
                  parent_manifest_sha256=g.sha(g.X / 'build/source-files.json'),
                  config_sha256=g.sha(config), private_and_live_config_unchanged=True,
                  actual_kbuild_aarch64_constituent_objects=3,
                  independent_relocatable_link_sha256=g.sha(root / 'qcom-scm.o'),
                  parameter_prefix_verified='qcom_scm.spx_pas_diag',
                  internal_diagnostic_gate_link_resolved=True,
                  original_target_failure_manifest_sha256=g.sha(PREPARED / 'failed-target-sha256.json'),
                  full_kernel_linked=False, deployed=False, boot_selected=False,
                  hardware_operations=0, hardware_acceptance_closed=False)
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {path.name: g.sha(path) for path in sorted(root.iterdir()) if path.is_file()}
    (root / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    os.sync()
    print(json.dumps(report | {'manifest_sha256': g.sha(root / 'sha256.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
