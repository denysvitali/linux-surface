#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal the verified diagnostic, failure provenance, and native/AArch64 proof."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('startup_verify', HERE / 'verify.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
g = v.g
WORK = Path('/var/tmp/spx-venus-startup-diag-20261004')


def sealed(root, recursive=True):
    digest = g.sha(root / 'sha256.json')
    actual = g.files(root) if recursive else {p.name: g.sha(p) for p in root.iterdir() if p.is_file()}
    assert actual == v.read(root / 'sha256.json') | {'sha256.json': digest}
    return digest


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
    assert not g.recovery(a).get('next_entry', '')
    assert sealed(g.X / 'actual-known-good-return') == '7b4809519672db379d9c3622dd942656da1b5d304caa94f91d805664403a66ca'
    failure = sealed(WORK / 'native-v1')
    assert failure == '204970b7f83f8e123ce4d95518408a272ce770867d1550223154d9d18d55c205'
    native = sealed(WORK / 'native-v2')
    assert native == '761a8949c20e7e2e2e779d217e39237dfcd21b7dea5e5290d4b9ac7130d3919a'
    compiled = sealed(WORK / 'aarch64', False)
    n = v.read(WORK / 'native-v2/report.json')
    c = v.read(WORK / 'aarch64/report.json')
    assert c['native_manifest_sha256'] == native
    assert c['actual_kbuild_aarch64_constituent_objects'] == 14
    assert c['internal_diagnostic_gate_link_resolved'] and c['private_and_live_config_unchanged']
    assert c['exact_three_source_changes'] == n['exact_three_source_changes']
    assert c['config_sha256'] == '86f046b08693c74b5e270b93c9fbc9c05850652aaa613a5bde2d172fb644bbe0'
    for result in n['native_actual_body_results']:
        assert result['shared_log_limit'] == result['concurrent_accepted'] == 32
        assert result['concurrent_calls'] == 16000
    assert sum(r['hfi_comparisons'] + r['firmware_comparisons'] for r in n['native_actual_body_results']) == 79296
    assert len(n['rejected_candidate_controls']) == 6
    rows = v.read(g.X / 'dtb-build/candidate-source-files.json')
    checked = v.live(rows, n['exact_three_source_changes'])
    root = g.X / 'offline-venus-startup-diag-20261004'
    root.mkdir(mode=0o700)
    for name in ('verify.py', 'build_venus.py', 'review_compile.py', 'archive_diag.py', 'native.h', 'checks.h', 'README.md'):
        shutil.copy2(HERE / name, root / name)
    shutil.copytree(WORK / 'native-v1', root / 'native-v1')
    shutil.copytree(WORK / 'native-v2', root / 'native-v2')
    target = root / 'aarch64'
    target.mkdir(mode=0o700)
    for name in v.read(WORK / 'aarch64/sha256.json'):
        shutil.copy2(WORK / 'aarch64' / name, target / name)
    shutil.copy2(WORK / 'aarch64/sha256.json', target / 'sha256.json')
    assert sealed(root / 'native-v1') == failure
    assert sealed(root / 'native-v2') == native
    assert sealed(target) == compiled
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), parent_attempt=a['attempt'],
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        parent_terminal_return_manifest_sha256='7b4809519672db379d9c3622dd942656da1b5d304caa94f91d805664403a66ca',
        native_manifest_sha256=native, original_failed_control_manifest_sha256=failure,
        aarch64_manifest_sha256=compiled, native_before_after_comparisons=79296,
        rejected_candidate_controls=6, concurrent_calls_per_config=16000,
        shared_diagnostic_line_limit=32, default_off_read_only_iris1=True,
        actual_kbuild_aarch64_constituent_objects=14, relocatable_link_verified=True,
        compiled_source_paths_verified=checked, private_source_records_verified=96938,
        exact_three_source_changes=n['exact_three_source_changes'],
        live_and_private_config_unchanged=True, insertion_only_scope=True,
        known_good_recovery_reverified=True, persistent_default='spx-known-good',
        next_entry_empty=True, early_recovery_validated=False,
        full_kernel_linked=False, deployed=False, boot_selected=False,
        hardware_acceptance_closed=False, limits=n['limits'])
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = g.files(root)
    (root / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    os.sync()
    assert sealed(root) == g.sha(root / 'sha256.json')
    print(json.dumps(dict(files=len(manifest), manifest_sha256=g.sha(root / 'sha256.json'), report=report)), flush=True)


if __name__ == '__main__':
    main()
