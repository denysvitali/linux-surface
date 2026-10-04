#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze and fully build the BB PAS diagnostic candidate without installing or booting it."""
from datetime import datetime, timezone
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ba_boot_guard as g

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/tmp/spx-mainline-trial-20261004ba/source')
PARENT = Path('/var/tmp/spx-mainline-trial-20261004ba')
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bb')
BOOT = 'a824008e-cf43-4287-84f8-4e930fa41a06'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bb+'
CHANGED = ('drivers/firmware/qcom/qcom_scm.c',
           'drivers/firmware/qcom/qcom_scm-smc.c',
           'drivers/firmware/qcom/qcom_scm.h')


def records(root):
    result = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink():
            result[name] = dict(symlink=os.readlink(path))
        elif path.is_file():
            result[name] = dict(sha256=g.sha(path), bytes=path.stat().st_size,
                                mode=stat.S_IMODE(path.stat().st_mode))
    return result


def states(path):
    return {line.split('=', 1)[0]: line.split('=', 1)[1]
            for line in path.read_text().splitlines() if line.startswith('CONFIG_')}


def main():
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert a['state'] == 'BA terminal; guarded return verified'
    capsule = g.X / 'offline-pas-diag-20261004'
    assert g.sha(capsule / 'sha256.json') == '2ef2de5057329f649216ed2a418493f5ea02758f90cffd3ae10560253528e9c2'
    expected_capsule = json.loads((capsule / 'sha256.json').read_text())
    assert len(expected_capsule) == 192 and g.files(capsule) == expected_capsule | {
        'sha256.json': g.sha(capsule / 'sha256.json')}
    diagnostic = json.loads((capsule / 'report.json').read_text())
    assert diagnostic['native_actual_body_checks'] == 91 and diagnostic['rejected_candidate_controls'] == 5
    assert set(diagnostic['exact_three_source_changes']) == set(CHANGED)
    for name in CHANGED:
        assert g.sha(REPO / name) == diagnostic['exact_three_source_changes'][name]['after_sha256']
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    returned = g.X / 'return-review'
    assert g.files(returned) == json.loads((returned / 'sha256.json').read_text()) | {
        'sha256.json': g.sha(returned / 'sha256.json')}
    assert g.sha(returned / 'sha256.json') == 'f1324030e2dc1361bae3565ce416e1d65fb1d875a02947131393347d1eefd3e0'
    terminal = json.loads((returned / 'report.json').read_text())
    assert terminal['returned_boot_id'] == BOOT and terminal['baseline_replay_exact']
    os.umask(0o077)
    STAGE.mkdir(mode=0o700)
    source, build = STAGE / 'source', STAGE / 'work-build'
    shutil.copy2(__file__, STAGE / 'build-bb.py')
    shutil.copy2(REPO / '.config', STAGE / 'live-config-before')
    shutil.copy2(PARENT / 'work-build/.config', STAGE / 'config-parent')
    shutil.copy2(g.X / 'build/source-files.json', STAGE / 'base-source-files.json')
    parent_config = g.sha(PARENT / 'work-build/.config')
    assert parent_config == g.sha(g.X / 'build/config-extracted')
    commands = []

    def run(label, argv):
        started = time.monotonic()
        with (STAGE / (label + '.log')).open('xb') as stream:
            result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT)
        commands.append(dict(label=label, argv=argv, exit_code=result.returncode,
                             seconds=round(time.monotonic() - started, 3)))
        (STAGE / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        print(json.dumps(commands[-1]), flush=True)
        assert result.returncode == 0, label

    run('snapshot', ['cp', '-a', '--reflink=auto', str(BASE), str(source)])
    original = json.loads((STAGE / 'base-source-files.json').read_text())
    actual = records(source)
    assert len(actual) == len(original) == 96938
    # Prior records can omit byte counts, but all declared fields must match.
    for name, row in original.items():
        assert all(actual[name][key] == value for key, value in row.items()), name
    delta, patch = {}, []
    for name in CHANGED:
        path = source / name
        before = path.read_text() if path.exists() else ''
        after = (REPO / name).read_text()
        assert before != after, name
        delta[name] = dict(before_sha256=g.sha(path) if path.exists() else None,
                           after_sha256=g.sha(REPO / name))
        patch.extend(difflib.unified_diff(before.splitlines(keepends=True),
                     after.splitlines(keepends=True), fromfile='a/' + name, tofile='b/' + name))
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / name, path)
    assert delta == diagnostic['exact_three_source_changes']
    final = records(source)
    assert set(final) == set(original) and len(final) == 96938
    assert {name for name in final if final[name] != actual.get(name)} == set(CHANGED)
    (STAGE / 'source-files.json').write_text(json.dumps(final, indent=2) + '\n')
    (STAGE / 'compiled-source-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
    (STAGE / 'source.diff').write_text(''.join(patch))
    run('source-archive', ['tar', '--zstd', '-cf', str(STAGE / 'source.tar.zst'),
                           '-C', str(source), '.'])
    seen = set()
    with subprocess.Popen(['zstd', '-dc', str(STAGE / 'source.tar.zst')], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                name = entry.name.removeprefix('./')
                assert name not in seen and name in final, name
                seen.add(name)
                row = final[name]
                if entry.issym():
                    assert row == dict(symlink=entry.linkname), name
                else:
                    assert entry.isfile() and entry.mode == row['mode'] and entry.size == row['bytes'], name
                    digest = hashlib.sha256()
                    data = archive.extractfile(entry)
                    for chunk in iter(lambda: data.read(1048576), b''):
                        digest.update(chunk)
                    assert digest.hexdigest() == row['sha256'], name
        assert proc.wait() == 0
    assert seen == set(final)
    (STAGE / 'source-tar.json').write_text(json.dumps(dict(
        source_archive_stream_verified=True, records_verified=len(seen),
        sha256=g.sha(STAGE / 'source.tar.zst')), indent=2) + '\n')
    run('output-clone', ['cp', '-a', '--reflink=auto', str(PARENT / 'work-build'), str(build)])
    make = ['make', '-C', str(source), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run('config-set', [str(source / 'scripts/config'), '--file', str(build / '.config'),
                       '--set-str', 'LOCALVERSION', '-spx-mainline-20261004bb',
                       '-m', 'SM_VIDEOCC_8150'])
    run('olddefconfig', make + ['olddefconfig'])
    before, after = states(STAGE / 'config-parent'), states(build / '.config')
    config_delta = {key: dict(before=before.get(key, 'n'), after=after.get(key, 'n'))
                    for key in sorted(set(before) | set(after))
                    if before.get(key, 'n') != after.get(key, 'n')}
    required = {'CONFIG_LOCALVERSION': '"-spx-mainline-20261004bb"'}
    assert {key: row['after'] for key, row in config_delta.items()} == required, config_delta
    assert after.get('CONFIG_VIDEO_QCOM_IRIS', 'n') == 'n'
    assert after['CONFIG_RTC_SYSTOHC'] == 'y' and after['CONFIG_RTC_SYSTOHC_DEVICE'] == '"rtc0"'
    prepared = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT, release=RELEASE,
                    source_files=len(final), source_manifest_sha256=g.sha(STAGE / 'source-files.json'),
                    config_sha256=g.sha(build / '.config'), config_delta=config_delta,
                    source_archive_sha256=g.sha(STAGE / 'source.tar.zst'), boot_selected=False)
    (STAGE / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    (STAGE / 'compile-started.json').write_text(json.dumps(dict(utc=prepared['utc'])) + '\n')
    run('prepare', make + ['prepare'])
    assert (build / 'source').resolve() == source
    assert subprocess.check_output(make + ['-s', 'kernelrelease'], text=True).strip().splitlines()[-1] == RELEASE
    run('image-dtb', make + ['-j6', 'Image', 'qcom/sc8180x-surface-pro-x.dtb'])
    run('modules', make + ['-j6', 'modules'])
    artifacts = STAGE / 'artifacts'
    order = (build / 'modules.order').read_text().splitlines()
    parent_order = (PARENT / 'work-build/modules.order').read_text().splitlines()
    expected = set()
    assert set(order) - set(parent_order) == expected and not set(parent_order) - set(order)
    assert len(order) == 202
    provider = build / 'drivers/clk/qcom/videocc-sm8150.ko'
    aliases = subprocess.check_output(['modinfo', '-F', 'alias', str(provider)], text=True)
    assert 'qcom,sm8150-videocc' in aliases
    (STAGE / 'videocc-module-aliases.txt').write_text(aliases)
    assert after['CONFIG_SM_GCC_8150'] == 'y' and after['CONFIG_QCOM_GDSC'] == 'y'
    modules = [str(Path(name).with_suffix('.ko')) for name in order]
    names = ['.config', 'System.map', 'vmlinux', 'Module.symvers', 'modules.order',
             'arch/arm64/boot/Image', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']
    for name in names + modules:
        dest = artifacts / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / name, dest)
    config = (build / '.config').read_bytes()
    assert subprocess.check_output([str(source / 'scripts/extract-ikconfig'),
                                    str(artifacts / 'arch/arm64/boot/Image')]) == config
    (STAGE / 'config-extracted').write_bytes(config)
    with (STAGE / 'vmlinuz').open('xb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', mtime=0) as compressed:
            with (artifacts / 'arch/arm64/boot/Image').open('rb') as image:
                shutil.copyfileobj(image, compressed)
    assert records(source) == final
    for name, row in delta.items():
        assert g.sha(REPO / name) == row['after_sha256']
    assert (REPO / '.config').read_bytes() == (STAGE / 'live-config-before').read_bytes()
    assert g.sha(PARENT / 'work-build/.config') == parent_config
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    result = dict(**prepared, utc_complete=datetime.now(timezone.utc).isoformat(),
                  modules=len(modules), added_modules=sorted(expected),
                  source_snapshot_unchanged=True, live_config_unchanged=True,
                  parent_config_unchanged=True, embedded_config_exact=True,
                  artifacts={name: g.sha(artifacts / name) for name in names + modules},
                  full_kernel_linked=True, loadable_modules_linked=True,
                  deployed=False, hardware_operations=0)
    result['pas_diagnostic_capsule_sha256'] = g.sha(capsule / 'sha256.json')
    (STAGE / 'build-complete.json').write_text(json.dumps(result, indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(release=RELEASE, modules=len(modules), files=len(final),
                          source_manifest_sha256=prepared['source_manifest_sha256'])), flush=True)


if __name__ == '__main__':
    main()
