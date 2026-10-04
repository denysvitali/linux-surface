#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze offline stream cleanup evidence; no live device/boot mutations."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[4]
WORK = Path('/var/tmp/spx-rear-stream-failure-20261003')
OUT = Path('/var/lib/spx-boot-diagnostics/attempts/20261003at/offline-rear-stream-failure-20261003')
BUILD = WORK / 'native-build/build-complete'
SOURCE = WORK / 'native-build/source'
BOOT = '74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(mode=0o700)
    driver = REPO / 'drivers/media/i2c/ov13858.c'
    assert sha(driver) == '358a0d5c6c380cddc69542dcb99c1c74e4c15f90fd09aeff06c27e6639057de5'
    assert sha(driver) == sha(SOURCE / 'drivers/media/i2c/ov13858.c')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'saved_entry=spx-known-good\n' in env and 'next_entry=\n' in env
    assert not list(Path('/sys/firmware/efi/efivars').glob('BootNext-*'))
    result = json.loads((WORK / 'fixed-test-final-v5/result.json').read_text())
    assert result['source_sha256'] == sha(driver)
    assert result['compile_returncode'] == result['returncode'] == 0
    assert 'PASS 171 cases' in result['stdout'] and 'PASS 67 stream cases' in result['stdout']
    baseline = json.loads((WORK / 'baseline-test-v2/result.json').read_text())
    assert baseline['source_sha256'] == sha(WORK / 'ov13858-before.c')
    assert baseline['compile_returncode'] == 0 and baseline['returncode'] == -6
    assert 'reset_gpio->value==1' in baseline['stderr']
    assert json.loads((WORK / 'native-build-result-v4.json').read_text())['returncode'] == 0
    log = (WORK / 'native-build-v4.log').read_text()
    assert not any(s in log for s in ('ERROR:', 'WARNING:', 'warning:'))
    review = json.loads((WORK / 'native-module-review.json').read_text())
    assert len(review['modules']) == 16
    assert review['retained_kernel_exports_sha256'] == sha(BUILD / 'vmlinux.o')
    assert sha(BUILD / 'vmlinux.o') == sha(Path('/var/tmp/spx-camera-power-20261003/native-build/build/vmlinux.o'))
    for p in WORK.iterdir():
        if p.is_file():
            shutil.copyfile(p, OUT / p.name)
        elif p.is_dir() and p.name != 'native-build':
            shutil.copytree(p, OUT / p.name)
    artifacts = OUT / 'native-artifacts'
    artifacts.mkdir()
    for name in ('.config', 'Module.symvers', 'include/generated/autoconf.h',
                 'include/config/kernel.release', 'include/generated/utsrelease.h'):
        target = artifacts / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUILD / name, target)
    for name, record in review['modules'].items():
        module = BUILD / name
        assert sha(module) == record['sha256'] and sha(module.with_suffix('.o')) == record['object_sha256']
        target = artifacts / name
        target.parent.mkdir(parents=True, exist_ok=True)
        for source, destination in ((module, target), (module.with_suffix('.o'), target.with_suffix('.o'))):
            shutil.copyfile(source, destination)
        for suffix in ('.mod.c', '.mod', '.mod.o'):
            source = module.with_suffix(suffix)
            if source.exists():
                shutil.copyfile(source, target.with_suffix(suffix))
        cmd = module.parent / ('.' + module.with_suffix('.o').name + '.cmd')
        if cmd.exists():
            shutil.copyfile(cmd, target.parent / cmd.name)
    source_manifest = {}
    for path in sorted(SOURCE.rglob('*')):
        name = str(path.relative_to(SOURCE))
        if path.is_symlink():
            source_manifest[name] = dict(symlink=os.readlink(path))
        elif path.is_file():
            source_manifest[name] = dict(sha256=sha(path))
    (OUT / 'native-source-manifest.json').write_text(json.dumps(source_manifest, indent=2)+'\n')
    for name, path in {
        'ov13858-final.c': driver,
        'archive_stream_failure.py': Path(__file__).resolve(),
        'STREAM-FAILURE-final.md': Path(__file__).with_name('STREAM-FAILURE.md'),
        'LOCAL-PROGRESS.md': REPO / 'LOCAL-PROGRESS.md',
        'PORT-CHECKLIST.md': REPO / 'PORT-CHECKLIST.md',
        'AGENTS.md': REPO / 'AGENTS.md',
        'RESULT-20261003at.md': REPO / 'tools/spx/boot-diagnostics/RESULT-20261003at.md',
        'check_rear_lifecycle-final-current.py': Path(__file__).with_name('check_rear_lifecycle.py'),
        'check_rear_stream_failure-final-current.py': Path(__file__).with_name('check_rear_stream_failure.py'),
    }.items():
        shutil.copyfile(path, OUT / name)
    checklist = (REPO / 'PORT-CHECKLIST.md').read_text()
    acceptance = [(v,k) for v,k in re.findall(r'^- \[([ x])\] \*\*([A-Z]\d\d)', checklist, re.M) if not k.startswith('M')]
    assert len(acceptance) == 47 and all(v == ' ' for v,k in acceptance)
    (OUT / 'final-review.json').write_text(json.dumps(dict(
        boot_id=BOOT, cmdline=Path('/proc/cmdline').read_text().strip(), grubenv=env,
        no_BootNext=True, original_defect_reproduced=True, lifecycle_cases=171,
        stream_cases=67, strict_native_modules=16, final_driver_sha256=sha(driver),
        source_manifest_entries=len(source_manifest), hardware_operations=[],
        modified_modules_installed=False, new_candidate_selected=False,
        hardware_acceptance_open=47, full_port_complete=False,
        compile_limit='Retained September kernel exports; not a full current boot candidate',
    ), indent=2)+'\n')
    files = sorted(p for p in OUT.rglob('*') if p.is_file())
    (OUT / 'archive-sha256.txt').write_text(''.join(f'{sha(p)}  {p.relative_to(OUT)}\n' for p in files))
    for line in (OUT / 'archive-sha256.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert sha(OUT / name) == digest
    print(json.dumps(dict(output=str(OUT), files=len(files), manifest_sha256=sha(OUT / 'archive-sha256.txt'))))


if __name__ == '__main__':
    main()
