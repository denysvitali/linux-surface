#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the frozen AX RTC candidate, without deploying or selecting a boot."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

STAGE = Path('/var/tmp/spx-mainline-trial-20261003ax')
PARENT = Path('/var/tmp/spx-mainline-trial-20261003au')
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
RELEASE = '7.3.0-rc2-spx-mainline-20261003ax+'
BOOT = 'fbc6d663-8269-4d2f-9aac-c4a687583b00'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(records):
    for name, record in records.items():
        path = STAGE / 'source' / name
        if 'sha256' in record:
            assert sha(path) == record['sha256'], name
        elif 'symlink' in record:
            assert os.readlink(path) == record['symlink'], name
        else:
            assert not path.exists(), name


def config_states(path):
    return {line.split('=', 1)[0]: line.split('=', 1)[1]
            for line in path.read_text().splitlines() if line.startswith('CONFIG_')}


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert (STAGE / 'stage-copy-complete.json').exists()
    assert not (STAGE / 'compile-started.json').exists()
    # Reuse the verified, immutable AU source path so normal Kbuild can reuse
    # unchanged objects in a private clone. Only AX's output tree is written.
    sources, build = (STAGE / 'source').resolve(), STAGE / 'work-build'
    records = json.loads((STAGE / 'source-files.json').read_text())
    verify_source(records)
    assert sha(build / '.config') == sha(STAGE / 'config-parent')
    parent_config = sha(PARENT / 'work-build/.config')
    assert parent_config == sha(STAGE / 'config-parent')
    shutil.copy2(__file__, STAGE / 'build-ax.py')
    commands = []

    def run(args, log):
        start = time.monotonic()
        with (STAGE / log).open('xb') as stream:
            result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT)
        commands.append({'command': args, 'exit_code': result.returncode,
                         'seconds': round(time.monotonic() - start, 2), 'log': log})
        (STAGE / 'build-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, log
        print(log, 'passed', flush=True)

    run([str(sources / 'scripts/config'), '--file', str(build / '.config'),
         '--set-str', 'LOCALVERSION', '-spx-mainline-20261003ax'], 'config-set.log')
    run([str(sources / 'scripts/config'), '--file', str(build / '.config'),
         '--enable', 'RTC_SYSTOHC', '--set-str', 'RTC_SYSTOHC_DEVICE', 'rtc0'], 'rtc-config-set.log')
    make = ['make', '-C', str(sources), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run(make + ['olddefconfig'], 'config.log')
    before, after = config_states(STAGE / 'config-parent'), config_states(build / '.config')
    delta = {name: {'before': before.get(name, 'n'), 'after': after.get(name, 'n')}
             for name in sorted(set(before) | set(after))
             if before.get(name, 'n') != after.get(name, 'n')}
    assert delta == {'CONFIG_LOCALVERSION': {
        'before': '"-spx-mainline-20261003au"', 'after': '"-spx-mainline-20261003ax"'},
        'CONFIG_RTC_SYSTOHC': {'before': 'n', 'after': 'y'},
        'CONFIG_RTC_SYSTOHC_DEVICE': {'before': 'n', 'after': '"rtc0"'}}, delta
    prepared = {'release': RELEASE, 'source_manifest_sha256': sha(STAGE / 'source-files.json'),
                'config_sha256': sha(build / '.config'), 'config_delta': delta,
                'boot_selected': False, 'compiled_from_frozen_snapshot': True}
    (STAGE / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    (STAGE / 'compile-started.json').write_text(json.dumps({'started': time.time()}) + '\n')
    run(make + ['prepare'], 'prepare.log')
    assert subprocess.check_output(make + ['-s', 'kernelrelease'], text=True).strip().splitlines()[-1] == RELEASE
    assert (build / 'source').resolve() == sources
    print('Frozen snapshot and distinct AX release verified; full compilation begins', flush=True)
    run(make + ['-j6', 'Image', 'qcom/sc8180x-surface-pro-x.dtb'], 'image-dtb.log')
    run(make + ['-j6', 'modules'], 'modules.log')
    artifacts = STAGE / 'artifacts'
    files = ['.config', 'System.map', 'vmlinux', 'Module.symvers', 'modules.order',
             'arch/arm64/boot/Image', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']
    order = (build / 'modules.order').read_text().splitlines()
    assert set(order) == set((PARENT / 'work-build/modules.order').read_text().splitlines())
    modules = [str(Path(p).with_suffix('.ko')) for p in order]
    assert len(modules) == 193
    for name in files + modules:
        dest = artifacts / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / name, dest)
    dtb = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    assert sha(artifacts / dtb) == sha(PARENT / 'artifacts' / dtb)
    config = (build / '.config').read_bytes()
    assert subprocess.check_output([str(sources / 'scripts/extract-ikconfig'),
                                    str(artifacts / 'arch/arm64/boot/Image')]) == config
    (STAGE / 'config-extracted').write_bytes(config)
    with (STAGE / 'vmlinuz').open('xb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', mtime=0) as gz:
            with (artifacts / 'arch/arm64/boot/Image').open('rb') as image:
                shutil.copyfileobj(image, gz)
    verify_source(records)
    assert (REPO / '.config').read_bytes() == (STAGE / 'live-config-before').read_bytes()
    assert sha(PARENT / 'work-build/.config') == parent_config
    (STAGE / 'build-complete.json').write_text(json.dumps({
        **prepared, 'modules': len(modules), 'source_files': len(records),
        'source_snapshot_unchanged': True, 'live_config_unchanged': True,
        'parent_config_unchanged': True, 'embedded_config_exact': True,
        'base_dtb_exact_au': True,
        'artifacts': {name: sha(artifacts / name) for name in files + modules}}, indent=2) + '\n')
    os.sync()
    print('Full AX kernel and 193 modules built; no deployment or boot selection', flush=True)


if __name__ == '__main__':
    main()
