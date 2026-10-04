#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify and archive BB's full PAS diagnostic candidate."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ba_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004bb')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bb')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bb+'
BOOT = 'a824008e-cf43-4287-84f8-4e930fa41a06'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
CHANGED = {'drivers/firmware/qcom/qcom_scm.c',
           'drivers/firmware/qcom/qcom_scm-smc.c',
           'drivers/firmware/qcom/qcom_scm.h'}


def read(path):
    return json.loads(path.read_text())


def capsule(path, digest=None):
    actual = g.sha(path / 'sha256.json')
    if digest:
        assert actual == digest, path
    assert g.files(path) == read(path / 'sha256.json') | {'sha256.json': actual}, path
    return actual


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert a['state'] == 'BA terminal; guarded return verified'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    returned = g.X / 'return-review'
    capsule(returned, 'f1324030e2dc1361bae3565ce416e1d65fb1d875a02947131393347d1eefd3e0')
    assert read(returned / 'report.json')['returned_boot_id'] == BOOT
    diag = g.X / 'offline-pas-diag-20261004'
    diagnostic_sha = capsule(diag, '2ef2de5057329f649216ed2a418493f5ea02758f90cffd3ae10560253528e9c2')
    assert len(read(diag / 'sha256.json')) == 192
    diagnostic = read(diag / 'report.json')
    assert diagnostic['native_actual_body_checks'] == 91
    assert diagnostic['native_before_after_cases'] == 80
    assert diagnostic['rejected_candidate_controls'] == 5
    assert read(STAGE / 'compiled-source-delta.json') == diagnostic['exact_three_source_changes']
    source = read(STAGE / 'source-files.json')
    original = read(g.X / 'build/source-files.json')
    assert set(source) == set(original) and len(source) == 96938
    assert {name for name in source if source[name] != original[name]} == CHANGED
    for name, row in source.items():
        path = STAGE / 'source' / name
        if 'sha256' in row:
            assert not path.is_symlink() and g.sha(path) == row['sha256'], name
            assert path.stat().st_size == row['bytes'], name
            assert stat.S_IMODE(path.stat().st_mode) == row['mode'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
    seen = set()
    with subprocess.Popen(['zstd', '-dc', str(STAGE / 'source.tar.zst')], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                name = entry.name.removeprefix('./')
                assert name not in seen and name in source, name
                seen.add(name)
                row = source[name]
                if entry.issym():
                    assert row == dict(symlink=entry.linkname), name
                else:
                    assert entry.isfile() and entry.size == row['bytes'] and entry.mode == row['mode'], name
                    digest = hashlib.sha256()
                    data = archive.extractfile(entry)
                    for chunk in iter(lambda: data.read(1048576), b''):
                        digest.update(chunk)
                    assert digest.hexdigest() == row['sha256'], name
        assert proc.wait() == 0
    assert seen == set(source)
    assert read(STAGE / 'source-tar.json')['sha256'] == g.sha(STAGE / 'source.tar.zst')
    built, assembled = read(STAGE / 'build-complete.json'), read(STAGE / 'build-verification.json')
    assert built['release'] == assembled['release'] == RELEASE
    assert built['modules'] == assembled['modules'] == 202
    assert built['full_kernel_linked'] and built['loadable_modules_linked'] and built['embedded_config_exact']
    assert built['pas_diagnostic_capsule_sha256'] == diagnostic_sha
    assert assembled['module_tree_files'] == 217 and assembled['embedded_modules'] == 55
    assert assembled['embedded_module_payloads_exact'] and assembled['private_logger_exact']
    assert assembled['actual_of_fallback_alias_resolves'] and assembled['boot_dtb_exact_parent_ba']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    for name, digest in assembled['artifacts'].items():
        assert g.sha(STAGE / name) == digest, name
    symbols = subprocess.check_output(['nm', '--defined-only', str(STAGE / 'artifacts/vmlinux')], text=True)
    parsed_symbols = {row.split()[-1]: row.split()[-2] for row in symbols.splitlines() if len(row.split()) == 3}
    assert parsed_symbols['qcom_scm_spx_pas_diag'] == 'T'
    assert parsed_symbols['spx_pas_diag'] == 'b'
    assert b'qcom_scm.spx_pas_diag\0' in (STAGE / 'artifacts/vmlinux').read_bytes()
    raw_name = 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    assert (STAGE / raw_name).read_bytes() == (g.X / 'build' / raw_name).read_bytes()
    assert (STAGE / 'dtb-build/spx.dtb').read_bytes() == (g.X / 'build/dtb-build/spx.dtb').read_bytes()
    assert g.sha(STAGE / 'dtb-build/spx.dtb') == '4d96be24498f39afc10db917d7be155ee4b0d8314bfdfec924ddf1131594f4a9'
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics/video-power-20261003'))
    from video_dt_contract import validate
    validate((STAGE / 'dtb-build/spx.dtb').read_bytes())
    validate((STAGE / raw_name).read_bytes())
    assert assembled['provider_argument_counts_and_interconnect_tags_verified']
    warnings = []
    for name in ('image-dtb.log', 'modules.log'):
        lines = (STAGE / name).read_text().splitlines()
        assert not any('error:' in line for line in lines)
        actual = sorted(line.replace(str(STAGE), '<STAGE>') for line in lines if 'warning:' in line)
        prior = sorted(line.replace('/var/tmp/spx-mainline-trial-20261004ba', '<STAGE>')
                       for line in (g.X / 'build' / name).read_text().splitlines() if 'warning:' in line)
        assert actual == prior, (name, actual, prior)
        warnings.extend(actual)
    assert len(warnings) == 5
    assert (REPO / '.config').read_bytes() == (STAGE / 'live-config-before').read_bytes()
    for name in CHANGED | {'arch/arm64/boot/dts/qcom/sc8180x.dtsi', 'arch/arm64/configs/spx.config'}:
        assert g.sha(REPO / name) == source[name]['sha256'], name
    plan = STAGE / 'runtime-plan'
    runtime_sha = capsule(plan)
    runtime = read(plan / 'result.json')
    assert runtime['helpers_parsed'] == 15 and runtime['units_verified'] == 12
    assert runtime['identity_positive_cases'] == 1 and runtime['identity_negative_cases'] == 11
    assert runtime['pas_diagnostic_selector'] == 'qcom_scm.spx_pas_diag=1'
    assert runtime['media_reference_pairs'] == 2 and runtime['media_negative_controls'] == 7
    log_review = STAGE / 'pas-log-review'
    log_review_sha = capsule(log_review, '2363d93696bff7aa44ace64f0889e7e530aa7c3aaa3c49075c58000928eb2f2e')
    log_result = read(log_review / 'report.json')
    assert log_result['synthetic_positive_traces'] == 52
    assert len(log_result['rejected_corrupt_traces']) == 14
    assert log_result['production_source_sha256'] == {
        name: row['after_sha256'] for name, row in diagnostic['exact_three_source_changes'].items()}
    X.mkdir(mode=0o700)
    build = X / 'build'
    shutil.copytree(STAGE, build, symlinks=True,
                    ignore=lambda path, names: {'source', 'work-build'} if Path(path) == STAGE else set())
    modules = build / 'module-root/lib/modules' / RELEASE
    assert g.files(modules) == read(build / 'module-sha256.json')
    assert len(g.files(modules)) == 217
    (build / 'module-links.json').write_text(json.dumps(g.links(modules), indent=2) + '\n')
    preparation = X / 'preparation'
    preparation.mkdir(mode=0o700)
    shutil.copytree(g.X / 'preparation', preparation / 'parent-ba', symlinks=True)
    assert g.files(preparation / 'parent-ba') == read(g.X / 'preparation-sha256.json')
    for name in ('return-review', 'terminal-records', 'terminal-document-reconciliation',
                 'pas-failure-provenance', 'offline-pas-diag-20261004',
                 'offline-pas-diag-document-records', 'recovery-touch-at-return',
                 'retired-az-boot-slot'):
        parent_capsule = g.X / name
        capsule(parent_capsule)
        shutil.copytree(parent_capsule, preparation / ('parent-ba-' + name))
        assert g.files(preparation / ('parent-ba-' + name)) == g.files(parent_capsule)
    helpers = preparation / 'helpers'
    helpers.mkdir()
    for name in ('build-bb.py', 'assemble-bb.py', 'archive-bb.py', 'prepare-bb-helpers.py',
                 'review-bb-runtime-plan.py', 'retire-az-for-bb.py'):
        shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, helpers / name)
    for name in ('LOCAL-PROGRESS.md', 'PORT-CHECKLIST.md'):
        shutil.copy2(REPO / name, preparation / name)
    for name in ('RESULT-20261004ba.md', 'review-ba-result.py', 'PREPARED-20261004bb.md'):
        shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, preparation / name)
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert g.sha(firmware) == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    shutil.copy2(firmware, preparation / 'installed-00042.mbn')
    shutil.copy2(g.X / 'working-recovery.json', X / 'working-recovery.json')
    for name, content in (('build-sha256.json', g.files(build)),
                          ('build-symlinks.json', g.links(build)),
                          ('preparation-sha256.json', g.files(preparation))):
        (X / name).write_text(json.dumps(content, indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), release=RELEASE, boot_id=BOOT,
                  source_files_verified=len(source), source_archive_stream_verified=True,
                  source_delta_files=3, full_kernel_and_modules_linked=True,
                  embedded_config_exact=True, module_count=202, module_tree_files=217,
                  private_initramfs_verified=True, embedded_modules=55,
                  videocc_provider_module_verified=True, actual_of_fallback_alias_resolves=True,
                  boot_dtb_exact_parent_ba=True, raw_compiled_board_dtb_exact_parent_ba=True,
                  provider_argument_counts_and_interconnect_tags_verified=True,
                  pas_diagnostic_native_checks=91, pas_diagnostic_native_comparisons=80,
                  pas_diagnostic_negative_controls=5, pas_diagnostic_capsule_sha256=diagnostic_sha,
                  pas_gate_and_parameter_in_full_kernel=True, pas_flag_linked_in_zero_initialized_bss=True,
                  pas_log_reviewer_positive_traces=52, pas_log_reviewer_negative_controls=14,
                  pas_log_reviewer_manifest_sha256=log_review_sha,
                  warnings_exact_parent_ba=warnings, runtime_plan_manifest_sha256=runtime_sha,
                  native_hardware_operations=0, parent_attempt='20261004ba',
                  parent_return_manifest_sha256=g.sha(returned / 'sha256.json'),
                  build_files=len(g.files(build)), build_links=len(g.links(build)),
                  preparation_files=len(g.files(preparation)),
                  build_manifest_sha256=g.sha(X / 'build-sha256.json'),
                  preparation_manifest_sha256=g.sha(X / 'preparation-sha256.json'),
                  recovery_definition_sha256=g.sha(X / 'working-recovery.json'),
                  installed=False, boot_selected=False, hardware_acceptance_closed=False)
    (X / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
    assert g.files(build) == read(X / 'build-sha256.json')
    assert g.links(build) == read(X / 'build-symlinks.json')
    assert g.files(preparation) == read(X / 'preparation-sha256.json')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
