#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive BF's fresh-build runtime correction without rewriting first evidence."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

HERE = Path(__file__).resolve().parent
X = g.X.with_name('20261004bf')
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bf')


def read(path):
    return json.loads(path.read_text())


def sealed(path, digest):
    assert g.sha(path / 'sha256.json') == digest
    assert g.files(path) == read(path / 'sha256.json') | {'sha256.json': digest}


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
    assert not g.recovery(a).get('next_entry', '')
    original = '0971bec8bcfcf5aba6d725420d3a4ef38feff6ac239a145880e53d47cc55b953'
    assert g.sha(X / 'preparation-sha256.json') == original
    assert g.files(X / 'preparation') == read(X / 'preparation-sha256.json')
    revision, plan, body = (STAGE / n for n in ('runtime-revision-v1', 'runtime-plan-v2', 'startup-body-review-v4'))
    sealed(revision, 'f719e675a48a44ad397f2d159fcfb4c40ad5c7569355f5fd52e18c77dfe159e9')
    sealed(plan, 'aae016afde27dbfbb36bbf64e0c65a8314d925b39f0e715bbfb872e78981c88b')
    sealed(body, '73b70332d9ff435b05f22d526955ba1a5acb9b0db8e260d04c99997e39d4b472')
    report = read(body / 'report.json')
    assert report['actual_startup_body_executed'] and report['actual_main_wrapper_executed']
    assert len(report['accepted']) == 9 and len(report['rejected']) == 30
    changes = read(revision / 'report.json')['changes']
    assert len(changes) == 14
    assert {n for n, row in changes.items() if row['changed']} == {
        'bf_boot_guard.py', 'bf-baseline.py', 'review-bf-baseline.py', 'review-bf-result.py', 'bf-reboot-check.py'}
    for name, row in changes.items():
        assert g.sha(HERE / name) == g.sha(plan / name) == g.sha(revision / name) == row['after_sha256']
    failures = X / 'runtime-review-failures'
    failures.mkdir(mode=0o700)
    failure_hashes = {}
    for number, digest in [(1, '7a6baa3ec02512266ca6f38a1dad105fe4b4e2e1418c3c400a5f1fc89068646b'),
                          (2, '36508a51b61b58a3dfaee5b1838b202999c46c3cc095e573385994ed55dc5a30'),
                          (3, 'dd5aea71a27814311db94a0838b51707cade9ecb5cae9c6c6f65e7e44844cb8a')]:
        source = STAGE / ('startup-body-review-v' + str(number))
        sealed(source, digest)
        target = failures / source.name
        shutil.copytree(source, target, symlinks=True)
        sealed(target, digest)
        failure_hashes[source.name] = digest
    (failures / 'sha256.json').write_text(json.dumps(g.files(failures), indent=2) + '\n')
    (X / 'runtime-review-failures-sha256.json').write_text(json.dumps(g.files(failures), indent=2) + '\n')
    prep = X / 'preparation-reviewed'
    shutil.copytree(X / 'preparation', prep, symlinks=True)
    shutil.rmtree(prep / 'runtime-plan')
    shutil.copytree(plan, prep / 'runtime-plan', symlinks=True)
    shutil.copytree(revision, prep / 'runtime-revision', symlinks=True)
    shutil.copytree(body, prep / 'startup-body-review', symlinks=True)
    for name in ('freeze-bf-reviewed-runtime.py', 'revise-bf-runtime.py', 'verify-bf-result-review.py'):
        shutil.copy2(HERE / name, prep / name)
    (prep / 'preserved-failures.json').write_text(json.dumps(dict(path=str(failures),
        manifests=failure_hashes, namespace_and_transport_fixture_corrections_only=True), indent=2) + '\n')
    (prep / 'symlinks.json').write_text(json.dumps(g.links(prep), indent=2) + '\n')
    (X / 'preparation-reviewed-sha256.json').write_text(json.dumps(g.files(prep), indent=2) + '\n')
    result = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=bid,
        original_preparation_manifest_sha256=original, original_preparation_preserved=True,
        runtime_plan_manifest_sha256=g.sha(prep / 'runtime-plan/sha256.json'),
        preparation_manifest_sha256=g.sha(X / 'preparation-reviewed-sha256.json'),
        startup_body_manifest_sha256=g.sha(prep / 'startup-body-review/sha256.json'),
        helpers=14, units=12, changed_helpers=list(n for n, row in changes.items() if row['changed']),
        startup_body_positive_cases=9, startup_body_negative_cases=30, actual_main_wrapper_executed=True,
        physical_checks_and_timing_unchanged=True, kernel_modules_initramfs_dtb_unchanged=True,
        failures_preserved=failure_hashes, preparation_files=len(g.files(prep)),
        baseline_body_and_artifact_contract_review_pending=True,
        independent_full_preparation_review_pending=True, installed=False, boot_selected=False,
        hardware_acceptance_closed=False)
    (X / 'reviewed-runtime-freeze.json').write_text(json.dumps(result, indent=2) + '\n')
    os.sync()
    assert g.files(prep) == read(X / 'preparation-reviewed-sha256.json')
    assert g.links(prep) == read(prep / 'symlinks.json')
    assert g.files(X / 'preparation') == read(X / 'preparation-sha256.json')
    assert not g.recovery(a).get('next_entry', '')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
