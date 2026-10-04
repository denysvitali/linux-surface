#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build Iris1 power changes in a fresh verified AX source snapshot."""
from datetime import datetime, timezone
import argparse
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
import ax_boot_guard as g

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/tmp/spx-mainline-trial-20261003au/source')
BOOT = 'b6b4f20b-376f-4577-b282-677ad4ae0ec8'
REL = ('drivers/clk/qcom/camcc-sc8180x.c',
       'drivers/media/platform/qcom/camss/camss.c',
       'drivers/media/platform/qcom/venus/hfi_venus.c',
       'drivers/media/platform/qcom/venus/hfi_venus_io.h',
       'drivers/media/platform/qcom/venus/pm_helpers.c',
       'drivers/media/platform/qcom/venus/pm_helpers.h',
       'drivers/media/platform/qcom/venus/core.c')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load(); env = g.recovery(a); assert not env.get('next_entry', '')
    g.artifacts(a)
    os.umask(0o077)
    root = args.output
    root.mkdir(mode=0o700)
    source, output = root / 'source', root / 'output'
    records = json.loads((g.X / 'build/source-files.json').read_text())
    assert len(records) == 96937
    steps = []

    def run(label, command, timeout):
        start = time.monotonic()
        with (root / (label + '.stdout')).open('w') as stdout, (root / (label + '.stderr')).open('w') as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout)
        steps.append(dict(label=label, argv=command, exit_code=result.returncode,
                          seconds=time.monotonic() - start))
        (root / 'commands.json').write_text(json.dumps(steps, indent=2) + '\n')
        print(json.dumps(steps[-1]), flush=True)
        assert result.returncode == 0, label

    run('snapshot', ['cp', '-a', '--reflink=auto', str(BASE), str(source)], 180)
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
    assert actual == set(records)
    for rel, row in records.items():
        path = source / rel
        if 'sha256' in row:
            assert not path.is_symlink() and g.sha(path) == row['sha256'], rel
            assert stat.S_IMODE(path.stat().st_mode) == row['mode'], rel
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], rel
    print(json.dumps({'base_records_verified': len(records)}), flush=True)
    changes, patch = {}, []
    for rel in REL:
        before, after = (source / rel).read_text(), (REPO / rel).read_text()
        assert before != after
        changes[rel] = dict(before_sha256=g.sha(source / rel), after_sha256=g.sha(REPO / rel))
        patch.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                         fromfile='a/' + rel, tofile='b/' + rel))
        shutil.copyfile(REPO / rel, source / rel)
        shutil.copyfile(REPO / rel, root / Path(rel).name)
    assert changes[REL[0]]['after_sha256'] == 'a33b9a4434912a41aadfc7d854f883cfe8762a24f79d10b5d92737a4cbf82098'
    assert changes[REL[1]]['after_sha256'] == '987e72dfb8dcef012433ae67855d93309a5438066117d93d45ec79856466e960'
    (root / 'source.patch').write_text(''.join(patch))
    output.mkdir(mode=0o700)
    config = g.X / 'build/config-extracted'
    shutil.copyfile(config, output / '.config')
    shutil.copyfile(config, root / 'config-before')
    run('config', [str(source / 'scripts/config'), '--file', str(output / '.config'),
                   '-e', 'V4L_MEM2MEM_DRIVERS', '-m', 'VIDEO_QCOM_VENUS'], 10)
    make = ['make', '-C', str(source), 'O=' + str(output), 'ARCH=arm64', 'LOCALVERSION=+']
    run('olddefconfig', make + ['olddefconfig'], 120)
    shutil.copyfile(output / '.config', root / 'config-after')
    config_delta = ''.join(difflib.unified_diff(config.read_text().splitlines(keepends=True),
                          (output / '.config').read_text().splitlines(keepends=True),
                          fromfile='AX-config', tofile='Venus-build-config'))
    (root / 'config.patch').write_text(config_delta)
    enabled = (output / '.config').read_text()
    for line in ('CONFIG_V4L_MEM2MEM_DRIVERS=y', 'CONFIG_VIDEO_QCOM_VENUS=m',
                 'CONFIG_V4L2_MEM2MEM_DEV=m', '# CONFIG_VIDEO_QCOM_IRIS is not set'):
        assert line in enabled, line
    run('prepare', make + ['-j6', 'modules_prepare'], 180)
    names = ('venus-core.o', 'venus-dec.o', 'venus-enc.o')
    rels = ['drivers/media/platform/qcom/venus/' + name for name in names]
    run('objects', make + ['-j6'] + rels, 240)
    objects = {}
    for rel in rels:
        path = output / rel
        objects[rel] = dict(sha256=g.sha(path), bytes=path.stat().st_size)
        shutil.copyfile(path, root / path.name)
    run('object-headers', ['readelf', '-h'] + [str(root / name) for name in names], 10)
    run('compiler', ['gcc', '--version'], 10)
    for rel in REL:
        assert g.sha(BASE / rel) == changes[rel]['before_sha256']
        assert g.sha(source / rel) == changes[rel]['after_sha256'] == g.sha(REPO / rel)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    shutil.copyfile(g.X / 'build/source-files.json', root / 'base-source-files.json')
    shutil.copyfile(Path(__file__), root / 'build_venus.py')
    result = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                  source_base=str(BASE), source_records_verified=len(records),
                  source_manifest_sha256=g.sha(g.X / 'build/source-files.json'),
                  source_archive_sha256=g.sha(g.X / 'build/source.tar.zst'),
                  exact_seven_source_changes=changes, config_before_sha256=g.sha(config),
                  config_after_sha256=g.sha(output / '.config'), commands=steps, objects=objects,
                  aggregates_linked=True, loadable_modules_linked=False,
                  full_kernel_linked=False, deployed=False, hardware_operations=0)
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    manifest = ''.join(f'{g.sha(p)}  {p.name}\n' for p in sorted(root.iterdir()) if p.is_file())
    (root / 'SHA256SUMS').write_text(manifest)
    print(json.dumps({'files': len(manifest.splitlines()), 'manifest_sha256': g.sha(root / 'SHA256SUMS'),
                      'objects': objects}), flush=True)


if __name__ == '__main__':
    main()
