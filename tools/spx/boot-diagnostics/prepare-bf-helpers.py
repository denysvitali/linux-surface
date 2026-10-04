#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive fresh-executable BF helpers from immutable BE runtime inputs."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261004be/preparation/runtime-plan')
NAMES = ('be_boot_guard.py', 'be-video.py', 'be-return.py', 'be-baseline.py',
         'be-camera-provider.py', 'be-camera-control.py', 'be_camera_core.py',
         'review-be-baseline.py', 'be-media.py', 'be-media-run.py',
         'be-reboot-check.py', 'be_startup_review.py', 'review-be-result.py')

ARTIFACTS = '''def artifacts(a):
    for path, digest in (a['sha256'] | a['runtime_sha256']).items():
        assert sha(path) == digest, path
    assert sha(X / 'preparation-sha256.json') == a['preparation_manifest_sha256']
    assert files(X / 'preparation') == json.loads((X / 'preparation-sha256.json').read_text())
    plan = X / 'preparation/runtime-plan'
    assert sha(plan / 'sha256.json') == a['runtime_plan_manifest_sha256']
    assert files(plan) == json.loads((plan / 'sha256.json').read_text()) | {'sha256.json': sha(plan / 'sha256.json')}
    assert sha(X / 'build-sha256.json') == a['build_manifest_sha256']
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert sha(X / 'build-review.json') == a['build_review_sha256']
    assert sha(X / 'assembly-sha256.json') == a['assembly_manifest_sha256']
    assert files(X / 'assembly') == json.loads((X / 'assembly-sha256.json').read_text())
    assert sha(X / 'assembly-symlinks.json') == a['assembly_symlinks_sha256']
    assert links(X / 'assembly') == json.loads((X / 'assembly-symlinks.json').read_text())
    assert sha(X / 'assembly-review.json') == a['assembly_review_sha256']
    report = json.loads((X / 'assembly-review.json').read_text())
    assert report['module_count'] == 202 and report['embedded_modules'] == 55
    assert report['all_staged_module_bytes_exact_compiled'] and report['embedded_module_payloads_exact']
    assert report['raw_and_retained_dtb_exact_be'] and report['original_build_archive_unchanged']
    built = json.loads((X / 'build-review.json').read_text())
    assert built['source_records_verified'] == 96938 and built['source_archive_stream_verified']
    assert built['three_diagnostic_source_changes_relative_be'] and built['provider_contracts_verified']
    assert built['venus_shared_gate_link_resolved'] and built['venus_parameter_default_zero_verified']
    assert sha(X / 'assembly/source.tar.zst') == built['source_archive_sha256']
    assert sha(X / 'assembly/source-files.json') == built['source_manifest_sha256']
    module_rows = json.loads((X / 'assembly/module-sha256.json').read_text())
    assert len(module_rows) == 217 and files(Path('/usr/lib/modules') / RELEASE) == module_rows
    assert links(Path('/usr/lib/modules') / RELEASE) == json.loads((X / 'assembly/module-links.json').read_text())
    assert Path('/boot/grub/custom.cfg').read_bytes() == (X / 'entry.cfg').read_bytes()
    assert sha(X / 'independent-preparation-review.json') == a['independent_preparation_review_sha256']
    independent = json.loads((X / 'independent-preparation-review.json').read_text())
    assert independent['source_archive_stream_verified'] and independent['source_paths_checked'] == 84669
    assert independent['full_bf_executable_and_initramfs_verified']
    assert independent['assembly_review_sha256'] == sha(X / 'assembly-review.json')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=SRC)
    out = parser.parse_args().out
    if out != SRC:
        out.mkdir(mode=0o700)
    manifest = json.loads((PARENT / 'sha256.json').read_text())
    assert hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest() == '7a025961e251507611645adc1085d1e1791a14b96aa065011418ba3735035dd4'
    outputs, changes = {}, {}
    for name in NAMES:
        origin = PARENT / name
        assert hashlib.sha256(origin.read_bytes()).hexdigest() == manifest[name]
        text = origin.read_text().replace('20261004be', '20261004bf').replace('20261004bc', '20261004bf')
        text = text.replace('433a78d6-9748-422f-a1a7-aac43c784a7d', 'c1cea488-ecf7-403e-9581-127ff365fb1e')
        text = re.sub(r'\bbe(?=[-_.])', 'bf', text).replace('BE', 'BF')
        target = re.sub(r'\bbe(?=[-_.])', 'bf', name)
        if target == 'bf_boot_guard.py':
            start, end = text.index('def artifacts(a):'), text.index('\n\ndef source():')
            text = text[:start] + ARTIFACTS.rstrip() + text[end:]
            text = text.replace("X / 'dtb-build/candidate-source-files.json'", "X / 'assembly/source-files.json'")
            text = text.replace("X / 'dtb-build/live-config-before'", "X / 'assembly/live-config-before'")
            start = text.index("    expected = json.loads((X / 'dt-input-files-sha256.json')")
            end = text.index('    return checked', start)
            text = text[:start] + text[end:]
            marker = "    assert a['entry'] == 'spx-trial-20261004bf'\n"
            assert text.count(marker) == 1
            text = text.replace(marker, marker + "    for flag in ('qcom_scm.spx_pas_diag=1', 'qcom_scm.spx_pas_area_diag=1', 'venus_core.spx_hfi_startup_diag=1'):\n        assert a['cmdline'].split().count(flag) == 1\n")
        if target == 'bf-video.py':
            marker = "    result = dict(utc=datetime.now(timezone.utc).isoformat(), attempt=a['attempt'], boot_id=boot,\n"
            assert text.count(marker) == 1
            text = text.replace(marker, '''    venus_parameter = dict(observed=False)
    path = Path('/sys/module/venus_core/parameters/spx_hfi_startup_diag')
    try:
        venus_parameter = dict(observed=True, value=path.read_text().strip(), mode=oct(path.stat().st_mode & 0o777))
    except OSError as error:
        venus_parameter['error'] = str(error)
    (root / 'venus-parameter.json').write_text(json.dumps(venus_parameter, indent=2) + '\\n')
''' + marker)
            text = text.replace('pas_parameters=parameters, memory_area_result_uninterpreted=True,',
                                'pas_parameters=parameters, venus_startup_parameter=venus_parameter, memory_area_result_uninterpreted=True,')
        if target == 'bf_startup_review.py':
            text = text.replace('import re\n', 'import re\nfrom bf_venus_startup import parse as parse_venus\n', 1)
            marker = "    devices = startup['platform_devices']\n"
            assert text.count(marker) == 1
            text = text.replace(marker, '''    venus = parse_venus(kernel)
    parameter = startup['venus_startup_parameter']
    assert isinstance(parameter, dict) and isinstance(parameter.get('observed'), bool)
    if parameter['observed']:
        assert parameter == dict(observed=True, value='Y', mode='0o400')
    else:
        assert parameter.get('error') and not venus['records']
    venus['parameter_witness'] = parameter
''' + marker)
            text = text.replace('return dict(firmware_reservation=reservation,', 'return dict(venus_startup=venus, firmware_reservation=reservation,')
        if target == 'review-bf-result.py':
            text = text.replace("X / 'dtb-build/video_dt_contract.py'", "X / 'assembly/dtb-build/video_dt_contract.py'")
            text = text.replace("X / 'build/pas-area-log-review'", "X / 'preparation/pas-area-log-review'")
            text = text.replace("X / 'dtb-build/candidate-source-files.json'", "X / 'assembly/source-files.json'")
            text = text.replace("X / 'build/config-extracted'", "X / 'assembly/config-extracted'")
            text = text.replace("'drivers/firmware/qcom/qcom_pas.c', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):",
                                "'drivers/firmware/qcom/qcom_pas.c', 'drivers/media/platform/qcom/venus/hfi_venus.c',\n                 'drivers/media/platform/qcom/venus/firmware.h', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):")
            text = text.replace("for name in ('bf_startup_review.py',):", "for name in ('bf_startup_review.py', 'bf_venus_startup.py'):")
            marker = "    witness = read(X / 'video-startup/pas-parameters.json')\n"
            text = text.replace(marker, "    assert read(X / 'video-startup/venus-parameter.json') == result['venus_startup_parameter']\n" + marker)
        ast.parse(text)
        assert not (out / target).exists(), target
        outputs[target] = text
        changes[target] = dict(parent_name=name, parent_sha256=manifest[name],
            exact_except_identity=target not in ('bf_boot_guard.py', 'bf-video.py', 'bf_startup_review.py', 'review-bf-result.py'))
    outputs['bf_venus_startup.py'] = (SRC / 'bf_venus_startup.py').read_text()
    ast.parse(outputs['bf_venus_startup.py'])
    assert not (out / 'bf_venus_startup.py').exists() or out == SRC
    for name, text in outputs.items():
        if name == 'bf_venus_startup.py' and out == SRC:
            pass
        else:
            (out / name).write_text(text)
        changes.setdefault(name, dict(new_observation_parser=True))['sha256'] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    print(json.dumps(dict(helpers=len(outputs), release='7.3.0-rc2-spx-mainline-20261004bf+',
        expected_kernel_image='BOOT_IMAGE=/spx-trial-20261004bf/vmlinuz', changes=changes,
        parent_runtime_manifest_sha256=hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest(),
        installed=False, boot_selected=False), indent=2))


if __name__ == '__main__':
    main()
