#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reverify BC's linked artifacts and complete its failed metadata-only finalizer."""
from datetime import datetime, timezone
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bc_builder', ROOT / 'build-bc.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
g = b.g


def main():
    assert os.geteuid() == 0
    stage, source, output = b.STAGE, b.STAGE / 'source', b.STAGE / 'work-build'
    assert not (stage / 'build-complete.json').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    a = g.load()
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    proof = stage / 'metadata-finalizer-review'
    proof.mkdir(mode=0o700)
    shutil.copy2(__file__, proof / Path(__file__).name)
    shutil.copy2(ROOT / 'build-bc.py', proof / 'corrected-build-bc.py')
    failure = stage / 'failed-build-finalizer'
    expected_failure = json.loads((failure / 'sha256.json').read_text())
    assert g.files(failure) == expected_failure | {'sha256.json': g.sha(failure / 'sha256.json')}
    commands = json.loads((stage / 'commands.json').read_text())
    assert [r['label'] for r in commands] == ['snapshot', 'source-archive', 'output-clone',
                'config-set', 'olddefconfig', 'prepare', 'image-dtb', 'modules']
    assert all(r['exit_code'] == 0 for r in commands)
    prepared = json.loads((stage / 'prepared.json').read_text())
    assert prepared['release'] == b.RELEASE
    final = json.loads((stage / 'source-files.json').read_text())
    assert b.records(source) == final and len(final) == 96938
    before, after = b.states(stage / 'config-parent'), b.states(output / '.config')
    delta = {k: dict(before=before.get(k, 'n'), after=after.get(k, 'n'))
             for k in set(before) | set(after) if before.get(k, 'n') != after.get(k, 'n')}
    assert delta == prepared['config_delta'] == {
        'CONFIG_LOCALVERSION': dict(before='"-spx-mainline-20261004bb"', after='"-spx-mainline-20261004bc"')}
    artifacts = stage / 'artifacts'
    config = (output / '.config').read_bytes()
    assert (artifacts / '.config').read_bytes() == (stage / 'config-extracted').read_bytes() == config
    assert g.sha(output / '.config') == prepared['config_sha256']
    assert subprocess.check_output([str(source / 'scripts/extract-ikconfig'),
                                    str(artifacts / 'arch/arm64/boot/Image')]) == config
    assert gzip.decompress((stage / 'vmlinuz').read_bytes()) == (artifacts / 'arch/arm64/boot/Image').read_bytes()
    order = (output / 'modules.order').read_text().splitlines()
    assert order == (b.PARENT / 'work-build/modules.order').read_text().splitlines() and len(order) == 202
    modules = [str(Path(name).with_suffix('.ko')) for name in order]
    names = ['.config', 'System.map', 'vmlinux', 'Module.symvers', 'modules.order',
             'arch/arm64/boot/Image', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']
    for name in names + modules:
        assert g.sha(artifacts / name) == g.sha(output / name), name
    raw_dtb = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    assert (artifacts / raw_dtb).read_bytes() == (b.PARENT / 'artifacts' / raw_dtb).read_bytes()
    symbols = subprocess.check_output(['nm', '--defined-only', str(artifacts / 'vmlinux')], text=True)
    (proof / 'symbols.txt').write_text(symbols)
    parsed = {row.split()[-1]: row.split()[-2] for row in symbols.splitlines() if len(row.split()) == 3}
    assert parsed['qcom_scm_spx_pas_diag'] == 'T'
    for parameter in ('spx_pas_diag', 'spx_pas_area_diag'):
        assert parsed[parameter] == 'b'
        assert ('qcom_scm.' + parameter + '\0').encode() in (artifacts / 'vmlinux').read_bytes()
    capsule = g.X / 'offline-pas-area-diag-20261004'
    diagnostic = json.loads((capsule / 'report.json').read_text())
    checked = b.live_source(diagnostic)
    assert (b.REPO / '.config').read_bytes() == (stage / 'live-config-before').read_bytes()
    assert g.sha(b.PARENT / 'work-build/.config') == g.sha(stage / 'config-parent')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    assert not g.recovery(a).get('next_entry', '')
    result = prepared | dict(utc_complete=datetime.now(timezone.utc).isoformat(), modules=len(modules),
        added_modules=[], source_snapshot_unchanged=True, live_config_unchanged=True,
        parent_config_unchanged=True, embedded_config_exact=True,
        artifacts={name: g.sha(artifacts / name) for name in names + modules},
        full_kernel_linked=True, loadable_modules_linked=True, live_compiled_source_paths_verified=checked,
        boot_dtb_exact_parent_bb=True, diagnostic_flags_default_zero_verified=True,
        both_diagnostic_parameter_namespaces_verified=True, deployed=False,
        hardware_operations=0, hardware_acceptance_closed=False,
        pas_diagnostic_capsule_sha256=g.sha(capsule / 'sha256.json'),
        metadata_finalizer_failure_preserved=True, artifacts_independently_reverified=True)
    with (stage / 'build-complete.json').open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    (proof / 'report.json').write_text(json.dumps(dict(utc=result['utc_complete'],
        source_records_verified=len(final), live_source_paths_verified=checked, modules=202,
        compilation_repeated=False, metadata_only_finalizer_completed=True,
        failure_manifest_sha256=g.sha(failure / 'sha256.json'),
        build_complete_sha256=g.sha(stage / 'build-complete.json'),
        full_image_and_modules_linked=True, known_good_recovery_verified=True,
        boot_selected=False, hardware_acceptance_closed=False), indent=2) + '\n')
    (proof / 'sha256.json').write_text(json.dumps(g.files(proof), indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(release=b.RELEASE, modules=202,
        image_sha256=g.sha(artifacts / 'arch/arm64/boot/Image'),
        build_complete_sha256=g.sha(stage / 'build-complete.json'),
        finalizer_manifest_sha256=g.sha(proof / 'sha256.json')), indent=2), flush=True)


if __name__ == '__main__':
    main()
