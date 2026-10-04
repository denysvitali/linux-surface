#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze the complete isolated AQ source and verified private boot payloads."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
SRC = REPO / 'tools/spx/boot-diagnostics'
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
PARENT = BASE / '20261002ap'
X = BASE / '20261003aq'
STAGE = Path('/var/tmp/spx-mainline-trial-20261003aq')
RELEASE = '7.3.0-rc2-spx-mainline-20261003aq+'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not X.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
        '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'
    verification = json.loads((STAGE / 'build-verification.json').read_text())
    build = json.loads((STAGE / 'build-complete.json').read_text())
    assert verification['release'] == build['release'] == RELEASE
    assert verification['provider_only_dtb_delta_verified'] and verification['embedded_module_payloads_exact']
    assert build['source_snapshot_unchanged'] and build['embedded_config_exact']
    for name, digest in verification['artifacts'].items():
        assert sha(STAGE / name) == digest
    assert gzip.decompress((STAGE / 'vmlinuz').read_bytes()) == (STAGE / 'artifacts/arch/arm64/boot/Image').read_bytes()
    source_files = json.loads((STAGE / 'source-files.json').read_text())
    for name, record in source_files.items():
        path = STAGE / 'source' / name
        if 'sha256' in record:
            assert sha(path) == record['sha256'], name
        elif 'symlink' in record:
            assert path.is_symlink() and os.readlink(path) == record['symlink'], name
        else:
            assert not path.exists(), name
    before = set((STAGE / 'config-before').read_text().splitlines())
    after = set((STAGE / 'artifacts/.config').read_text().splitlines())
    assert before - after == {'CONFIG_LOCALVERSION="-spx-mainline-20261001am"'}
    assert after - before == {'CONFIG_LOCALVERSION="-spx-mainline-20261003aq"'}
    assert (REPO / '.config').read_bytes() == (STAGE / 'config-before').read_bytes()
    modules = json.loads((STAGE / 'module-sha256.json').read_text())
    assert files(STAGE / 'module-root/lib/modules' / RELEASE) == modules and len(modules) == 202
    sys.path.insert(0, str(SRC))
    import ap_boot_guard
    parent = ap_boot_guard.load()
    ap_boot_guard.recovery(parent)
    ap_boot_guard.artifacts(parent)
    # Full source archive includes untracked board/port inputs, not just a git patch.
    archive = STAGE / 'source.tar.zst'
    assert not archive.exists()
    with (STAGE / 'source-archive.log').open('wb') as log:
        subprocess.run(['tar', '-I', 'zstd -T2 -3', '-cf', str(archive),
                        '-C', str(STAGE), 'source'], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    X.mkdir(mode=0o700)
    shutil.copytree(STAGE, X / 'build', symlinks=True,
                    ignore=shutil.ignore_patterns('source', 'work-build'))
    shutil.copytree(STAGE / 'dtb-build', X / 'dtb-build')
    shutil.copy2(PARENT / 'working-recovery.json', X / 'working-recovery.json')
    source_review = X / 'source-review'
    source_review.mkdir()
    for name in ('build-aq.py', 'assemble-aq.py', 'archive-aq.py'):
        shutil.copy2(SRC / name, source_review / name)
    for name in ('AGENTS.md', 'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md'):
        shutil.copy2(REPO / name, source_review / name)
    for name in ('camera-power-c01-20261003', 'camera-regulator-c01-20261003',
                 'camera-pmic-metadata-20261003', 'output-bounds-candidate-20261002'):
        manifest = PARENT / name / 'sha256.json'
        shutil.copy2(manifest, source_review / (name + '-manifest.json'))
    built_files = files(X / 'build')
    links = {str(p.relative_to(X / 'build')): os.readlink(p)
             for p in sorted((X / 'build').rglob('*')) if p.is_symlink()}
    for name, content in [('build-sha256.json', built_files), ('build-symlinks.json', links),
                          ('dtb-sha256.json', files(X / 'dtb-build')),
                          ('source-review-sha256.json', files(source_review))]:
        (X / name).write_text(json.dumps(content, indent=2) + '\n')
    assert files(X / 'build') == built_files
    assert files(X / 'dtb-build') == json.loads((X / 'dtb-sha256.json').read_text())
    report = {'attempt': '20261003aq', 'release': RELEASE,
              'preboot_id': '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f',
              'checklist_ids': ['C01', 'I02', 'I03'],
              'build_files_verified': len(built_files), 'build_symlinks_verified': len(links),
              'source_snapshot_files_verified': len(source_files),
              'full_source_archive_sha256': sha(X / 'build/source.tar.zst'),
              'build_manifest_sha256': sha(X / 'build-sha256.json'),
              'build_symlink_manifest_sha256': sha(X / 'build-symlinks.json'),
              'config_sha256': sha(X / 'build/artifacts/.config'),
              'live_config_unchanged': True, 'config_delta_localversion_only': True,
              'boot_payload_sha256': verification['artifacts'],
              'module_files_verified': 202, 'module_vermagic_records_verified': 187,
              'provider_only_dtb_delta_verified': True,
              'functional_delta': 'Reviewed touch output bounds and standard camera SPMI provider; '
                  'rear supply/CCI changes retained in source with sensors disabled.',
              'camera_consumers_present': False, 'hardware_acceptance_closed': False,
              'boot_selected': False, 'deployed': False}
    (X / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
