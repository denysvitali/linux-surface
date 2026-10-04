#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Durably archive BD's reviewed runtime without installing or selecting a boot."""
import ast
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
SRC = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bc_boot_guard as old
sys.path.insert(0, str(SRC))
import bd_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004bd')
BOOT = '78d60cce-ef40-4cea-93e1-42727db4a851'


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
    assert parent['state'].startswith('BC terminal;')
    assert not old.recovery(parent).get('next_entry', '')
    old.artifacts(parent)
    assert not (g.X / 'attempt.json').exists() and not Path('/boot/spx-trial-20261004bd').exists()
    archives = {
        'runtime-plan': ('runtime-plan-v2', '2d07decf54cf92ddee25cd020b3d922f5aaac0db5abcda1ce66a1400611d6842'),
        'runtime-plan-before-preparation-guard': ('runtime-plan-v1', '8bf2aa7e2c282be3e5769bd6e87472c217079aeb937cd2b4ad4c3ae4fe314291'),
        'startup-review-offline-v1-failed': ('startup-review-offline-v1', '2dbce778605b8bc4b0308300b3fee683b101fe46b09a526e08c5cdf14cc9fd51'),
        'startup-review-offline-v2': ('startup-review-offline-v2', '50651e6495838358f27a027f549359f166ff81baf6a02793bbd95996f31c06c8'),
        'result-review-offline': ('result-review-offline-v1', 'f59a777a8be2ece2a58ea3858ccff009562d0ed103f698637b65a0425596f7ee'),
    }
    for name, digest in archives.values():
        sealed(STAGE / name, digest)
    cases = read(STAGE / 'result-review-offline-v1/report.json')
    assert cases['actual_startup_review_body'] and len(cases['accepted']) == 6 and len(cases['rejected']) == 18
    assert g.links(STAGE / 'result-review-offline-v1') == read(STAGE / 'result-review-offline-v1/symlinks.json')
    plan = STAGE / 'runtime-plan-v2'
    spec = importlib.util.spec_from_file_location('bd_runtime_preparation', SRC / 'prepare-bd-runtime.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    for name in config.HELPERS:
        assert (plan / name).read_bytes() == (SRC / name).read_bytes(), name
        ast.parse((plan / name).read_text())
    assert (plan / 'review-bd-result.py').read_bytes() == (STAGE / 'result-review-offline-v1/review-bd-result.py').read_bytes()
    assert (plan / 'bd_startup_review.py').read_bytes() == (STAGE / 'startup-review-offline-v2/bd_startup_review.py').read_bytes()
    subprocess.run(['grub-script-check', str(plan / 'entry.cfg')], check=True, timeout=30)
    assert g.source() == 84669
    assert g.files(g.X / 'dtb-build') == read(g.X / 'dtb-sha256.json')
    assert g.files(g.X / 'build') == read(g.X / 'build-sha256.json')
    assert g.links(g.X / 'build') == read(g.X / 'build-symlinks.json')
    prep = g.X / 'preparation'
    prep.mkdir(mode=0o700)
    for destination, (origin, digest) in archives.items():
        shutil.copytree(STAGE / origin, prep / destination, symlinks=True)
        sealed(prep / destination, digest)
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert g.sha(firmware) == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    shutil.copy2(firmware, prep / 'installed-00042.mbn')
    shutil.copy2('/var/tmp/spx-bd-helper-generation-20261004.json', prep / 'helper-generation.json')
    for name in ('prepare-bd-helpers.py', 'prepare-bd-result-review.py', 'freeze-bd-runtime.py'):
        shutil.copy2(SRC / name, prep / name)
    write(prep / 'symlinks.json', g.links(prep))
    write(g.X / 'preparation-sha256.json', g.files(prep))
    assert g.files(prep) == read(g.X / 'preparation-sha256.json')
    assert g.links(prep) == read(prep / 'symlinks.json')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not old.recovery(parent).get('next_entry', '')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
        source_paths_checked=84669, helper_files_frozen=13, unit_files_frozen=12,
        identity_positive_cases=1, identity_negative_cases=15,
        startup_interpreter_positive_cases=7, startup_interpreter_corruptions_rejected=15,
        actual_startup_reviewer_positive_cases=6, actual_startup_reviewer_corruptions_rejected=18,
        compiled_candidate_archive_review_sha256=g.sha(g.X / 'archive-review.json'),
        preparation_files=len(g.files(prep)), preparation_manifest_sha256=g.sha(g.X / 'preparation-sha256.json'),
        runtime_plan_manifest_sha256=g.sha(prep / 'runtime-plan/sha256.json'),
        media_frame_parser_exact_bc=True, firmware_sha256=g.sha(prep / 'installed-00042.mbn'),
        live_source_config_verified=True, preserved_failed_fixture_generation=True,
        installed=False, boot_selected=False, hardware_acceptance_closed=False)
    write(g.X / 'independent-runtime-preparation-review.json', report)
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
