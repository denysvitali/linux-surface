#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve BE's verified runtime and synthetic cases before installation."""
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
import bd_boot_guard as old
sys.path.insert(0, str(SRC))
import be_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004be')
BOOT = '433a78d6-9748-422f-a1a7-aac43c784a7d'


def read(path):
    return json.loads(path.read_text())


def sealed(path, digest):
    assert g.sha(path / 'sha256.json') == digest, path
    assert g.files(path) == read(path / 'sha256.json') | {'sha256.json': digest}, path


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    parent = old.load()
    assert parent['state'].startswith('BD terminal;')
    assert not old.recovery(parent).get('next_entry', '')
    old.artifacts(parent)
    assert not (g.X / 'attempt.json').exists()
    assert not Path('/boot/spx-trial-20261004be').exists()
    archives = {
        'runtime-plan': ('runtime-plan-v1', '7a025961e251507611645adc1085d1e1791a14b96aa065011418ba3735035dd4'),
        'startup-review-preliminary': ('startup-review-offline-v1', 'c440c669b432fdc631546d03272a7ac5c0e9ee485880109c97ae7ee9d6df0d64'),
        'startup-review-offline': ('startup-review-offline-v2', '6f45c52f43817904f27fb6c236a28ede785c9b835d3a732c253c6a73fc39d27d'),
        'result-review-preliminary': ('result-review-offline-v1', '604657f608b7ffe142a7628aceb86ac022ffcec96d7c2ec01bbeb60e0c45f424'),
        'result-review-offline': ('result-review-offline-v2', 'e8358f4a1e550076b084f0ece01bcbe8a527452609e420fdd6657839f5db0e08'),
    }
    for name, digest in archives.values():
        sealed(STAGE / name, digest)
    cases = read(STAGE / 'result-review-offline-v2/report.json')
    assert cases['actual_startup_review_body'] and cases['explicitly_synthetic']
    assert len(cases['accepted']) == 6 and len(cases['rejected']) == 21
    for name in ('result-review-offline-v1', 'result-review-offline-v2'):
        assert g.links(STAGE / name) == read(STAGE / name / 'symlinks.json')
    interpreter = read(STAGE / 'startup-review-offline-v2/report.json')
    assert interpreter['actual_interpreter_positive_cases'] == 7
    assert interpreter['rejected_corruptions'] == 17
    maps = read(STAGE / 'startup-review-offline-v2/memory-maps-review.json')
    plan = STAGE / 'runtime-plan-v1'
    runtime = read(plan / 'result.json')
    assert runtime['helpers'] == 13 and runtime['units'] == 12
    assert runtime['identity_positive_cases'] == 1 and runtime['identity_negative_cases'] == 16
    spec = importlib.util.spec_from_file_location('be_runtime_preparation', plan / 'prepare-be-runtime.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    generation = read(Path('/var/tmp/spx-be-helper-generation-20261004-v2.json'))
    assert generation['helpers'] == 13
    for name in config.HELPERS:
        assert (plan / name).read_bytes() == (SRC / name).read_bytes(), name
        assert (plan / name).read_bytes() == (STAGE / 'helper-replay-v2' / name).read_bytes(), name
        assert g.sha(plan / name) == generation['changes'][name]['sha256']
        ast.parse((plan / name).read_text())
    assert (plan / 'review-be-result.py').read_bytes() == (STAGE / 'result-review-offline-v2/review-be-result.py').read_bytes()
    assert (plan / 'be_startup_review.py').read_bytes() == (STAGE / 'startup-review-offline-v2/be_startup_review.py').read_bytes()
    assert g.source() == 84669
    assert g.files(g.X / 'dtb-build') == read(g.X / 'dtb-sha256.json')
    assert g.files(g.X / 'build') == read(g.X / 'build-sha256.json')
    assert g.links(g.X / 'build') == read(g.X / 'build-symlinks.json')
    assert g.sha(g.X / 'archive-review.json') == '68e0892d9b32fed854359ef3e310a3111554439c3c5eb9a996ab51a2fb3d69d6'
    prep = g.X / 'preparation'
    prep.mkdir(mode=0o700)
    for destination, (origin, digest) in archives.items():
        shutil.copytree(STAGE / origin, prep / destination, symlinks=True)
        sealed(prep / destination, digest)
    shutil.copytree(STAGE / 'helper-replay-v2', prep / 'helper-replay', symlinks=True)
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert g.sha(firmware) == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    shutil.copy2(firmware, prep / 'installed-00042.mbn')
    for version in ('', '-v2'):
        shutil.copy2(f'/var/tmp/spx-be-helper-generation-20261004{version}.json',
                     prep / ('helper-generation' + version + '.json'))
    for name in ('prepare-be-helpers.py', 'freeze-be-runtime.py'):
        shutil.copy2(SRC / name, prep / name)
    write(prep / 'symlinks.json', g.links(prep))
    write(g.X / 'preparation-sha256.json', g.files(prep))
    assert g.files(prep) == read(g.X / 'preparation-sha256.json')
    assert g.links(prep) == read(prep / 'symlinks.json')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not old.recovery(parent).get('next_entry', '')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
        source_paths_checked=84669, helper_files_frozen=13, unit_files_frozen=12,
        identity_positive_cases=runtime['identity_positive_cases'],
        identity_negative_cases=runtime['identity_negative_cases'],
        startup_interpreter_positive_cases=interpreter['actual_interpreter_positive_cases'],
        startup_interpreter_corruptions_rejected=interpreter['rejected_corruptions'],
        memory_map_review=maps,
        actual_startup_reviewer_positive_cases=len(cases['accepted']),
        actual_startup_reviewer_corruptions_rejected=len(cases['rejected']),
        compiled_candidate_archive_review_sha256=g.sha(g.X / 'archive-review.json'),
        preparation_files=len(g.files(prep)), preparation_manifest_sha256=g.sha(g.X / 'preparation-sha256.json'),
        runtime_plan_manifest_sha256=g.sha(prep / 'runtime-plan/sha256.json'),
        media_frame_parser_exact_bc=True, firmware_sha256=g.sha(prep / 'installed-00042.mbn'),
        live_source_config_verified=True, preserved_preliminary_synthetic_cases=True,
        helper_replay_exact=True, installed=False, boot_selected=False,
        hardware_acceptance_closed=False)
    write(g.X / 'independent-runtime-preparation-review.json', report)
    os.sync()
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
