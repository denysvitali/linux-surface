#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve the BF baseline-layout replay and its original fixture failures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

X = g.X.with_name('20261004bf')
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bf')


def read(path):
    return json.loads(path.read_text())


def copy(source, target):
    expected = read(source / 'sha256.json') | {'sha256.json': g.sha(source / 'sha256.json')}
    assert g.files(source) == expected
    shutil.copytree(source, target, symlinks=True)
    assert g.files(target) == expected and g.links(target) == g.links(source)


def main():
    os.umask(0o077)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
    source = STAGE / 'baseline-layout-review-v3'
    report = read(source / 'report.json')
    assert report['full_top_level_baseline_reviewer_executed'] and report['actual_artifact_guard_body_executed']
    assert report['artifact_contract_positive_cases'] == 1 and report['artifact_contract_negative_cases'] == 4
    copy(source, X / 'baseline-layout-review')
    failures = X / 'baseline-layout-failures'
    failures.mkdir(mode=0o700)
    for number, digest in [(1, '0f8c0728a190c88c01d5257ba341321186c692bcd6e1e13853b7d1c8c03568bb'),
                          (2, '8964fd3b1a5fb7e208924e830c970801acdca98053300fa4d70ff9390798bfb3')]:
        source = STAGE / ('baseline-layout-review-v' + str(number))
        assert g.sha(source / 'sha256.json') == digest
        copy(source, failures / source.name)
    shutil.copy2(__file__, X / Path(__file__).name)
    review = dict(utc=datetime.now(timezone.utc).isoformat(), original_baseline_fixture_failures_preserved=2,
        baseline_layout_manifest_sha256=g.sha(X / 'baseline-layout-review/sha256.json'),
        original_preparation_and_reviewed_runtime_unchanged=True, hardware_acceptance_closed=False)
    (X / 'baseline-layout-archive.json').write_text(json.dumps(review, indent=2) + '\n')
    os.sync()
    print(json.dumps(review), flush=True)


if __name__ == '__main__':
    main()
