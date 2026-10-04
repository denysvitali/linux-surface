#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze and fully build the BF bounded Venus startup candidate without installing or booting it."""
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
import be_boot_guard as g

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/tmp/spx-mainline-trial-20261004bc/source')
PARENT = Path('/var/tmp/spx-mainline-trial-20261004bc')
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bf')
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'
BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'
DIAGNOSTIC = ('drivers/media/platform/qcom/venus/hfi_venus.c',
              'drivers/media/platform/qcom/venus/firmware.c',
              'drivers/media/platform/qcom/venus/firmware.h')
CHANGED = DIAGNOSTIC + (BOARD,)


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


def live_source(diagnostic):
    rows = json.loads((g.X / 'dtb-build/candidate-source-files.json').read_text())
    changes = diagnostic['exact_three_source_changes']
    checked = 0
    for name, row in rows.items():
        top = Path(name).parts[0]
        if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or
                (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
            continue
        path = REPO / name
        if name in changes:
            assert g.sha(path) == changes[name]['after_sha256']
            assert row['sha256'] == changes[name]['before_sha256']
        elif 'sha256' in row:
            assert g.sha(path) == row['sha256'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
        checked += 1
    assert checked == 84669
    assert g.sha(REPO / '.config') == g.sha(g.X / 'build/live-config-before')
    return checked


def main():
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    capsule = g.X / 'offline-venus-startup-diag-20261004'
    assert g.sha(capsule / 'sha256.json') == '24ac5c41623b08a93ad64b04896db0f0ba467263e65793af1513abede701a5b1'
    expected_capsule = json.loads((capsule / 'sha256.json').read_text())
    assert len(expected_capsule) == 186 and g.files(capsule) == expected_capsule | {
        'sha256.json': g.sha(capsule / 'sha256.json')}
    diagnostic = json.loads((capsule / 'report.json').read_text())
    assert diagnostic['native_before_after_comparisons'] == 79296
    assert diagnostic['rejected_candidate_controls'] == 6
    assert diagnostic['actual_kbuild_aarch64_constituent_objects'] == 14
    assert diagnostic['default_off_read_only_iris1'] and diagnostic['relocatable_link_verified']
    assert diagnostic['shared_diagnostic_line_limit'] == 32
    assert set(diagnostic['exact_three_source_changes']) == set(DIAGNOSTIC)
    live_source(diagnostic)
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    returned = g.X / 'actual-known-good-return'
    assert g.files(returned) == json.loads((returned / 'sha256.json').read_text()) | {
        'sha256.json': g.sha(returned / 'sha256.json')}
    assert g.sha(returned / 'sha256.json') == '7b4809519672db379d9c3622dd942656da1b5d304caa94f91d805664403a66ca'
    assert g.sha(REPO / BOARD) == '0edc078ca14ca2818c4c26313baf79d121c6e05cafb1ab93ac68d3a1629f9912'
    os.umask(0o077)
    STAGE.mkdir(mode=0o700)
    source, build = STAGE / 'source', STAGE / 'work-build'
    shutil.copy2(__file__, STAGE / 'build-bf.py')
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
    assert {n: r for n, r in delta.items() if n in DIAGNOSTIC} == diagnostic['exact_three_source_changes']
    final = records(source)
    assert set(final) == set(original) and len(final) == 96938
    assert {name for name in final if final[name] != actual.get(name)} == set(CHANGED)
    be_rows = json.loads((g.X / 'dtb-build/candidate-source-files.json').read_text())
    assert set(final) == set(be_rows)
    observed_delta = set()
    for name, row in be_rows.items():
        if any(final[name].get(key) != value for key, value in row.items()):
            observed_delta.add(name)
    assert observed_delta == set(DIAGNOSTIC)
    shutil.copy2(g.X / 'dtb-build/candidate-source-files.json', STAGE / 'parent-be-source-files.json')
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
                       '--set-str', 'LOCALVERSION', '-spx-mainline-20261004bf'])
    run('olddefconfig', make + ['olddefconfig'])
    before, after = states(STAGE / 'config-parent'), states(build / '.config')
    config_delta = {key: dict(before=before.get(key, 'n'), after=after.get(key, 'n'))
                    for key in sorted(set(before) | set(after))
                    if before.get(key, 'n') != after.get(key, 'n')}
    required = {'CONFIG_LOCALVERSION': '"-spx-mainline-20261004bf"'}
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
    symbols = subprocess.check_output(['nm', '--defined-only', str(artifacts / 'vmlinux')], text=True)
    parsed_symbols = {row.split()[-1]: row.split()[-2] for row in symbols.splitlines() if len(row.split()) == 3}
    assert parsed_symbols['qcom_scm_spx_pas_diag'] == 'T'
    for name in ('spx_pas_diag', 'spx_pas_area_diag'):
        assert parsed_symbols[name] == 'b'
        assert ('qcom_scm.' + name + '\0').encode() in (artifacts / 'vmlinux').read_bytes()
    raw_dtb = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    assert (artifacts / raw_dtb).read_bytes() == (g.X / 'dtb-build/raw-after.dtb').read_bytes()
    venus = artifacts / 'drivers/media/platform/qcom/venus/venus-core.ko'
    module_symbols = subprocess.check_output(['nm', '--defined-only', str(venus)], text=True)
    parsed_module_symbols = {r.split()[-1]: r.split()[-2] for r in module_symbols.splitlines() if len(r.split()) == 3}
    assert parsed_module_symbols['venus_hfi_startup_diag'] == 'T'
    assert parsed_module_symbols['spx_hfi_startup_diag'] == 'b'
    assert parsed_module_symbols['spx_hfi_startup_diag_lines'] == 'b'
    parms = subprocess.check_output(['modinfo', '-F', 'parmtype', str(venus)], text=True).splitlines()
    assert 'spx_hfi_startup_diag:bool' in parms
    (STAGE / 'venus-module-parmtype.txt').write_text('\n'.join(parms) + '\n')
    assert b'SPX Venus startup poll' in venus.read_bytes()
    assert b'SPX Venus startup buffers' in venus.read_bytes()
    assert b'SPX Venus startup auth-reset' in venus.read_bytes()
    assert b'SPX Venus startup remote-state' in venus.read_bytes()
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
    checked = live_source(diagnostic)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    result = dict(**prepared, utc_complete=datetime.now(timezone.utc).isoformat(),
                  modules=len(modules), added_modules=sorted(expected),
                  source_snapshot_unchanged=True, live_config_unchanged=True,
                  parent_config_unchanged=True, embedded_config_exact=True,
                  artifacts={name: g.sha(artifacts / name) for name in names + modules},
                  full_kernel_linked=True, loadable_modules_linked=True,
                  live_compiled_source_paths_verified=checked,
                  raw_dtb_exact_parent_be=True,
                  three_diagnostic_source_changes_relative_be=True,
                  venus_startup_diagnostic_default_zero_verified=True,
                  venus_shared_gate_link_resolved=True, diagnostic_flags_default_zero_verified=True,
                  both_diagnostic_parameter_namespaces_verified=True,
                  deployed=False, hardware_operations=0,
                  hardware_acceptance_closed=False)
    result['venus_diagnostic_capsule_sha256'] = g.sha(capsule / 'sha256.json')
    (STAGE / 'build-complete.json').write_text(json.dumps(result, indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(release=RELEASE, modules=len(modules), files=len(final),
                          source_manifest_sha256=prepared['source_manifest_sha256'])), flush=True)


if __name__ == '__main__':
    main()
