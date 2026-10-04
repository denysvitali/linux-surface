#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify BF's complete fresh executable and frozen runtime."""
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

import libfdt

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as parent

X = parent.X.with_name('20261004bf')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = parent.load()
    assert a['state'].startswith('BE terminal;') and not parent.recovery(a).get('next_entry', '')
    parent.artifacts(a)
    for path in (X / 'attempt.json', Path('/boot/spx-trial-20261004bf'), Path('/usr/lib/modules') / RELEASE):
        assert not path.exists()
    build, assembly, prep = (X / name for name in ('build', 'assembly', 'preparation-reviewed'))
    constants = {'build-sha256.json': '0faf4fa9c249d139319f5dc1ca7d33cfc9be2825455c9ec7b64b78c22211cf7e',
        'build-review.json': '2b35e937da781140297bf1e927a309409c5c6a9ef13e3b539cf03e166e9dcd81',
        'assembly-sha256.json': 'f4dc5ed76e1fb94b909dc074b629b00efed5de584d968dda1bb1957041450723',
        'assembly-symlinks.json': 'b9b08cc436add8d4d30ec25d1bc966450d5b3d25e63b39c54012c56a2f6b5d0b',
        'assembly-review.json': 'fc93518554c01f5d41308daa057667ef1082cfbd6ced9f4243ebe935bdef1444',
        'preparation-sha256.json': '0971bec8bcfcf5aba6d725420d3a4ef38feff6ac239a145880e53d47cc55b953',
        'preparation-reviewed-sha256.json': 'fd1f4a9020c9f3341fd126c19a421050e121d7fb69287c68ae393d6451cbae18'}
    for name, digest in constants.items(): assert parent.sha(X / name) == digest, name
    assert parent.files(build) == read(X / 'build-sha256.json') and len(parent.files(build)) == 243
    assert parent.files(assembly) == read(X / 'assembly-sha256.json') and len(parent.files(assembly)) == 818
    assert parent.links(assembly) == read(X / 'assembly-symlinks.json') and len(parent.links(assembly)) == 272
    assert parent.files(X / 'preparation') == read(X / 'preparation-sha256.json')
    assert parent.files(prep) == read(X / 'preparation-reviewed-sha256.json') and len(parent.files(prep)) == 9450
    assert parent.links(prep) == read(prep / 'symlinks.json')
    out = X / 'independent-preparation-evidence'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    rows = read(assembly / 'source-files.json')
    original = read(parent.X / 'dtb-build/candidate-source-files.json')
    assert len(rows) == len(original) == 96938 and rows.keys() == original.keys()
    delta = {name for name in rows if rows[name] != original[name]}
    assert delta == {'drivers/media/platform/qcom/venus/hfi_venus.c',
                     'drivers/media/platform/qcom/venus/firmware.c', 'drivers/media/platform/qcom/venus/firmware.h'}
    review = read(X / 'build-review.json')
    for name, values in review['exact_three_source_changes'].items():
        assert rows[name]['sha256'] == values['after_sha256'] and original[name]['sha256'] == values['before_sha256']
    assert parent.sha(assembly / 'source.tar.zst') == review['source_archive_sha256']
    seen = set()
    with subprocess.Popen(['zstd', '-dc', str(assembly / 'source.tar.zst')], stdout=subprocess.PIPE) as process:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir(): continue
                name = entry.name.removeprefix('./')
                assert name in rows and name not in seen
                seen.add(name)
                row = rows[name]
                if entry.issym(): assert row == dict(symlink=entry.linkname)
                else:
                    assert entry.isfile() and entry.mode == row['mode'] and entry.size == row['bytes']
                    stream, digest = archive.extractfile(entry), hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1048576), b''): digest.update(chunk)
                    assert digest.hexdigest() == row['sha256'], name
        assert process.wait() == 0
    assert seen == set(rows)
    checked = 0
    for name, row in rows.items():
        top = Path(name).parts[0]
        if not (top in parent.CODE_DIRS or name in parent.CODE_TOP or name.startswith('localversion') or
                (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'): continue
        path = parent.REPO / name
        if 'sha256' in row: assert parent.sha(path) == row['sha256'], name
        else: assert path.is_symlink() and os.readlink(path) == row['symlink'], name
        checked += 1
    assert checked == 84669
    assert parent.sha(parent.REPO / '.config') == parent.sha(assembly / 'live-config-before')
    print(json.dumps(dict(source_stream_records=len(seen), live_source_paths=checked)), flush=True)
    image = assembly / 'artifacts/arch/arm64/boot/Image'
    config = (assembly / 'config-extracted').read_bytes()
    assert gzip.decompress((assembly / 'vmlinuz').read_bytes()) == image.read_bytes()
    assert subprocess.check_output([str(parent.REPO / 'scripts/extract-ikconfig'), str(image)]) == config
    assert config == (assembly / 'artifacts/.config').read_bytes()
    expected = (parent.X / 'build/config-extracted').read_bytes().replace(
        b'CONFIG_LOCALVERSION="-spx-mainline-20261004bc"', b'CONFIG_LOCALVERSION="-spx-mainline-20261004bf"')
    assert config == expected
    for name, digest in read(assembly / 'build-complete.json')['artifacts'].items():
        assert parent.sha(assembly / 'artifacts' / name) == digest, name
    modules = assembly / 'module-root/lib/modules' / RELEASE
    assert parent.files(modules) == read(assembly / 'module-sha256.json') and len(parent.files(modules)) == 217
    assert parent.links(modules) == read(assembly / 'module-links.json')
    module_count = 0
    for path in sorted(modules.rglob('*.ko')):
        name = str(path.relative_to(modules)).removeprefix('kernel/')
        assert parent.sha(path) == parent.sha(assembly / 'artifacts' / name)
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).split()[0] == RELEASE
        module_count += 1
    assert module_count == 202 and not (assembly / 'depmod.log').read_text().strip()
    alias = read(assembly / 'videocc-alias-resolution.json')
    assert subprocess.check_output(['modprobe', '--resolve-alias', '-d', str(assembly / 'module-root'),
        '-S', RELEASE, alias['modalias']], text=True).splitlines() == ['videocc_sm8150']
    extracted = out / 'initramfs-extracted'
    extracted.mkdir(mode=0o700)
    with (out / 'initramfs-extract.log').open('xb') as log:
        subprocess.run(['lsinitcpio', '-x', str(assembly / 'initramfs.img')], cwd=extracted, stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=120)
    assert parent.files(extracted) == parent.files(assembly / 'initramfs-extracted')
    embedded = sorted(extracted.rglob('*.ko'))
    assert len(embedded) == 55
    for path in embedded:
        name = path.relative_to(extracted / 'usr/lib/modules' / RELEASE)
        assert parent.sha(path) == parent.sha(modules / name)
    assert parent.sha(extracted / 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == parent.sha(assembly / 'logging/initrd-log.sh')
    assert parent.sha(assembly / 'initramfs.img') == '1da8adaa37c03a004c22854ae0a8d905758876773454e7ff99a6436394606286'
    spec = importlib.util.spec_from_file_location('bf_providers', assembly / 'dtb-build/video_dt_contract.py')
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    assert contract.EXPECTED['memory-region'] == [('/reserved-memory/video-firmware', [])]
    contract.EXPECTED['memory-region'] = [('/reserved-memory/video-firmware@8d300000', [])]
    providers = {}
    for label, current, prior in [('raw', assembly / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb', parent.X / 'dtb-build/raw-after.dtb'),
                                 ('retained', assembly / 'dtb-build/spx.dtb', parent.X / 'dtb-build/spx.dtb')]:
        assert current.read_bytes() == prior.read_bytes()
        tree = libfdt.Fdt(current.read_bytes())
        offset = tree.path_offset('/reserved-memory/video-firmware@8d300000')
        assert bytes(tree.getprop(offset, 'reg')) == struct.pack('>4I', 0, 0x8d300000, 0, 0x500000)
        assert bytes(tree.getprop(offset, 'no-map')) == b''
        for name in ('size', 'alignment', 'alloc-ranges', 'reusable'):
            try: tree.getprop(offset, name)
            except libfdt.FdtException as exc: assert exc.err == -libfdt.NOTFOUND
            else: raise AssertionError(name)
        providers[label] = contract.validate(current.read_bytes())
    (out / 'provider-contracts.json').write_text(json.dumps(providers, indent=2) + '\n')
    plan = prep / 'runtime-plan'
    assert parent.sha(plan / 'sha256.json') == 'aae016afde27dbfbb36bbf64e0c65a8314d925b39f0e715bbfb872e78981c88b'
    assert parent.files(plan) == read(plan / 'sha256.json') | {'sha256.json': parent.sha(plan / 'sha256.json')}
    for name, row in read(prep / 'runtime-revision/report.json')['changes'].items():
        assert parent.sha(HERE / name) == parent.sha(plan / name) == row['after_sha256']
    units = sorted(plan.glob('spx-bf-*.service')) + sorted(plan.glob('spx-bf-*.timer'))
    assert len(units) == 12
    result = subprocess.run(['systemd-analyze', 'verify'] + list(map(str, units)), capture_output=True, timeout=60)
    (out / 'unit-verify.stdout').write_bytes(result.stdout)
    (out / 'unit-verify.stderr').write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr.strip()
    subprocess.run(['grub-script-check', str(plan / 'entry.cfg')], check=True, timeout=30)
    cmdline = (plan / 'cmdline').read_text().strip()
    assert cmdline == a['cmdline'].replace('spx_attempt=20261004be', 'spx_attempt=20261004bf') + ' venus_core.spx_hfi_startup_diag=1'
    assert 'linux /spx-trial-20261004bf/vmlinuz ' + cmdline + '; then' in (plan / 'entry.cfg').read_text()
    body = read(prep / 'startup-body-review/report.json')
    assert body['actual_startup_body_executed'] and body['actual_main_wrapper_executed']
    assert len(body['accepted']) == 9 and len(body['rejected']) == 30
    baseline_root = X / 'baseline-layout-review'
    baseline = read(baseline_root / 'report.json')
    assert baseline['full_top_level_baseline_reviewer_executed'] and baseline['actual_artifact_guard_body_executed']
    assert baseline['baseline_collector_other_code_ast_exact_first_bf'] and baseline['physical_predicates_ast_exact_first_bf']
    assert baseline['artifact_contract_positive_cases'] == 1 and baseline['artifact_contract_negative_cases'] == 4
    assert parent.files(baseline_root) == read(baseline_root / 'sha256.json') | {'sha256.json': parent.sha(baseline_root / 'sha256.json')}
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert parent.sha(firmware) == parent.sha(prep / 'installed-00042.mbn') == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    assert parent.sha(X / 'working-recovery.json') == parent.sha(parent.X / 'working-recovery.json')
    assert not parent.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT, release=RELEASE,
        source_archive_stream_verified=True, full_source_records_verified=96938, source_paths_checked=checked,
        exact_three_venus_source_changes_relative_be=True, live_config_exact=True, config_delta_localversion_only=True,
        full_bf_executable_and_initramfs_verified=True, compressed_image_exact=True, embedded_config_exact=True,
        module_count=module_count, module_files_checked=217, embedded_modules_checked=55, all_module_vermagic_exact=True,
        freshly_extracted_initramfs_files_exact=True, initramfs_logger_exact=True, of_alias_resolves=True,
        raw_and_retained_dtb_byte_exact_be=True, static_geometry_and_providers_verified=True,
        build_review_sha256=parent.sha(X / 'build-review.json'), assembly_review_sha256=parent.sha(X / 'assembly-review.json'),
        build_files_checked=243, assembly_files_checked=818, assembly_links_checked=272,
        original_preparation_preserved=True, original_preparation_manifest_sha256=constants['preparation-sha256.json'],
        preparation_files_checked=9450, preparation_manifest_sha256=constants['preparation-reviewed-sha256.json'],
        runtime_plan_manifest_sha256=parent.sha(plan / 'sha256.json'), helpers_checked=14, units_checked=12,
        startup_body_positive_cases=9, startup_body_negative_cases=30, actual_main_wrapper_checked=True,
        baseline_layout_review_manifest_sha256=parent.sha(baseline_root / 'sha256.json'),
        full_baseline_reviewer_and_actual_guard_contract_checked=True, physical_checks_and_delays_unchanged=True,
        firmware_sha256=parent.sha(firmware), known_good_recovery_reverified=True,
        persistent_default='spx-known-good', next_entry_empty=True, efi_bootnext_absent=True,
        installed=False, boot_selected=False, early_recovery_validated=False, hardware_acceptance_closed=False)
    (out / 'sha256.json').write_text(json.dumps(parent.files(out), indent=2) + '\n')
    report['evidence_manifest_sha256'] = parent.sha(out / 'sha256.json')
    destination = X / 'independent-preparation-review.json'
    with destination.open('x') as stream: stream.write(json.dumps(report, indent=2) + '\n')
    os.sync()
    print(json.dumps(report | dict(review_sha256=parent.sha(destination))), flush=True)


if __name__ == '__main__':
    main()
