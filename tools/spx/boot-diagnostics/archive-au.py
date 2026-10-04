#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive and independently rehash AU payload/source provenance; select no boot."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

STAGE = Path('/var/tmp/spx-mainline-trial-20261003au')
DEST = Path('/var/lib/spx-boot-diagnostics/attempts/20261003au')
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
RELEASE = '7.3.0-rc2-spx-mainline-20261003au+'
BOOT = '74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def links(root):
    return {str(p.relative_to(root)): os.readlink(p) for p in sorted(root.rglob('*'))
            if p.is_symlink()}


def verify_tar(root):
    expected = json.loads((root / 'source-files.json').read_text())
    actual = {}
    process = subprocess.Popen(['zstd', '-dc', str(root / 'source.tar.zst')], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                assert entry.name.startswith('source/')
                name = entry.name[len('source/'):]
                assert name in expected and name not in actual, name
                if entry.issym():
                    actual[name] = {'symlink': entry.linkname}
                else:
                    assert entry.isfile(), name
                    digest = hashlib.sha256()
                    stream = archive.extractfile(entry)
                    for block in iter(lambda: stream.read(1048576), b''):
                        digest.update(block)
                    actual[name] = {'sha256': digest.hexdigest(), 'mode': entry.mode & 0o777}
        assert process.wait(timeout=30) == 0
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    assert actual == {name: data for name, data in expected.items() if not data.get('absent')}
    return len(actual)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not DEST.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    import sys
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics'))
    import at_boot_guard
    parent = at_boot_guard.load()
    assert not at_boot_guard.recovery(parent).get('next_entry', '')
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assembled = json.loads((STAGE / 'build-verification.json').read_text())
    assert built['release'] == assembled['release'] == RELEASE
    assert built['source_snapshot_unchanged'] and built['embedded_config_exact']
    assert built['base_dtb_exact_ar'] and built['modules'] == 193
    assert assembled['exact_at_dtb_preserved'] and assembled['embedded_modules'] == 54
    assert not assembled['boot_selected'] and not assembled['deployed']
    assert built['config_delta'] == {'CONFIG_LOCALVERSION': {
        'before': '"-spx-mainline-20261003ar"', 'after': '"-spx-mainline-20261003au"'}}
    for name, digest in built['artifacts'].items():
        assert sha(STAGE / 'artifacts' / name) == digest, name
    for name, digest in assembled['artifacts'].items():
        assert sha(STAGE / name) == digest, name
    assert gzip.decompress((STAGE / 'vmlinuz').read_bytes()) == (STAGE / 'artifacts/arch/arm64/boot/Image').read_bytes()
    for payload in ('vmlinuz', 'artifacts/arch/arm64/boot/Image'):
        config = subprocess.check_output([str(STAGE / 'source/scripts/extract-ikconfig'), str(STAGE / payload)])
        assert config == (STAGE / 'artifacts/.config').read_bytes(), payload
    assert (REPO / '.config').read_bytes() == (STAGE / 'live-config-before').read_bytes()
    frozen = json.loads((STAGE / 'source-files.json').read_text())
    compiled = json.loads((STAGE / 'compiled-source-delta.json').read_text())
    assert set(compiled) == {'drivers/media/i2c/ov13858.c', 'drivers/media/v4l2-core/v4l2-subdev.c',
                            'drivers/media/platform/qcom/camss/camss.c',
                            'drivers/media/platform/qcom/camss/camss-csiphy-3ph-1-0.c'}
    for name in compiled:
        assert sha(REPO / name) == frozen[name]['sha256'], name
    source_count = verify_tar(STAGE)
    print('Full source archive verified:', source_count, 'files/links', flush=True)
    tmp = DEST.with_name(DEST.name + '.new')
    assert not tmp.exists()
    tmp.mkdir(mode=0o700)
    build = tmp / 'build'
    build.mkdir(mode=0o700)
    for path in STAGE.iterdir():
        if path.name in ('source', 'work-build', 'initramfs-extracted'):
            continue
        target = build / path.name
        if path.is_dir():
            shutil.copytree(path, target, symlinks=True)
        else:
            shutil.copy2(path, target)
    root = build / 'module-root/lib/modules' / RELEASE
    assert files(root) == json.loads((build / 'module-sha256.json').read_text())
    assert len(files(root)) == 208
    assert len(list(root.rglob('*.ko'))) == 193
    (tmp / 'build-sha256.json').write_text(json.dumps(files(build), indent=2) + '\n')
    (tmp / 'build-symlinks.json').write_text(json.dumps(links(build), indent=2) + '\n')
    shutil.copy2(at_boot_guard.X / 'working-recovery.json', tmp / 'working-recovery.json')
    gpu = Path('/var/lib/spx-boot-diagnostics/gpu-workloads/20261003au')
    assert sha(gpu / 'sha256.json') == '6994fa099d486ceb63259d3bd52bc2554afe447344c98e02a7db4611e1906ce4'
    hashes = json.loads((gpu / 'sha256.json').read_text())
    assert files(gpu) == hashes | {'sha256.json': sha(gpu / 'sha256.json')}
    (tmp / 'gpu-workload-provenance.json').write_text(json.dumps({
        'archive': str(gpu), 'manifest_sha256': sha(gpu / 'sha256.json'),
        'reference_only': True, 'candidate_run_pending': True}, indent=2) + '\n')
    records = tmp / 'preparation-records'
    records.mkdir(mode=0o700)
    for name in ('build-au.py', 'assemble-au.py', 'archive-au.py',
                 'gpu-workload-20261003/README.md', 'gpu-workload-20261003/collect.py',
                 'gpu-workload-20261003/plan.json', 'gpu-workload-20261003/verify_results.py',
                 'gpu-workload-20261003/archive.py'):
        source = REPO / 'tools/spx/boot-diagnostics' / name
        target = records / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for name in ('PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md', 'AGENTS.md'):
        shutil.copy2(REPO / name, records / name)
    for name, digest in json.loads((tmp / 'build-sha256.json').read_text()).items():
        assert sha(build / name) == digest, name
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not at_boot_guard.recovery(parent).get('next_entry', '')
    report = {'release': RELEASE, 'source_archive_stream_verified': True,
              'source_files_links_verified': source_count,
              'config_delta_exact': True, 'both_payload_configs_exact': True,
              'current_exports_full_build': True, 'module_count': 193,
              'module_tree_files': 208, 'embedded_modules': 54,
              'at_dtb_sha256': sha(build / 'dtb-build/spx.dtb'),
              'build_manifest_sha256': sha(tmp / 'build-sha256.json'),
              'gpu_preparation_manifest_sha256': sha(gpu / 'sha256.json'),
              'preboot_id': BOOT, 'deployed': False, 'boot_selected': False,
              'hardware_acceptance_closed': False}
    (tmp / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = files(tmp)
    (tmp / 'preparation-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    assert files(tmp) == manifest | {'preparation-sha256.json': sha(tmp / 'preparation-sha256.json')}
    os.sync()
    tmp.rename(DEST)
    os.sync()
    print(json.dumps({**report, 'archive': str(DEST), 'files': len(manifest),
                      'preparation_manifest_sha256': sha(DEST / 'preparation-sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
