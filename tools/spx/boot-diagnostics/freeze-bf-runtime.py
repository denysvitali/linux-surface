#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze BF runtime, parser proofs and dependencies before independent review."""
import ast
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
SRC = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as old
spec = importlib.util.spec_from_file_location('bf_build', SRC / 'build-bf.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
spec = importlib.util.spec_from_file_location('bf_runtime', SRC / 'prepare-bf-runtime.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
X = old.BASE / 'attempts/20261004bf'
STAGE = b.STAGE


def read(path):
    return json.loads(path.read_text())


def sealed(path, digest):
    assert old.sha(path / 'sha256.json') == digest
    assert old.files(path) == read(path / 'sha256.json') | {'sha256.json': digest}


def main():
    os.umask(0o077)
    a = old.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    assert not old.recovery(a).get('next_entry', '')
    old.artifacts(a)
    assert not (X / 'attempt.json').exists() and not Path('/boot/spx-trial-20261004bf').exists()
    assert old.sha(X / 'assembly-sha256.json') == 'f4dc5ed76e1fb94b909dc074b629b00efed5de584d968dda1bb1957041450723'
    assert old.files(X / 'assembly') == read(X / 'assembly-sha256.json')
    assert old.links(X / 'assembly') == read(X / 'assembly-symlinks.json')
    assert old.sha(X / 'assembly-review.json') == 'fc93518554c01f5d41308daa057667ef1082cfbd6ced9f4243ebe935bdef1444'
    plan = STAGE / 'runtime-plan-v1'
    plan_sha = '4f2fd603627a52dc649191403712c54eeee57245c6731ce8b9939f2f751b211f'
    log_sha = 'be62318b12377b2b25c14244c2d4b5a213e88628e8067e0505e25f92bda366bf'
    failed_sha = '1292f559a06bede5c4106ba5661c65b8abbf8c2111af026146c95344fe73fa5a'
    sealed(plan, plan_sha)
    sealed(STAGE / 'venus-log-review-v2', log_sha)
    sealed(STAGE / 'venus-log-review-v1', failed_sha)
    runtime = read(plan / 'result.json')
    assert runtime['helpers'] == 14 and runtime['units'] == 12
    assert runtime['identity_positive_cases'] == 1 and runtime['identity_negative_cases'] == 19
    assert runtime['fresh_bf_executable_paths'] and runtime['media_ordered_after_video']
    assert runtime['timer_seconds'] == {name: value[1] for name, value in config.ACTIONS.items()}
    log = read(STAGE / 'venus-log-review-v2/report.json')
    assert log['native_actual_body_records'] == 4 and len(log['positive_traces']) == 12
    assert len(log['rejected_corruptions']) == 15 and log['actual_be_replayed_with_zero_new_observations']
    assert log['interpreter_positive_cases'] == 2 and len(log['rejected_parameter_witnesses']) == 3
    generation = read(Path('/var/tmp/spx-bf-helper-generation-20261004-v1.json'))
    replay = read(Path('/var/tmp/spx-bf-helper-replay-20261004-v1.json'))
    assert generation == replay and generation['helpers'] == 14
    for name in config.HELPERS:
        assert old.sha(plan / name) == generation['changes'][name]['sha256']
        assert (plan / name).read_bytes() == (SRC / name).read_bytes() == (STAGE / 'helper-replay-v1' / name).read_bytes()
        ast.parse((plan / name).read_text())
    assert (plan / 'bf_startup_review.py').read_bytes() == (STAGE / 'venus-log-review-v2/bf_startup_review.py').read_bytes()
    assert (plan / 'bf_venus_startup.py').read_bytes() == (STAGE / 'venus-log-review-v2/bf_venus_startup.py').read_bytes()
    parent_parser = old.X / 'build/pas-area-log-review'
    parent_parser_sha = old.sha(parent_parser / 'sha256.json')
    sealed(parent_parser, parent_parser_sha)
    assert parent_parser_sha == 'c9b5432d841c0cc5270786dc14d3eb3260215f81fbd0f29690131ba536b5e8d7'
    diagnostic = read(old.X / 'offline-venus-startup-diag-20261004/report.json')
    assert b.live_source(diagnostic) == 84669
    assert b.records(STAGE / 'source') == read(STAGE / 'source-files.json')
    prep = X / 'preparation'
    prep.mkdir(mode=0o700)
    for source, name in [(plan, 'runtime-plan'), (STAGE / 'venus-log-review-v2', 'venus-log-review'),
                         (STAGE / 'venus-log-review-v1', 'venus-log-review-preliminary'),
                         (STAGE / 'helper-replay-v1', 'helper-replay'), (parent_parser, 'pas-area-log-review')]:
        shutil.copytree(source, prep / name, symlinks=True)
        assert old.files(prep / name) == old.files(source)
    for source, name in [(Path('/var/tmp/spx-bf-helper-generation-20261004-v1.json'), 'helper-generation.json'),
                         (Path('/var/tmp/spx-bf-helper-replay-20261004-v1.json'), 'helper-replay.json'),
                         (STAGE / 'prepare-bf-runtime-before-parent-import.py', 'prepare-bf-runtime-before-parent-import.py')]:
        shutil.copy2(source, prep / name)
    (prep / 'runtime-parent-import-failure.json').write_text(json.dumps(dict(
        failure='Identity transform changed the producer parent import to BF before BF attempt metadata exists.',
        corrected_parent='Frozen terminal BE, then fresh BF runtime identities.',
        failed_before_writing_runtime_plan=True, kernel_and_assembly_unchanged=True), indent=2) + '\n')
    for name in ('prepare-bf-helpers.py', 'prepare-bf-runtime.py', 'freeze-bf-runtime.py', 'verify-bf-venus-startup.py',
                 'assemble-bf.py', 'archive-bf-assembly.py', 'PREPARED-20261004bf.md'):
        shutil.copy2(SRC / name, prep / name)
    for name in ('PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md'):
        shutil.copy2(b.REPO / name, prep / name)
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert old.sha(firmware) == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    shutil.copy2(firmware, prep / 'installed-00042.mbn')
    (prep / 'symlinks.json').write_text(json.dumps(old.links(prep), indent=2) + '\n')
    (X / 'preparation-sha256.json').write_text(json.dumps(old.files(prep), indent=2) + '\n')
    assert not old.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    report = dict(utc=datetime.now(timezone.utc).isoformat(), current_boot_id=b.BOOT,
        helper_files_frozen=14, unit_files_frozen=12, identity_positive_cases=1, identity_negative_cases=19,
        timer_seconds=runtime['timer_seconds'], media_ordered_after_video=True,
        frame_parser_exact_be_and_fixtures_verified=True, helper_replay_exact=True,
        new_venus_actual_body_log_records=4, venus_positive_traces=12, venus_corruptions_rejected=15,
        interpreter_positive_cases=2, interpreter_parameter_corruptions_rejected=3,
        actual_be_replay_preserves_unobserved_values=True, original_fixture_and_parent_import_failures_preserved=True,
        compiled_source_paths_verified=84669, full_private_source_records_verified=96938,
        assembly_review_sha256=old.sha(X / 'assembly-review.json'),
        runtime_plan_manifest_sha256=plan_sha, venus_log_manifest_sha256=log_sha,
        pas_area_parser_manifest_sha256=parent_parser_sha,
        preparation_files=len(old.files(prep)), preparation_manifest_sha256=old.sha(X / 'preparation-sha256.json'),
        independent_full_startup_body_review_pending=True, independent_preparation_review_pending=True,
        installed=False, boot_selected=False, hardware_acceptance_closed=False)
    (X / 'runtime-preparation-review.json').write_text(json.dumps(report, indent=2) + '\n')
    os.sync()
    assert old.files(prep) == read(X / 'preparation-sha256.json')
    assert old.links(prep) == read(prep / 'symlinks.json')
    print(json.dumps(report | dict(review_sha256=old.sha(X / 'runtime-preparation-review.json'))), flush=True)


if __name__ == '__main__':
    main()
