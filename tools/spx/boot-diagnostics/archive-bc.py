#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify and archive BC's full PIL area-query candidate."""
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
import bb_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004bc')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bc')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bc+'
BOOT = 'e00a2d25-03f7-4265-b56e-0eac05b234d3'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
CHANGED = {'drivers/firmware/qcom/qcom_scm.c',
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
    assert a['state'] == 'BB terminal; scoped baseline and guarded return verified; PAS memory setup raw SCM error unresolved'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    returned = g.X / 'return-review'
    capsule(returned, 'a3e8476226a06d9ea452fe958b9fb73b61d03171c82287e77bc7df8d56a9cdaa')
    assert read(returned / 'report.json')['returned_boot_id'] == BOOT
    diag = g.X / 'offline-pas-area-diag-20261004'
    diagnostic_sha = capsule(diag, '5c48431dd13217778361fa211e717413c5efd7738e29b3daabef7f7780be6404')
    assert len(read(diag / 'sha256.json')) == 403
    diagnostic = read(diag / 'report.json')
    assert diagnostic['native_actual_body_checks'] == 436
    assert diagnostic['native_before_after_cases'] == 416
    assert diagnostic['rejected_candidate_controls'] == 9
    assert read(STAGE / 'compiled-source-delta.json') == diagnostic['exact_two_source_changes']
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
    assert built['diagnostic_flags_default_zero_verified'] and built['both_diagnostic_parameter_namespaces_verified']
    assert assembled['module_tree_files'] == 217 and assembled['embedded_modules'] == 55
    assert assembled['embedded_module_payloads_exact'] and assembled['private_logger_exact']
    assert assembled['actual_of_fallback_alias_resolves'] and assembled['boot_dtb_exact_parent_bb']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    for name, digest in assembled['artifacts'].items():
        assert g.sha(STAGE / name) == digest, name
    symbols = subprocess.check_output(['nm', '--defined-only', str(STAGE / 'artifacts/vmlinux')], text=True)
    parsed_symbols = {row.split()[-1]: row.split()[-2] for row in symbols.splitlines() if len(row.split()) == 3}
    assert parsed_symbols['qcom_scm_spx_pas_diag'] == 'T'
    for parameter in ('spx_pas_diag', 'spx_pas_area_diag'):
        assert parsed_symbols[parameter] == 'b'
        assert ('qcom_scm.' + parameter + '\0').encode() in (STAGE / 'artifacts/vmlinux').read_bytes()
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
        prior = sorted(line.replace('/var/tmp/spx-mainline-trial-20261004bb', '<STAGE>')
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
    assert runtime['identity_positive_cases'] == 1 and runtime['identity_negative_cases'] == 14
    assert runtime['pas_diagnostic_selector'] == 'qcom_scm.spx_pas_diag=1'
    assert runtime['media_reference_pairs'] == 2 and runtime['media_negative_controls'] == 7
    assert runtime['area_query_selector'] == 'qcom_scm.spx_pas_area_diag=1'
    log_review = STAGE / 'pas-area-log-review'
    shutil.copytree(diag / 'log-v1', log_review)
    log_review_sha = capsule(log_review, 'c9b5432d841c0cc5270786dc14d3eb3260215f81fbd0f29690131ba536b5e8d7')
    log_result = read(log_review / 'report.json')
    assert log_result['bb_positive_traces_replayed'] == 52
    assert log_result['synthetic_area_traces'] == 17
    assert len(log_result['corrupt_traces_rejected']) == 33
    result_review = STAGE / 'result-review-offline'
    result_review_sha = capsule(result_review, '75aa6784feae55b1afa57c74b37e49531aaa9ce14b183cd942bacf4fc8613e4d')
    result_review_report = read(result_review / 'report.json')
    assert result_review_report['synthetic_positive_cases'] == ['ok', 'unknown-a0', 'leaf']
    assert len(result_review_report['corrupt_cases_rejected']) == 5
    assert result_review_report['startup_reviewer_sha256'] == g.sha(REPO / 'tools/spx/boot-diagnostics/review-bc-result.py')
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
    shutil.copytree(g.X / 'preparation', preparation / 'parent-bb', symlinks=True)
    assert g.files(preparation / 'parent-bb') == read(g.X / 'preparation-sha256.json')
    for name in ('return-review', 'terminal-records', 'post-status-documentation',
                 'returned-recovery-state', 'actual-handoff-records',
                 'offline-pas-status-20261004', 'offline-pas-memarea-20261004',
                 'offline-pas-area-diag-20261004', 'post-area-documentation',
                 'retired-ba-boot-slot-for-bc'):
        parent_capsule = g.X / name
        capsule(parent_capsule)
        shutil.copytree(parent_capsule, preparation / ('parent-bb-' + name))
        assert g.files(preparation / ('parent-bb-' + name)) == g.files(parent_capsule)
    helpers = preparation / 'helpers'
    helpers.mkdir()
    for name in ('build-bc.py', 'assemble-bc.py', 'archive-bc.py', 'prepare-bc-helpers.py',
                 'review-bc-runtime-plan.py', 'prepare-bc-runtime.py', 'retire-ba-for-bc.py',
                 'review-bc-result.py', 'verify-bc-result-review.py', 'complete-bc-build-record.py'):
        shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, helpers / name)
    for name in ('LOCAL-PROGRESS.md', 'PORT-CHECKLIST.md'):
        shutil.copy2(REPO / name, preparation / name)
    for name in ('RESULT-20261004bb.md', 'review-bb-result.py', 'PREPARED-20261004bc.md'):
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
                  source_delta_files=2, full_kernel_and_modules_linked=True,
                  embedded_config_exact=True, module_count=202, module_tree_files=217,
                  private_initramfs_verified=True, embedded_modules=55,
                  videocc_provider_module_verified=True, actual_of_fallback_alias_resolves=True,
                  boot_dtb_exact_parent_bb=True, raw_compiled_board_dtb_exact_parent_bb=True,
                  provider_argument_counts_and_interconnect_tags_verified=True,
                  pas_diagnostic_native_checks=436, pas_diagnostic_native_comparisons=416,
                  pas_diagnostic_negative_controls=9, pas_diagnostic_capsule_sha256=diagnostic_sha,
                  pas_gate_and_parameter_in_full_kernel=True, pas_flag_linked_in_zero_initialized_bss=True,
                  pas_area_query_parameter_in_full_kernel=True, both_pas_flags_zero_initialized=True,
                  pas_area_raw_result_words_uninterpreted=True,
                  pas_log_reviewer_positive_traces=69, pas_log_reviewer_negative_controls=33,
                  pas_log_reviewer_manifest_sha256=log_review_sha,
                  actual_startup_review_body_positive_cases=3,
                  actual_startup_review_body_negative_cases=5,
                  startup_review_synthetic_manifest_sha256=result_review_sha,
                  warnings_exact_parent_bb=warnings, runtime_plan_manifest_sha256=runtime_sha,
                  native_hardware_operations=0, parent_attempt='20261004bb',
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
