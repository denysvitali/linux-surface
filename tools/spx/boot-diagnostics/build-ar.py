#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build AR from a complete isolated source snapshot; never deploy or select it."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
STAGE = Path('/var/tmp/spx-mainline-trial-20261003ar')
BOOT_ID = '991a6fbd-2217-4f93-8185-287a223a13f6'
RELEASE = '7.3.0-rc2-spx-mainline-20261003ar+'
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261003aq')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def output(*args):
    return subprocess.check_output(args, cwd=REPO, timeout=90)


def config_states(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_'):
            name, value = line.split('=', 1)
            values[name] = value
    return values


EXPECTED_CONFIG = {
    'CONFIG_LOCALVERSION': '"-spx-mainline-20261003ar"',
    'CONFIG_I2C_QCOM_CCI': 'm', 'CONFIG_VIDEO_DEV': 'm',
    'CONFIG_VIDEO_V4L2_I2C': 'y', 'CONFIG_VIDEO_V4L2_SUBDEV_API': 'y',
    'CONFIG_V4L2_ASYNC': 'm', 'CONFIG_V4L2_FWNODE': 'm',
    'CONFIG_VIDEO_CAMERA_SENSOR': 'y', 'CONFIG_VIDEO_OV13858': 'm',
}


def guard():
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    assert os.uname().release == '6.18.3-1-surface+'
    assert sha(REPO / '.config') == 'f0c4a7ff7ed3659f1f44ede2348d7333803721b5bc1229d57744f7999e619288'
    env = output('grub-editenv', '/boot/grub/grubenv', 'list').decode().splitlines()
    assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
    assert b'BootNext:' not in output('efibootmgr')
    import sys
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics'))
    import aq_boot_guard
    parent = aq_boot_guard.load()
    aq_boot_guard.recovery(parent)
    aq_boot_guard.artifacts(parent)
    assert not json.loads((PARENT / 'independent-result-review.json').read_text())['scoped_passed']
    manifest_hashes = {
        'final-result': '62a941dc10ab963638b1290aac86c63cc1fe935868936fd1d892f9c46085299c',
        'recovery-return': '9c94d29a755c9c8296c3687c523c317dc5aa28fe31038cdef6e7034e2c87eb11',
        'offline-followup-candidates-20261003': 'c05163c4bea62a2845eb90fd4400bb8d91e18d5668f43238a46ff3f37409abc9',
    }
    for name, digest in manifest_hashes.items():
        root = PARENT / name
        assert sha(root / 'sha256.json') == digest, name
        manifest = json.loads((root / 'sha256.json').read_text())
        for filename, expected in manifest.items():
            assert sha(root / filename) == expected, (name, filename)
    returned = json.loads((PARENT / 'recovery-return/report.json').read_text())
    assert returned['userspace_fallback_return_verified']
    assert returned['recovery_boot_id'] == BOOT_ID
    return manifest_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Compile the already prepared, reviewed snapshot')
    parser.add_argument('--review-config', action='store_true', help='Preserve and correct the rejected two media defaults')
    args = parser.parse_args()
    assert not (args.build and args.review_config)
    os.umask(0o077)
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    parent_manifests = guard()
    if args.review_config:
        review_config(parent_manifests)
        return
    if args.build:
        compile_snapshot()
        return
    assert not STAGE.exists()
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
        path.write_text(path.read_text().replace('20261003aq', '20261003ar'))
    assert str(STAGE / 'logging') in (STAGE / 'initcpio/install/spx_diagnostics').read_text()
    (STAGE / 'build-started.json').write_text(json.dumps({
        'boot_id': BOOT_ID, 'release': RELEASE, 'started': time.time(),
        'parent_manifests': parent_manifests, 'source_files': len(records), 'runtime_actions': [], 'boot_selected': False}, indent=2) + '\n')
    run([str(sources / 'scripts/config'), '--file', str(build / '.config'),
         '--set-str', 'LOCALVERSION', '-spx-mainline-20261003ar',
         '--module', 'I2C_QCOM_CCI', '--module', 'VIDEO_DEV',
         '--module', 'VIDEO_OV13858'], 'config-set.log')
    make = ['make', '-C', str(sources), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run(make + ['olddefconfig'], 'config.log')
    before = config_states(STAGE / 'config-before')
    after = config_states(build / '.config')
    delta = {name: {'before': before.get(name, 'n'), 'after': after.get(name, 'n')}
             for name in sorted(set(before) | set(after)) if before.get(name, 'n') != after.get(name, 'n')}
    (STAGE / 'config-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
    assert set(delta) == set(EXPECTED_CONFIG), delta
    assert all(after[name] == value for name, value in EXPECTED_CONFIG.items()), delta
    assert all(name == 'CONFIG_LOCALVERSION' or delta[name]['before'] == 'n' for name in delta)
    (STAGE / 'prepared.json').write_text(json.dumps({
        'release': RELEASE, 'config_sha256': sha(build / '.config'),
        'source_manifest_sha256': sha(STAGE / 'source-files.json'),
        'config_delta': delta, 'no_camera_dt_consumers': True,
        'parent_manifests': parent_manifests, 'boot_selected': False}, indent=2) + '\n')
    os.sync()
    print('AR source/config prepared; full compilation requires --build', flush=True)


def run(args, log, cwd=None):
    start = time.monotonic()
    with (STAGE / log).open('xb') as stream:
        result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    path = STAGE / 'build-commands.json'
    commands = json.loads(path.read_text()) if path.exists() else []
    commands.append({'command': args, 'cwd': str(cwd), 'exit_code': result.returncode,
                     'seconds': round(time.monotonic() - start, 2), 'log': log})
    path.write_text(json.dumps(commands, indent=2) + '\n')
    assert result.returncode == 0, log
    print(log, 'passed', flush=True)


def review_config(parent_manifests):
    assert not (STAGE / 'prepared.json').exists()
    assert not (STAGE / 'compile-started.json').exists()
    source, build = STAGE / 'source', STAGE / 'work-build'
    assert sha(build / '.config') == '3f8bf5589d9282fec044ada6a848f6a74691b28e0aebf042982b93803f83d991'
    failure = STAGE / 'initial-config-review-failure'
    assert not failure.exists()
    failure.mkdir()
    for name, path in {'.config': build / '.config', 'config-delta.json': STAGE / 'config-delta.json',
                       'config.log': STAGE / 'config.log', 'config-set.log': STAGE / 'config-set.log',
                       'build-commands.json': STAGE / 'build-commands.json',
                       'build-ar.py': source / 'tools/spx/boot-diagnostics/build-ar.py'}.items():
        shutil.copy2(path, failure / name)
    delta = json.loads((failure / 'config-delta.json').read_text())
    assert set(delta) == set(EXPECTED_CONFIG) | {'CONFIG_RADIO_ADAPTERS', 'CONFIG_VIDEO_CAMERA_LENS'}
    (failure / 'reason.json').write_text(json.dumps({'rejected_before_compilation': True,
        'unexpected_defaults': ['CONFIG_RADIO_ADAPTERS', 'CONFIG_VIDEO_CAMERA_LENS'],
        'source_snapshot_changed': False}, indent=2) + '\n')
    (failure / 'sha256.json').write_text(json.dumps({p.name: sha(p) for p in sorted(failure.iterdir())}, indent=2) + '\n')
    run([str(source / 'scripts/config'), '--file', str(build / '.config'),
         '--disable', 'RADIO_ADAPTERS', '--disable', 'VIDEO_CAMERA_LENS'], 'config-review-set.log')
    make = ['make', '-C', str(source), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run(make + ['olddefconfig'], 'config-review.log')
    before, after = config_states(STAGE / 'config-before'), config_states(build / '.config')
    delta = {name: {'before': before.get(name, 'n'), 'after': after.get(name, 'n')}
             for name in sorted(set(before) | set(after)) if before.get(name, 'n') != after.get(name, 'n')}
    assert set(delta) == set(EXPECTED_CONFIG), delta
    assert all(after[name] == value for name, value in EXPECTED_CONFIG.items()), delta
    (STAGE / 'config-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
    (STAGE / 'prepared.json').write_text(json.dumps({
        'release': RELEASE, 'config_sha256': sha(build / '.config'),
        'source_manifest_sha256': sha(STAGE / 'source-files.json'),
        'config_delta': delta, 'no_camera_dt_consumers': True,
        'initial_config_failure_manifest_sha256': sha(failure / 'sha256.json'),
        'parent_manifests': parent_manifests, 'boot_selected': False}, indent=2) + '\n')
    os.sync()
    print('Rejected defaults retained; exact nine-setting AR config verified; source snapshot unchanged', flush=True)


def compile_snapshot():
    assert not (STAGE / 'compile-started.json').exists()
    sources, build = STAGE / 'source', STAGE / 'work-build'
    prepared = json.loads((STAGE / 'prepared.json').read_text())
    assert prepared['release'] == RELEASE
    assert sha(build / '.config') == prepared['config_sha256']
    assert sha(STAGE / 'source-files.json') == prepared['source_manifest_sha256']
    assert {name: value['after'] for name, value in prepared['config_delta'].items()} == EXPECTED_CONFIG
    records = json.loads((STAGE / 'source-files.json').read_text())
    for name, record in records.items():
        path = sources / name
        if 'sha256' in record:
            assert sha(path) == record['sha256'], name
        elif 'symlink' in record:
            assert os.readlink(path) == record['symlink'], name
        else:
            assert not path.exists(), name
    (STAGE / 'compile-started.json').write_text(json.dumps({'started': time.time()}) + '\n')
    make = ['make', '-C', str(sources), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
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
    parent_modules = set((PARENT / 'build/artifacts/modules.order').read_text().splitlines())
    current_modules = set((build / 'modules.order').read_text().splitlines())
    expected_new = {
        'drivers/i2c/busses/i2c-qcom-cci.o', 'drivers/media/i2c/ov13858.o',
        'drivers/media/v4l2-core/videodev.o', 'drivers/media/v4l2-core/v4l2-dv-timings.o',
        'drivers/media/v4l2-core/v4l2-async.o', 'drivers/media/v4l2-core/v4l2-fwnode.o',
    }
    delta = {'added': sorted(current_modules - parent_modules), 'removed': sorted(parent_modules - current_modules)}
    (STAGE / 'module-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
    assert not delta['removed'] and set(delta['added']) == expected_new, delta
    for name in files + modules:
        dest = artifacts / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / name, dest)
    import sys
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics'))
    import review_aq_dtb_delta_ar
    review_aq_dtb_delta_ar.verify_base(PARENT, STAGE)
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
        'config_delta': prepared['config_delta'],
        'embedded_config_exact': True, 'base_dtb_only_touch_delay_delta': True,
        'camera_driver_modules_built': True, 'camera_dt_consumers_enabled': False, 'boot_selected': False}, indent=2) + '\n')
    os.sync()
    print('Full AR kernel/modules and base DTB built; provider DTB and initramfs still required', flush=True)


if __name__ == '__main__':
    main()
