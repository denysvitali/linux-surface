#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify/seal BF's full build; no runtime deployment or selection."""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bf_build', HERE / 'build-bf.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
g = b.g
STAGE = b.STAGE
X = g.BASE / 'attempts/20261004bf'


def read(path):
    return json.loads(path.read_text())


def sealed(root, digest):
    assert g.sha(root / 'sha256.json') == digest
    assert g.files(root) == read(root / 'sha256.json') | {'sha256.json': digest}


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    assert os.uname().release == '6.18.3-1-surface+'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    capsule = g.X / 'offline-venus-startup-diag-20261004'
    diagnostic_sha = '24ac5c41623b08a93ad64b04896db0f0ba467263e65793af1513abede701a5b1'
    sealed(capsule, diagnostic_sha)
    diagnostic = read(capsule / 'report.json')
    assert diagnostic['native_before_after_comparisons'] == 79296 and diagnostic['rejected_candidate_controls'] == 6
    complete = read(STAGE / 'build-complete.json')
    assert complete['release'] == b.RELEASE and complete['modules'] == 202
    assert complete['full_kernel_linked'] and complete['loadable_modules_linked']
    assert complete['embedded_config_exact'] and complete['venus_shared_gate_link_resolved']
    assert complete['venus_diagnostic_capsule_sha256'] == diagnostic_sha
    assert complete['source_snapshot_unchanged'] and complete['live_config_unchanged']
    expected_delta = {'CONFIG_LOCALVERSION': {'before': '"-spx-mainline-20261004bc"',
                                              'after': '"-spx-mainline-20261004bf"'}}
    assert complete['config_delta'] == expected_delta
    rows = read(STAGE / 'source-files.json')
    assert len(rows) == 96938 and b.records(STAGE / 'source') == rows
    parent = read(g.X / 'dtb-build/candidate-source-files.json')
    assert read(STAGE / 'parent-be-source-files.json') == parent
    assert set(rows) == set(parent)
    differences = {name for name, row in parent.items() if any(rows[name].get(k) != val for k, val in row.items())}
    assert differences == set(b.DIAGNOSTIC)
    delta = read(STAGE / 'compiled-source-delta.json')
    assert set(delta) == set(b.CHANGED)
    assert {n: r for n, r in delta.items() if n in b.DIAGNOSTIC} == diagnostic['exact_three_source_changes']
    assert rows[b.BOARD]['sha256'] == parent[b.BOARD]['sha256'] == '0edc078ca14ca2818c4c26313baf79d121c6e05cafb1ab93ac68d3a1629f9912'
    source_tar = STAGE / 'source.tar.zst'
    seen = set()
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
        assert proc.wait() == 0
    assert seen == set(rows) and g.sha(source_tar) == complete['source_archive_sha256']
    assert read(STAGE / 'source-tar.json')['sha256'] == g.sha(source_tar)
    print(json.dumps(dict(source_archive_stream_verified=len(seen))), flush=True)
    assert g.sha(STAGE / 'source-files.json') == complete['source_manifest_sha256']
    for name, digest in complete['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest
    config = (STAGE / 'artifacts/.config').read_bytes()
    assert config == (STAGE / 'work-build/.config').read_bytes() == (STAGE / 'config-extracted').read_bytes()
    assert g.sha(STAGE / 'artifacts/.config') == complete['config_sha256']
    assert subprocess.check_output([str(STAGE / 'source/scripts/extract-ikconfig'),
                                    str(STAGE / 'artifacts/arch/arm64/boot/Image')]) == config
    assert gzip.decompress((STAGE / 'vmlinuz').read_bytes()) == (STAGE / 'artifacts/arch/arm64/boot/Image').read_bytes()
    order = (STAGE / 'artifacts/modules.order').read_text().splitlines()
    assert len(order) == len(set(order)) == 202
    vermagic = {}
    for name in order:
        path = STAGE / 'artifacts' / Path(name).with_suffix('.ko')
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).strip()
        assert value.split()[0] == b.RELEASE
        vermagic[str(path.relative_to(STAGE / 'artifacts'))] = value
    venus = STAGE / 'artifacts/drivers/media/platform/qcom/venus/venus-core.ko'
    symbols = subprocess.check_output(['nm', '--defined-only', str(venus)], text=True)
    parsed = {r.split()[-1]: r.split()[-2] for r in symbols.splitlines() if len(r.split()) == 3}
    assert parsed['venus_hfi_startup_diag'] == 'T'
    assert parsed['spx_hfi_startup_diag'] == parsed['spx_hfi_startup_diag_lines'] == 'b'
    assert 'spx_hfi_startup_diag:bool' in subprocess.check_output(['modinfo', '-F', 'parmtype', str(venus)], text=True).splitlines()
    raw = STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    assert raw.read_bytes() == (g.X / 'dtb-build/raw-after.dtb').read_bytes()
    assert g.sha(raw) == '0b86a7f1d18f19f281cf880c5cf5159ff2711116b1f51fe56aa5ad361ecd8928'
    boot_dtb = g.X / 'dtb-build/spx.dtb'
    assert g.sha(boot_dtb) == '2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252'
    spec = importlib.util.spec_from_file_location('provider_contract', HERE / 'video-power-20261003/video_dt_contract.py')
    providers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(providers)
    assert providers.EXPECTED['memory-region'] == [('/reserved-memory/video-firmware', [])]
    providers.EXPECTED['memory-region'] = [('/reserved-memory/video-firmware@8d300000', [])]
    provider_results = dict(raw=providers.validate(raw.read_bytes()),
                           retained=providers.validate(boot_dtb.read_bytes()))
    warnings = []
    for name in ('image-dtb.log', 'modules.log'):
        text = (STAGE / name).read_text()
        assert not any('error:' in line for line in text.splitlines())
        actual = sorted(line.replace(str(STAGE), '<STAGE>') for line in text.splitlines() if 'warning:' in line)
        prior = sorted(line.replace('/var/tmp/spx-mainline-trial-20261004bc', '<STAGE>')
                       for line in (g.X / 'build' / name).read_text().splitlines() if 'warning:' in line)
        assert actual == prior, (name, actual, prior)
        warnings.extend(actual)
    assert len(warnings) == 5
    checked = b.live_source(diagnostic)
    assert not g.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    X.mkdir(mode=0o700)
    target = X / 'build'
    target.mkdir(mode=0o700)
    for path in sorted(STAGE.iterdir()):
        if path.is_file() and not path.is_symlink():
            shutil.copy2(path, target / path.name)
    shutil.copytree(STAGE / 'artifacts', target / 'artifacts')
    shutil.copy2(boot_dtb, target / 'spx.dtb')
    shutil.copy2(__file__, target / Path(__file__).name)
    shutil.copy2(g.X / 'working-recovery.json', X / 'working-recovery.json')
    shutil.copy2(g.X / 'actual-known-good-return/report.json', target / 'parent-actual-return.json')
    shutil.copy2(HERE / 'video-power-20261003/video_dt_contract.py', target / 'video_dt_contract.py')
    (target / 'provider-contracts.json').write_text(json.dumps(provider_results, indent=2) + '\n')
    (target / 'module-vermagic.json').write_text(json.dumps(vermagic, indent=2) + '\n')
    for path in sorted(target.rglob('*')):
        if path.is_file():
            name = str(path.relative_to(target))
            if name == 'spx.dtb':
                assert g.sha(path) == g.sha(boot_dtb)
            elif (STAGE / name).is_file():
                assert g.sha(path) == g.sha(STAGE / name)
    (X / 'build-sha256.json').write_text(json.dumps(g.files(target), indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), release=b.RELEASE, parent_attempt=a['attempt'],
        current_boot_id=b.BOOT, source_archive_stream_verified=True, source_records_verified=len(rows),
        live_compiled_source_paths_verified=checked, full_kernel_linked=True, loadable_modules_linked=True,
        modules=202, all_module_vermagic_exact=True, embedded_config_exact=True,
        config_delta=expected_delta, three_diagnostic_source_changes_relative_be=True,
        exact_three_source_changes=diagnostic['exact_three_source_changes'],
        raw_and_retained_dtb_exact_be=True, provider_contracts_verified=True,
        provider_expected_delta={'memory-region': '/reserved-memory/video-firmware@8d300000'},
        original_static_provider_path_failure_preserved=True,
        venus_diagnostic_capsule_sha256=diagnostic_sha, venus_shared_gate_link_resolved=True,
        venus_parameter_default_zero_verified=True, current_and_parent_config_unchanged=True,
        source_archive_sha256=g.sha(source_tar), source_manifest_sha256=g.sha(STAGE / 'source-files.json'),
        kernel_image_sha256=g.sha(STAGE / 'artifacts/arch/arm64/boot/Image'),
        compressed_kernel_sha256=g.sha(STAGE / 'vmlinuz'), config_sha256=g.sha(STAGE / 'artifacts/.config'),
        raw_dtb_sha256=g.sha(raw), boot_dtb_sha256=g.sha(boot_dtb),
        build_manifest_sha256=g.sha(X / 'build-sha256.json'), build_files=len(g.files(target)),
        compiler_warnings_exact_bc=warnings, known_good_recovery_reverified=True,
        persistent_default='spx-known-good', next_entry_empty=True, early_recovery_validated=False,
        initramfs_assembled=False, module_tree_installed=False, runtime_prepared=False,
        deployed=False, boot_selected=False, hardware_acceptance_closed=False)
    (X / 'build-review.json').write_text(json.dumps(report, indent=2) + '\n')
    os.sync()
    assert g.files(target) == read(X / 'build-sha256.json')
    assert not g.recovery(a).get('next_entry', '')
    print(json.dumps(report | dict(build_review_sha256=g.sha(X / 'build-review.json'))), flush=True)


if __name__ == '__main__':
    main()
