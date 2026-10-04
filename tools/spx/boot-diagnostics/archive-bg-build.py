#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify/seal BG's full build without installing or selecting it."""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bg_build', HERE / 'build-bg.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
g, STAGE = b.g, b.STAGE
X = g.BASE / 'attempts/20261004bg'


def read(path):
    return json.loads(path.read_text())


def actual_parameters(path, names):
    """Read actual AArch64 ELF BSS and kernel_param permission records."""
    data = path.read_bytes()
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    assert h[0][:6] == b'\x7fELF\x02\x01' and h[2] == 183
    assert h[1] in (1, 2, 3) and h[11] == 64 and 0 < h[12] < 65535
    assert h[6] + h[11] * h[12] <= len(data)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, h[6] + 64 * n)
                for n in range(h[12])]
    wanted = set(names) | {'__param_' + n for n in names}
    symbols = {}
    for sec in sections:
        if sec[1] != 2:
            continue
        assert sec[9] == 24 and sec[5] % 24 == 0
        assert sec[4] + sec[5] <= len(data)
        strings = sections[sec[6]]
        assert strings[4] + strings[5] <= len(data)
        table = data[strings[4]:strings[4] + strings[5]]
        for at in range(sec[4], sec[4] + sec[5], 24):
            s = struct.unpack_from('<IBBHQQ', data, at)
            assert s[0] < len(table)
            name = table[s[0]:table.index(b'\0', s[0])].decode()
            if name in wanted:
                assert name not in symbols, name
                symbols[name] = s
    assert set(symbols) == wanted
    result = {}
    for name in names:
        var = symbols[name]
        assert var[5] == 1 and sections[var[3]][1] == 8, name
        param = symbols['__param_' + name]
        assert param[5] == 40
        sec = sections[param[3]]
        relative = param[4] - (sec[3] if h[1] in (2, 3) else 0)
        assert 0 <= relative and relative + 40 <= sec[5]
        at = sec[4] + relative
        assert at + 40 <= len(data)
        assert struct.unpack_from('<H', data, at + 24)[0] == 0o400
        result[name] = dict(default_zero_bss=True, permission='0o400')
    return result


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BF terminal;') and a['returned_boot_id'] == b.BOOT
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    assert os.uname().release == '6.18.3-1-surface+'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    complete = read(STAGE / 'build-complete.json')
    assert complete['release'] == b.RELEASE and complete['modules'] == 202
    for key in ('full_kernel_linked', 'loadable_modules_linked', 'embedded_config_exact',
                'venus_shared_alloc_actual_zero_default_0400', 'source_snapshot_unchanged',
                'live_config_unchanged', 'raw_dtb_exact_bf'):
        assert complete[key], key
    expected_config = {'CONFIG_LOCALVERSION': {'before': '"-spx-mainline-20261004bf"',
                                              'after': '"-spx-mainline-20261004bg"'}}
    assert complete['config_delta'] == expected_config
    for name, digest in complete['proof_manifests'].items():
        root = g.X / name
        assert g.sha(root / 'sha256.json') == digest
        assert g.files(root) == read(root / 'sha256.json') | {'sha256.json': digest}
    rows = read(STAGE / 'source-files.json')
    parent = read(g.X / 'assembly/source-files.json')
    assert len(rows) == 96938 and b.records(STAGE / 'source') == rows
    assert read(STAGE / 'parent-bf-source-files.json') == parent
    assert set(rows) == set(parent)
    assert {name for name in rows if rows[name] != parent[name]} == {b.CHANGED}
    assert rows[b.CHANGED]['sha256'] == b.CANDIDATE_SHA
    expected_delta = {b.CHANGED: dict(before_sha256=parent[b.CHANGED]['sha256'],
                                     after_sha256=b.CANDIDATE_SHA)}
    assert read(STAGE / 'compiled-source-delta.json') == expected_delta
    assert complete['one_shared_allocation_source_change'] == expected_delta
    assert rows[b.BOARD] == parent[b.BOARD]
    seen, file_bytes = set(), 0
    source_tar = STAGE / 'source.tar.zst'
    with subprocess.Popen(['zstd', '-dc', str(source_tar)], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                name = entry.name.removeprefix('./')
                assert name not in seen and name in rows
                seen.add(name)
                row = rows[name]
                if entry.issym():
                    assert row == dict(symlink=entry.linkname)
                else:
                    assert entry.isfile() and entry.mode == row['mode'] and entry.size == row['bytes']
                    digest = hashlib.sha256()
                    stream = archive.extractfile(entry)
                    for chunk in iter(lambda: stream.read(1048576), b''):
                        digest.update(chunk)
                    assert digest.hexdigest() == row['sha256'], name
                    file_bytes += entry.size
        assert proc.wait() == 0
    assert seen == set(rows) and g.sha(source_tar) == complete['source_archive_sha256']
    assert read(STAGE / 'source-tar.json')['sha256'] == g.sha(source_tar)
    assert g.sha(STAGE / 'source-files.json') == complete['source_manifest_sha256']
    print(json.dumps(dict(source_archive_stream_verified=len(seen), file_bytes=file_bytes)), flush=True)
    commands = read(STAGE / 'commands.json')
    assert [r['label'] for r in commands] == ['snapshot', 'source-archive', 'output-clone',
        'config-set', 'olddefconfig', 'prepare', 'image-dtb', 'modules']
    assert all(r['exit_code'] == 0 for r in commands)
    make = ['make', '-C', str(STAGE / 'source'), 'O=' + str(STAGE / 'work-build'),
            'ARCH=arm64', 'LOCALVERSION=+']
    assert commands[-2]['argv'] == make + ['-j6', 'Image', 'qcom/sc8180x-surface-pro-x.dtb']
    assert commands[-1]['argv'] == make + ['-j6', 'modules']
    for name, digest in complete['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
        assert g.sha(STAGE / 'work-build' / name) == digest, name
    config = (STAGE / 'artifacts/.config').read_bytes()
    assert config == (STAGE / 'work-build/.config').read_bytes() == (STAGE / 'config-extracted').read_bytes()
    assert g.sha(STAGE / 'artifacts/.config') == complete['config_sha256']
    assert subprocess.check_output([str(STAGE / 'source/scripts/extract-ikconfig'),
                                    str(STAGE / 'artifacts/arch/arm64/boot/Image')]) == config
    assert gzip.decompress((STAGE / 'vmlinuz').read_bytes()) == (STAGE / 'artifacts/arch/arm64/boot/Image').read_bytes()
    cfg_before, cfg_after = b.states(STAGE / 'config-parent'), b.states(STAGE / 'artifacts/.config')
    assert {k: dict(before=cfg_before.get(k, 'n'), after=cfg_after.get(k, 'n'))
        for k in set(cfg_before) | set(cfg_after) if cfg_before.get(k, 'n') != cfg_after.get(k, 'n')} == expected_config
    assert g.sha(STAGE / 'config-parent') == g.sha(b.PARENT / 'work-build/.config')
    assert (STAGE / 'live-config-before').read_bytes() == (b.REPO / '.config').read_bytes()
    order = (STAGE / 'artifacts/modules.order').read_text().splitlines()
    assert len(order) == len(set(order)) == 202
    assert set(order) == set((b.PARENT / 'work-build/modules.order').read_text().splitlines())
    vermagic = {}
    for name in order:
        path = STAGE / 'artifacts' / Path(name).with_suffix('.ko')
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).strip()
        assert value.split()[0] == b.RELEASE
        vermagic[str(path.relative_to(STAGE / 'artifacts'))] = value
    assert read(STAGE / 'module-vermagic.json') == vermagic
    venus = STAGE / 'artifacts/drivers/media/platform/qcom/venus/venus-core.ko'
    actual_parms = dict(venus=actual_parameters(venus, ['spx_hfi_startup_diag', 'spx_uc_shared_alloc']),
        scm=actual_parameters(STAGE / 'artifacts/vmlinux', ['spx_pas_diag', 'spx_pas_area_diag']))
    assert set(subprocess.check_output(['modinfo', '-F', 'parmtype', str(venus)], text=True).splitlines()) >= {
        'spx_hfi_startup_diag:bool', 'spx_uc_shared_alloc:bool'}
    symbols = subprocess.check_output(['nm', '--defined-only', str(venus)], text=True)
    parsed = {r.split()[-1]: r.split()[-2] for r in symbols.splitlines() if len(r.split()) == 3}
    assert parsed['venus_hfi_startup_diag'] == 'T' and parsed['spx_hfi_startup_diag_lines'] == 'b'
    raw = STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    boot_dtb = STAGE / 'spx.dtb'
    assert raw.read_bytes() == (g.X / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb').read_bytes()
    assert boot_dtb.read_bytes() == (g.X / 'build/spx.dtb').read_bytes()
    spec = importlib.util.spec_from_file_location('provider_contract', HERE / 'video-power-20261003/video_dt_contract.py')
    providers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(providers)
    assert providers.EXPECTED['memory-region'] == [('/reserved-memory/video-firmware', [])]
    providers.EXPECTED['memory-region'] = [('/reserved-memory/video-firmware@8d300000', [])]
    provider_results = dict(raw=providers.validate(raw.read_bytes()), retained=providers.validate(boot_dtb.read_bytes()))
    import libfdt
    for path in (raw, boot_dtb):
        tree = libfdt.Fdt(path.read_bytes())
        mem = tree.path_offset('/reserved-memory/video-firmware@8d300000')
        assert bytes(tree.getprop(mem, 'reg')) == struct.pack('>4I', 0, 0x8d300000, 0, 0x500000)
        assert bytes(tree.getprop(mem, 'no-map')) == b''
    warnings = []
    for name in ('image-dtb.log', 'modules.log'):
        lines = (STAGE / name).read_text().splitlines()
        assert not any('error:' in line for line in lines)
        actual = sorted(line.replace(str(STAGE), '<STAGE>') for line in lines if 'warning:' in line)
        prior = sorted(line.replace(str(b.PARENT), '<STAGE>') for line in (g.X / 'build' / name).read_text().splitlines() if 'warning:' in line)
        assert actual == prior, (name, actual, prior)
        warnings.extend(actual)
    assert len(warnings) == 5
    checked = b.live_source()
    assert not g.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    X.mkdir(mode=0o700)
    target = X / 'build'
    target.mkdir(mode=0o700)
    for path in sorted(STAGE.iterdir()):
        if path.is_file() and not path.is_symlink():
            shutil.copy2(path, target / path.name)
    shutil.copytree(STAGE / 'artifacts', target / 'artifacts')
    shutil.copy2(__file__, target / Path(__file__).name)
    shutil.copy2(g.X / 'working-recovery.json', X / 'working-recovery.json')
    shutil.copy2(g.X / 'actual-known-good-return/report.json', target / 'parent-actual-return.json')
    shutil.copy2(HERE / 'video-power-20261003/video_dt_contract.py', target / 'video_dt_contract.py')
    shutil.copytree('/var/tmp/spx-bg-preflight-path-correction-20261004', target / 'preflight-path-correction')
    shutil.copytree('/var/tmp/spx-bg-archive-elf-precheck-20261004-v1', target / 'elf-precheck-original-failure')
    shutil.copytree('/var/tmp/spx-bg-archive-elf-precheck-20261004-v2', target / 'elf-precheck-correction')
    (target / 'provider-contracts.json').write_text(json.dumps(provider_results, indent=2) + '\n')
    (target / 'actual-parameters.json').write_text(json.dumps(actual_parms, indent=2) + '\n')
    for path in sorted(target.rglob('*')):
        if path.is_file() and (STAGE / path.relative_to(target)).is_file():
            assert g.sha(path) == g.sha(STAGE / path.relative_to(target))
    (X / 'build-sha256.json').write_text(json.dumps(g.files(target), indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), release=b.RELEASE, parent_attempt=a['attempt'],
        current_boot_id=b.BOOT, source_archive_stream_verified=True, source_records_verified=len(rows),
        source_file_bytes_streamed=file_bytes, live_compiled_source_paths_verified=checked,
        full_kernel_linked=True, loadable_modules_linked=True, modules=202, all_module_vermagic_exact=True,
        embedded_config_exact=True, config_delta=expected_config, one_source_change_relative_bf=expected_delta,
        raw_and_retained_dtb_exact_bf=True, provider_contracts_verified=True,
        provider_expected_delta={'memory-region': '/reserved-memory/video-firmware@8d300000'},
        actual_default_off_parameters=actual_parms, proof_manifests=complete['proof_manifests'],
        original_preflight_path_interruption_preserved=True, compiler_warnings_exact_bf=warnings,
        current_and_parent_config_unchanged=True, source_archive_sha256=g.sha(source_tar),
        source_manifest_sha256=g.sha(STAGE / 'source-files.json'),
        kernel_image_sha256=g.sha(STAGE / 'artifacts/arch/arm64/boot/Image'),
        compressed_kernel_sha256=g.sha(STAGE / 'vmlinuz'), config_sha256=g.sha(STAGE / 'artifacts/.config'),
        raw_dtb_sha256=g.sha(raw), boot_dtb_sha256=g.sha(boot_dtb),
        build_manifest_sha256=g.sha(X / 'build-sha256.json'), build_files=len(g.files(target)),
        known_good_recovery_reverified=True, persistent_default='spx-known-good', next_entry_empty=True,
        early_recovery_validated=False, initramfs_assembled=False, module_tree_installed=False,
        runtime_prepared=False, deployed=False, boot_selected=False, hardware_acceptance_closed=False)
    (X / 'build-review.json').write_text(json.dumps(report, indent=2) + '\n')
    os.sync()
    assert g.files(target) == read(X / 'build-sha256.json')
    assert not g.recovery(a).get('next_entry', '')
    print(json.dumps(report | dict(build_review_sha256=g.sha(X / 'build-review.json'))), flush=True)


if __name__ == '__main__':
    main()
