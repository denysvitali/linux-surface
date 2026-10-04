#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adapt BC's archive/return review shell to BD's bounded allocation outcome body."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent
STARTUP = '''
def startup(out, a):
    import importlib.util
    import struct
    import libfdt
    from bd_startup_review import analyze
    result = read(X / 'video-startup/result.json')
    assert result['attempt'] == a['attempt'] == '20261004bd'
    assert result['release'] == a['release']
    assert result['boot_id'] != a['preboot_id'] and 60 <= result['uptime_start'] < 240
    assert result['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz'] + a['cmdline'].split()
    assert result['kernel_taint'] == '0'
    assert len(result['platform_devices']) == 1
    provider = result['clock_provider_devices']
    assert len(provider) == 1 and provider[0]['driver'] == '/sys/bus/platform/drivers/video_cc-sm8150'
    tree = libfdt.Fdt((X / 'video-startup/actual-fdt.dtb').read_bytes())
    offset = tree.path_offset('/reserved-memory/video-firmware')
    assert bytes(tree.getprop(offset, 'alloc-ranges')) == struct.pack('>4I', 0, 0x8b700000, 0, 0x0f400000)
    assert bytes(tree.getprop(offset, 'size')) == struct.pack('>2I', 0, 0x500000)
    assert bytes(tree.getprop(offset, 'alignment')) == struct.pack('>2I', 0, 0x100000)
    assert bytes(tree.getprop(offset, 'no-map')) == b''
    contract_path = X / 'dtb-build/video_dt_contract.py'
    spec = importlib.util.spec_from_file_location('bd_dt_contract', contract_path)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    references = contract.validate((X / 'video-startup/actual-fdt.dtb').read_bytes())
    (out / 'actual-provider-contracts.json').write_text(json.dumps(references, indent=2) + '\\n')
    diagnostic = X / 'build/pas-area-log-review'
    sealed(diagnostic)
    for name in ('parse_log.py', 'parse_pas.py'):
        shutil.copy2(diagnostic / name, out / name)
    sys.path.insert(0, str(diagnostic))
    spec = importlib.util.spec_from_file_location('bd_pas_parser', diagnostic / 'parse_log.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    kernel = (X / 'video-startup/kernel.stdout').read_text()
    decoded = parser.parse(kernel)
    report = analyze(result, kernel, decoded)
    (out / 'decoded-pas.json').write_text(json.dumps(decoded, indent=2) + '\\n')
    witness = read(X / 'video-startup/pas-parameters.json')
    assert witness == result['pas_parameters']
    assert witness == {name: dict(value='Y', mode='0o400') for name in ('spx_pas_diag', 'spx_pas_area_diag')}
    if os.uname().release == a['release']:
        for name, expected in witness.items():
            path = Path('/sys/module/qcom_scm/parameters') / name
            assert dict(value=path.read_text().strip(), mode=oct(path.stat().st_mode & 0o777)) == expected
    rows = read(X / 'dtb-build/candidate-source-files.json')
    for name in ('drivers/soc/qcom/mdt_loader.c', 'drivers/media/platform/qcom/venus/firmware.c',
                 'drivers/media/platform/qcom/venus/core.c', 'drivers/firmware/qcom/qcom_scm.c',
                 'drivers/firmware/qcom/qcom_scm-smc.c', 'drivers/firmware/qcom/qcom_scm.h',
                 'drivers/firmware/qcom/qcom_pas.c', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):
        source = Path('/home/dvitali/Documents/git/linux-surface-next') / name
        assert sha(source) == rows[name]['sha256']
        shutil.copy2(source, out / source.name)
    shutil.copy2(X / 'build/config-extracted', out / 'candidate.config')
    for name in ('bd_startup_review.py',):
        source = RUNTIME / name
        assert sha(source) == a['runtime_sha256'][str(source)]
        shutil.copy2(source, out / name)
    assert 'could not get #interconnect-cells' not in kernel
    report.update(boot_id=result['boot_id'], release=result['release'], startup=sealed(X / 'video-startup'),
                  provider=sealed(X / 'camera-provider-result'), initial_camera=sealed(X / 'camera-control-result'),
                  actual_provider_declared_argument_contracts_verified=True,
                  pil_reply_layout_correlated_from_retained_vendor_and_primary_interface=True,
                  original_interconnect_parse_failure_absent=True)
    skipped = X / 'media-not-run.json'
    media = X / 'media-short-result'
    if skipped.exists():
        data = read(skipped)
        assert data['boot_id'] == result['boot_id'] and data['hardware_codec_used'] is False
        assert data['video_startup_sha256'] == sha(X / 'video-startup/result.json')
        shutil.copy2(skipped, out / skipped.name)
        report['media_phase'] = 'not run: normal nodes unavailable'
    elif (media / 'result.json').exists() and (media / 'sha256.json').exists():
        data = read(media / 'result.json')
        assert data['boot_id'] == result['boot_id'] and data['release'] == a['release']
        report['media_phase'] = 'completed'
        report['media_short_result'] = sealed(media)
        report['media_short_producer_scoped_passed'] = bool(data.get('scoped_passed'))
        report['media_independent_functional_review_pending'] = True
        shutil.copy2(media / 'result.json', out / 'media-short-producer-result.json')
    else:
        report['media_phase'] = 'pending or failed before a sealed result'
    return report
'''


def main():
    origin = SRC / 'review-bc-result.py'
    text = origin.read_text().replace('20261004bc', '20261004bd').replace('bc_boot_guard', 'bd_boot_guard')
    text = text.replace('review-bc-baseline.py', 'review-bd-baseline.py')
    text = text.replace('spx-bc-fallback.service', 'spx-bd-fallback.service')
    tree = ast.parse(text)
    body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'startup')
    lines = text.splitlines(True)
    text = ''.join(lines[:body.lineno-1]) + STARTUP.strip() + '\n' + ''.join(lines[body.end_lineno:])
    text = text.replace("X / 'build/runtime-plan/review-bd-baseline.py'", "X / 'preparation/runtime-plan/review-bd-baseline.py'")
    text = text.replace("archive['build_files']", "archive['build_files_verified']")
    text = text.replace("archive['build_links']", "archive['build_links_verified']")
    text = text.replace("archive['preparation_files']", "len(files(X / 'preparation'))")
    ast.parse(text)
    destination = SRC / 'review-bd-result.py'
    assert not destination.exists()
    destination.write_text(text)
    print('Created BD allocation-aware startup and guarded-return reviewer.')


if __name__ == '__main__':
    main()
