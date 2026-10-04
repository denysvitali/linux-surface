#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build AQ from a complete isolated source snapshot; never deploy or select it."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
STAGE = Path('/var/tmp/spx-mainline-trial-20261003aq')
BOOT_ID = '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'
RELEASE = '7.3.0-rc2-spx-mainline-20261003aq+'
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261002ap')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def output(*args):
    return subprocess.check_output(args, cwd=REPO, timeout=90)


def main():
    os.umask(0o077)
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    assert os.geteuid() == 0 and not STAGE.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    assert os.uname().release == '7.3.0-rc2-spx-mainline-20261001am+'
    assert sha(REPO / '.config') == 'f0c4a7ff7ed3659f1f44ede2348d7333803721b5bc1229d57744f7999e619288'
    env = output('grub-editenv', '/boot/grub/grubenv', 'list').decode().splitlines()
    assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
    assert b'BootNext:' not in output('efibootmgr')
    # Validate installed recovery/artifacts independently of AP's obsolete source guard.
    import sys
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics'))
    import ap_boot_guard
    parent = ap_boot_guard.load()
    ap_boot_guard.recovery(parent)
    ap_boot_guard.artifacts(parent)
    assert json.loads((PARENT / 'independent-result-review.json').read_text())['scoped_passed']
    STAGE.mkdir(mode=0o700)
    sources = STAGE / 'source'
    build = STAGE / 'work-build'
    sources.mkdir()
    build.mkdir()
    (STAGE / 'source-commit.txt').write_bytes(output('git', 'rev-parse', 'HEAD'))
    (STAGE / 'source.diff').write_bytes(output('git', 'diff', '--binary', 'HEAD'))
    (STAGE / 'source-status.txt').write_bytes(output('git', 'status', '--short', '--untracked-files=all'))
    names = sorted(set(output('git', 'ls-files', '-z', '--cached', '--others',
                              '--exclude-standard').decode().strip('\0').split('\0')))
    records = {}
    for name in names:
        src, dst = REPO / name, sources / name
        if not src.exists() and not src.is_symlink():
            records[name] = {'absent': True}
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
            records[name] = {'symlink': os.readlink(src)}
        else:
            shutil.copy2(src, dst)
            records[name] = {'sha256': sha(dst), 'mode': dst.stat().st_mode & 0o777}
            assert sha(src) == records[name]['sha256'], name
    (STAGE / 'source-files.json').write_text(json.dumps(records, indent=2) + '\n')
    shutil.copy2(REPO / '.config', STAGE / 'config-before')
    shutil.copy2(REPO / '.config', build / '.config')
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / 'build' / name, STAGE / name, symlinks=True)
    shutil.copy2(PARENT / 'build/mkinitcpio.conf', STAGE / 'mkinitcpio.conf')
    for path in (STAGE / 'initcpio/install/spx_diagnostics', STAGE / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace('20261001am', '20261003aq'))
    assert str(STAGE / 'logging') in (STAGE / 'initcpio/install/spx_diagnostics').read_text()
    (STAGE / 'build-started.json').write_text(json.dumps({
        'boot_id': BOOT_ID, 'release': RELEASE, 'started': time.time(),
        'source_files': len(records), 'runtime_actions': [], 'boot_selected': False}, indent=2) + '\n')
    commands = []

    def run(args, log, cwd=sources):
        start = time.monotonic()
        with (STAGE / log).open('wb') as stream:
            result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        commands.append({'command': args, 'cwd': str(cwd), 'exit_code': result.returncode,
                         'seconds': round(time.monotonic() - start, 2), 'log': log})
        (STAGE / 'build-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, log
        print(log, 'passed', flush=True)

    run([str(sources / 'scripts/config'), '--file', str(build / '.config'),
         '--set-str', 'LOCALVERSION', '-spx-mainline-20261003aq'], 'config-set.log')
    make = ['make', '-C', str(sources), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run(make + ['olddefconfig'], 'config.log')
    before = set((STAGE / 'config-before').read_text().splitlines())
    after = set((build / '.config').read_text().splitlines())
    assert before - after == {'CONFIG_LOCALVERSION="-spx-mainline-20261001am"'}
    assert after - before == {'CONFIG_LOCALVERSION="-spx-mainline-20261003aq"'}
    run(make + ['prepare'], 'prepare.log')
    assert subprocess.check_output(make + ['-s', 'kernelrelease'], cwd=sources,
                                   text=True).strip().splitlines()[-1] == RELEASE
    print('Snapshot and distinct release verified; compiling full kernel', flush=True)
    run(make + ['-j6', 'Image', 'qcom/sc8180x-surface-pro-x.dtb'], 'image-dtb.log')
    run(make + ['-j6', 'modules'], 'modules.log')
    artifacts = STAGE / 'artifacts'
    files = ['.config', 'System.map', 'vmlinux', 'Module.symvers', 'modules.order',
             'arch/arm64/boot/Image', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']
    modules = [str(Path(p).with_suffix('.ko')) for p in (build / 'modules.order').read_text().splitlines()]
    assert len(modules) == 187
    for name in files + modules:
        dest = artifacts / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / name, dest)
    assert sha(artifacts / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb') == \
        '5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
    with (STAGE / 'vmlinuz').open('wb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', mtime=0) as gz:
            with (artifacts / 'arch/arm64/boot/Image').open('rb') as image:
                shutil.copyfileobj(image, gz)
    config = (build / '.config').read_bytes()
    assert subprocess.check_output([str(sources / 'scripts/extract-ikconfig'),
                                    str(artifacts / 'arch/arm64/boot/Image')]) == config
    (STAGE / 'config-extracted').write_bytes(config)
    for name, record in records.items():
        path = sources / name
        if 'sha256' in record:
            assert sha(path) == record['sha256'], name
        elif 'symlink' in record:
            assert os.readlink(path) == record['symlink'], name
    assert (REPO / '.config').read_bytes() == (STAGE / 'config-before').read_bytes()
    (STAGE / 'build-complete.json').write_text(json.dumps({
        'release': RELEASE, 'modules': len(modules), 'source_files': len(records),
        'source_snapshot_unchanged': True, 'live_config_unchanged': True,
        'config_delta': 'LOCALVERSION only; explicit Kbuild LOCALVERSION=+ in isolated tree',
        'embedded_config_exact': True, 'base_dtb_exact_am': True,
        'camera_sensors_enabled': False, 'boot_selected': False}, indent=2) + '\n')
    os.sync()
    print('Full AQ kernel/modules and base DTB built; provider DTB and initramfs still required', flush=True)


if __name__ == '__main__':
    main()
