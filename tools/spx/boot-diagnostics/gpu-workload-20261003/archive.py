#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze reviewed GPU workload provenance, failures and bounded reference results."""
import hashlib
import json
import os
from pathlib import Path
import shutil

TEMP = Path('/var/tmp/spx-gpu-benchmark-20261003')
DEST = Path('/var/lib/spx-boot-diagnostics/gpu-workloads/20261003au')
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not DEST.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
        '74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b'
    result = json.loads((TEMP / 'reference-smoke-v5/progress.json').read_text())
    review = json.loads((TEMP / 'reference-review-v2/report.json').read_text())
    assert result['reference_smoke'] and result['scoped_passed']
    assert review['recomputed_runs'] == 10 and review['successful_image_checks'] == 60
    assert review['successful_timed_scene_rows'] == 30
    assert len(review['software_or_false_result_cases_rejected']) == 8
    assert len(review['positive_fault_signatures_detected']) == 9
    provenance = json.loads((TEMP / 'toolchain-provenance.json').read_text())
    assert provenance['commit']['output'].strip() == '42e3d8fe3aa88743ef90348138f643f7b04a9237'
    assert not provenance['source_status']['output'].strip()
    assert 'Good signature' in (TEMP / 'package-verification.log').read_text()
    stage = DEST.with_name(DEST.name + '.new')
    assert not stage.exists()
    stage.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage.mkdir(mode=0o700)
    for name in ('fixture', 'packages', 'upstream-2023.01', 'conditionals-review',
                 'reference-smoke', 'reference-smoke-v2', 'reference-smoke-v3',
                 'reference-smoke-v4', 'reference-smoke-v5', 'reference-review',
                 'reference-review-v2'):
        shutil.copytree(TEMP / name, stage / name, symlinks=True)
    shutil.copytree(TEMP / 'source', stage / 'source', ignore=shutil.ignore_patterns('.git'))
    for path in TEMP.iterdir():
        if path.is_file():
            shutil.copy2(path, stage / path.name)
    orchestration = stage / 'orchestration'
    orchestration.mkdir(mode=0o700)
    for path in HERE.iterdir():
        if path.is_file():
            shutil.copy2(path, orchestration / path.name)
    build = stage / 'build-provenance'
    build.mkdir(mode=0o700)
    for name in ('build.ninja', 'compile_commands.json', 'meson-info/intro-buildoptions.json',
                 'meson-info/intro-dependencies.json', 'meson-info/intro-targets.json',
                 'meson-logs/meson-log.txt'):
        path = TEMP / 'build' / name
        if path.exists():
            target = build / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copy2(path, target)
    # Recheck every reference manifest after copying, including failed runs.
    for root in stage.glob('reference-*'):
        if not root.is_dir():
            continue
        manifest = root / 'sha256.json'
        assert manifest.is_file(), root
        expected = json.loads(manifest.read_text())
        assert files(root) == expected | {'sha256.json': sha(manifest)}, root
    fixture = json.loads((stage / 'fixture/sha256.json').read_text())
    assert files(stage / 'fixture') == fixture | {'sha256.json': sha(stage / 'fixture/sha256.json')}
    hashes = files(stage)
    (stage / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    assert files(stage) == hashes | {'sha256.json': sha(stage / 'sha256.json')}
    os.sync()
    stage.rename(DEST)
    os.sync()
    print(json.dumps({'archive': str(DEST), 'files': len(hashes),
                      'manifest_sha256': sha(DEST / 'sha256.json'),
                      'hardware_acceptance_closed': False}, indent=2))


if __name__ == '__main__':
    main()
