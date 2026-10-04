#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive offline privacy ordering evidence after reviewing terminal results."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[4]
WORK = Path('/var/tmp/spx-privacy-ordering-20261003')
OUT = Path('/var/lib/spx-boot-diagnostics/attempts/20261003at/offline-privacy-ordering-20261003')
SOURCE = WORK / 'native-build/source'
BUILD = WORK / 'native-build/build-complete'
BOOT = '74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    cmdline = Path('/proc/cmdline').read_text().strip()
    assert 'spx_boot=known-good' in cmdline.split()
    env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'saved_entry=spx-known-good\n' in env and 'next_entry=\n' in env
    assert not list(Path('/sys/firmware/efi/efivars').glob('BootNext-*'))
    media = REPO / 'drivers/media/v4l2-core/v4l2-subdev.c'
    assert sha(media) == 'ba004f8b066b41a589644f35c738ebd5279323ed0953d0a4b0c2a249cded84b6'
    assert sha(SOURCE / media.relative_to(REPO)) == sha(media)
    for name, text in [('fixed-final', 'PASS 129 privacy cases'),
                       ('leds-unreachable', 'PASS 72 privacy cases'),
                       ('rear-regression-final', 'PASS 67 stream cases')]:
        result = json.loads((WORK / name / 'result.json').read_text())
        assert result['compile_returncode'] == result['returncode'] == 0
        assert text in result['stdout']
        if name == 'rear-regression-final':
            assert 'PASS 171 cases' in result['stdout']
            assert result['source_sha256'] == sha(REPO / 'drivers/media/i2c/ov13858.c')
        else:
            assert result['source_sha256'] == sha(media)
    for name in ['baseline-legacy-v2', 'baseline-native-v2']:
        result = json.loads((WORK / name / 'result.json').read_text())
        assert result['compile_returncode'] == 0 and result['returncode'] == -6
        assert result['source_sha256'] == sha(WORK / 'v4l2-subdev-before.c')
        assert 'gpiod->value==1' in result['stderr']
    assert json.loads((WORK / 'native-build-result.json').read_text())['returncode'] == 0
    log = (WORK / 'native-build.log').read_text()
    assert not any(x in log for x in ['ERROR:', 'WARNING:', 'warning:'])
    assert 'MODPOST' in log and 'v4l2-subdev.o' in log
    assert 'total: 0 errors, 1 warnings' in (WORK / 'checkpatch.log').read_text()
    checklist = (REPO / 'PORT-CHECKLIST.md').read_text()
    acceptance = [(v, k) for v, k in re.findall(r'^- \[([ x])\] \*\*([A-Z]\d\d)', checklist, re.M)
                  if not k.startswith('M')]
    assert len(acceptance) == 47 and all(v == ' ' for v, k in acceptance)
    # Verify the complete source snapshot again after make; preserve each entry.
    manifest = json.loads((WORK / 'parent-native-source-manifest.json').read_text())
    name = str(media.relative_to(REPO))
    manifest[name] = dict(sha256=sha(media))
    for name, record in manifest.items():
        path = SOURCE / name
        assert (path.is_symlink() and os.readlink(path) == record['symlink']) \
            if 'symlink' in record else sha(path) == record['sha256'], name
    assert {str(p.relative_to(SOURCE)) for p in SOURCE.rglob('*')
            if p.is_file() or p.is_symlink()} == set(manifest)
    parent_build = Path('/var/tmp/spx-rear-stream-failure-20261003/native-build/build-complete')
    assert sha(BUILD / 'vmlinux.o') == sha(parent_build / 'vmlinux.o')
    OUT.mkdir(mode=0o700)
    for path in WORK.iterdir():
        if path.name == 'native-build':
            continue
        if path.is_file():
            shutil.copyfile(path, OUT / path.name)
        elif path.is_dir():
            shutil.copytree(path, OUT / path.name)
    artifacts = OUT / 'native-artifacts'
    artifacts.mkdir()

    def copy_artifact(name):
        target = artifacts / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUILD / name, target)

    for name in ['.config', 'Module.symvers', 'include/generated/autoconf.h',
                 'include/config/kernel.release', 'include/generated/utsrelease.h',
                 'drivers/media/v4l2-core/v4l2-subdev.o',
                 'drivers/media/v4l2-core/.v4l2-subdev.o.cmd']:
        copy_artifact(name)
    modules = {}
    for path in sorted(BUILD.rglob('*.ko')):
        name = str(path.relative_to(BUILD))
        modules[name] = dict(sha256=sha(path), object_sha256=sha(path.with_suffix('.o')),
                             modinfo=subprocess.check_output(['modinfo', str(path)], text=True))
        copy_artifact(name)
        for suffix in ['.o', '.mod.c', '.mod', '.mod.o']:
            other = path.with_suffix(suffix)
            if other.exists():
                copy_artifact(str(other.relative_to(BUILD)))
        other = path.parent / ('.' + path.with_suffix('.o').name + '.cmd')
        if other.exists():
            copy_artifact(str(other.relative_to(BUILD)))
    assert len(modules) == 16
    (OUT / 'native-module-review.json').write_text(json.dumps(dict(
        modules=modules, retained_kernel_exports_sha256=sha(BUILD / 'vmlinux.o'),
        release=(BUILD / 'include/config/kernel.release').read_text().strip(),
        full_current_kernel_build=False), indent=2)+'\n')
    (OUT / 'native-source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    for name, path in {
        'v4l2-subdev-final.c': media,
        'ov13858-final.c': REPO / 'drivers/media/i2c/ov13858.c',
        'check_stream_ordering-final.py': Path(__file__).with_name('check_stream_ordering.py'),
        'archive_stream_ordering.py': Path(__file__).resolve(),
        'STREAM-ORDERING.md': Path(__file__).with_name('STREAM-ORDERING.md'),
        'README-privacy.md': Path(__file__).with_name('README.md'),
        'LOCAL-PROGRESS.md': REPO / 'LOCAL-PROGRESS.md',
        'PORT-CHECKLIST.md': REPO / 'PORT-CHECKLIST.md',
        'AGENTS.md': REPO / 'AGENTS.md',
        'RESULT-20261003at.md': REPO / 'tools/spx/boot-diagnostics/RESULT-20261003at.md',
        'check_rear_lifecycle-current.py': REPO / 'tools/spx/boot-diagnostics/camera-power-20261003/check_rear_lifecycle.py',
        'check_rear_stream_failure-current.py': REPO / 'tools/spx/boot-diagnostics/camera-power-20261003/check_rear_stream_failure.py',
        'STREAM-FAILURE-current.md': REPO / 'tools/spx/boot-diagnostics/camera-power-20261003/STREAM-FAILURE.md',
    }.items():
        shutil.copyfile(path, OUT / name)
    (OUT / 'final-review.json').write_text(json.dumps(dict(
        boot_id=BOOT, cmdline=cmdline, grubenv=env, no_BootNext=True,
        original_legacy_native_defects_reproduced=True, privacy_cases=129,
        leds_unreachable_cases=72, rear_cases=238, strict_native_modules=16,
        v4l2_sha256=sha(media), source_manifest_entries=len(manifest),
        checkpatch_warnings_reviewed=['ENOTSUPP is required by the LED API, distinct from EOPNOTSUPP'],
        hardware_operations=[], modified_modules_installed=False, new_candidate_selected=False,
        hardware_acceptance_open=47, full_port_complete=False,
        limits=['Serialized work/media/GPIO models', 'Retained September kernel exports',
                'Electrical/optical timing and real capture untested']), indent=2)+'\n')
    files = sorted(p for p in OUT.rglob('*') if p.is_file())
    (OUT / 'archive-sha256.txt').write_text(''.join(f'{sha(p)}  {p.relative_to(OUT)}\n' for p in files))
    for line in (OUT / 'archive-sha256.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert sha(OUT / name) == digest
    print(json.dumps(dict(output=str(OUT), files=len(files),
                          manifest_sha256=sha(OUT / 'archive-sha256.txt'))))


if __name__ == '__main__':
    main()
