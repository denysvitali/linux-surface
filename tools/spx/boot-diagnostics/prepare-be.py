#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive BE's static video reservation and exact BC executable artifact reuse."""
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
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004be')
DEST = g.BASE / 'attempts/20261004be'
BOOT = '433a78d6-9748-422f-a1a7-aac43c784a7d'
BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'
ALLOCATION = g.X / 'offline-video-static-reservation'


def read(path):
    return json.loads(path.read_text())


def sealed(root, expected_digest=None):
    if expected_digest:
        assert g.sha(root / 'sha256.json') == expected_digest, root
    assert g.files(root) == read(root / 'sha256.json') | {'sha256.json': g.sha(root / 'sha256.json')}, root


def records(root):
    result = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink():
            result[name] = dict(symlink=os.readlink(path))
        elif path.is_file():
            result[name] = dict(sha256=g.sha(path), bytes=path.stat().st_size,
                                mode=stat.S_IMODE(path.stat().st_mode))
    return result


def stream_verify(archive, expected):
    seen = set()
    with subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as stream:
            for entry in stream:
                if entry.isdir():
                    continue
                name = entry.name.removeprefix('./')
                assert name not in seen and name in expected, name
                seen.add(name)
                row = expected[name]
                if entry.issym():
                    assert row == dict(symlink=entry.linkname), name
                else:
                    assert entry.isfile() and entry.size == row['bytes'] and entry.mode == row['mode'], name
                    h = hashlib.sha256()
                    data = stream.extractfile(entry)
                    for chunk in iter(lambda: data.read(1048576), b''):
                        h.update(chunk)
                    assert h.hexdigest() == row['sha256'], name
        assert proc.wait() == 0
    assert seen == set(expected)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '4096'
    a = g.load()
    assert a['state'].startswith('BD terminal;') and a['returned_boot_id'] == BOOT
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    sealed(g.X / 'return-review', '7fcd4a3adb197210a267a1682d0e89a2c50fc1d64dffbfa6d9a514710e6d9b7e')
    sealed(ALLOCATION, 'db344ac87ca686ed6c7ea644ed6e5ae3d1bd15fc3997142b6c2071b9fb8fd873')
    proof = read(ALLOCATION / 'report.json')
    assert proof['source_delta'] == [BOARD] and proof['compiled_source_paths_checked'] == 84669
    assert proof['raw_comparison']['all_other_nodes_properties_exact']
    assert proof['retained_comparison']['all_other_nodes_properties_exact']
    assert proof['provider_contracts_verified'] and proof['static_nomap']
    assert g.sha(g.REPO / BOARD) == proof['board_sha256']
    assert not STAGE.exists() and not DEST.exists() and not DEST.with_suffix('.new').exists()
    STAGE.mkdir(mode=0o700)
    shutil.copy2(__file__, STAGE / Path(__file__).name)
    out = DEST.with_suffix('.new')
    try:
        parent_rows = read(g.X / 'dtb-build/candidate-source-files.json')
        assert len(parent_rows) == 96938
        expected = dict(parent_rows)
        path = g.REPO / BOARD
        expected[BOARD] = dict(sha256=g.sha(path), bytes=path.stat().st_size,
                               mode=stat.S_IMODE(path.stat().st_mode))
        assert expected[BOARD] != parent_rows[BOARD]
        checked = 0
        for name, row in expected.items():
            top = Path(name).parts[0]
            if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or
                    (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                    name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
                continue
            path = g.REPO / name
            if 'sha256' in row:
                assert g.sha(path) == row['sha256'], name
            else:
                assert path.is_symlink() and os.readlink(path) == row['symlink'], name
            checked += 1
        assert checked == 84669
        assert g.sha(g.REPO / '.config') == g.sha(g.X / 'dtb-build/live-config-before')
        print('BE live compiled sources/config and parent recovery verified', flush=True)
        source = STAGE / 'source'
        shutil.copytree('/var/tmp/spx-mainline-trial-20261004bd/source', source, symlinks=True)
        assert records(source) == parent_rows
        shutil.copy2(g.REPO / BOARD, source / BOARD)
        assert records(source) == expected
        (STAGE / 'source-files.json').write_text(json.dumps(expected, indent=2) + '\n')
        shutil.copy2(g.REPO / '.config', STAGE / 'live-config-before')
        with (STAGE / 'source.tar.zst').open('xb') as data, \
                (STAGE / 'source-tar.stderr').open('xb') as tar_err, \
                (STAGE / 'source-zstd.stderr').open('xb') as zstd_err:
            tar = subprocess.Popen(['tar', '--sort=name', '-cf', '-', '-C', str(source), '.'],
                                   stdout=subprocess.PIPE, stderr=tar_err)
            zstd = subprocess.Popen(['zstd', '-T2', '-3', '--no-progress'], stdin=tar.stdout,
                                    stdout=data, stderr=zstd_err)
            tar.stdout.close()
            assert zstd.wait() == 0 and tar.wait() == 0
        stream_verify(STAGE / 'source.tar.zst', expected)
        print('BE full 96,938-record candidate source archive stream verified', flush=True)
        out.mkdir(mode=0o700)
        shutil.copytree(g.X / 'build', out / 'build', symlinks=True)
        for name in ('build-sha256.json', 'build-symlinks.json', 'working-recovery.json'):
            shutil.copy2(g.X / name, out / name)
        assert g.files(out / 'build') == read(out / 'build-sha256.json')
        assert g.links(out / 'build') == read(out / 'build-symlinks.json')
        # The copied build is the exact original BC executable provenance.
        # Candidate source/DT inputs live separately so parent records remain exact.
        dt = out / 'dtb-build'
        shutil.copytree(ALLOCATION, dt)
        (dt / 'sha256.json').rename(dt / 'compile-sha256.json')
        shutil.copy2(dt / 'boot-after.dtb', dt / 'spx.dtb')
        shutil.copy2(STAGE / 'source.tar.zst', dt / 'candidate-source.tar.zst')
        shutil.copy2(STAGE / 'source-files.json', dt / 'candidate-source-files.json')
        shutil.copy2(STAGE / 'live-config-before', dt / 'live-config-before')
        for name in ('source-tar.stderr', 'source-zstd.stderr', 'prepare-be.py'):
            shutil.copy2(STAGE / name, dt / name)
        (dt / 'sha256.json').write_text(json.dumps(g.files(dt), indent=2) + '\n')
        (out / 'dtb-sha256.json').write_text(json.dumps(g.files(dt), indent=2) + '\n')
        (out / 'dt-input-files-sha256.json').write_text(json.dumps({BOARD: proof['board_sha256']}, indent=2) + '\n')
        assert g.sha(dt / 'spx.dtb') == '2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252'
        assert g.sha(dt / 'raw-after.dtb') == '0b86a7f1d18f19f281cf880c5cf5159ff2711116b1f51fe56aa5ad361ecd8928'
        assert {name for name in parent_rows if parent_rows[name] != expected[name]} == {BOARD}
        archive = read(g.X / 'parent-bc-records/archive-review.json')
        assert archive['source_archive_stream_verified'] and archive['full_kernel_and_modules_linked']
        assert archive['embedded_config_exact'] and archive['module_count'] == 202
        assert archive['private_initramfs_verified'] and archive['embedded_modules'] == 55
        logger = out / 'build/logging/initrd-log.sh'
        assert '/proc/sys/kernel/random/boot_id' in logger.read_text() and '/proc/cmdline' in logger.read_text()
        assert '20261004bc' not in logger.read_text()
        assert g.sha(logger) == g.sha(out / 'build/initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh')
        for name in ('vmlinuz', 'initramfs.img', 'config-extracted', 'module-sha256.json', 'module-links.json'):
            assert g.sha(out / 'build' / name) == g.sha(g.X / 'build' / name)
        assert g.files(out / 'build/module-root/lib/modules' / a['release']) == read(out / 'build/module-sha256.json')
        assert g.files(Path('/usr/lib/modules') / a['release']) == read(out / 'build/module-sha256.json')
        parent = out / 'parent-bd-records'
        parent.mkdir()
        for name in ('attempt.json', 'archive-review.json', 'return-review/report.json',
                     'return-review/sha256.json', 'offline-video-static-reservation/report.json',
                     'offline-video-static-reservation/sha256.json'):
            target = parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(g.X / name, target)
        for capsule in ('offline-pil-pgcm', 'offline-pil-reservation-policy'):
            shutil.copytree(g.X / capsule, out / capsule)
            sealed(out / capsule)
        shutil.copy2(__file__, out / Path(__file__).name)
        report = dict(utc=datetime.now(timezone.utc).isoformat(), attempt='20261004be',
            release=a['release'], parent_attempt='20261004bd', preboot_id=BOOT,
            kernel_modules_initramfs_reused_exact_bc=True,
            kernel_executable_sources_exact_bc=True, external_dt_only_source_delta=[BOARD],
            full_candidate_source_records_verified=96938,
            candidate_source_archive_stream_verified=True,
            candidate_source_archive_sha256=g.sha(dt / 'candidate-source.tar.zst'),
            candidate_source_manifest_sha256=g.sha(dt / 'candidate-source-files.json'),
            source_paths_checked=checked, live_config_exact_bc_prebuild=True,
            build_files_verified=len(g.files(out / 'build')),
            build_links_verified=len(g.links(out / 'build')),
            build_manifest_sha256=g.sha(out / 'build-sha256.json'),
            dtb_files_verified=len(g.files(dt)), dtb_manifest_sha256=g.sha(out / 'dtb-sha256.json'),
            candidate_dtb_sha256=g.sha(dt / 'spx.dtb'), raw_candidate_dtb_sha256=g.sha(dt / 'raw-after.dtb'),
            config_sha256=g.sha(out / 'build/config-extracted'), module_tree_files=217,
            module_count=202, embedded_modules=55, generic_private_logger_verified=True,
            provider_contracts_verified=True, exactly_one_reserved_memory_node_changed=True,
            static_video_base='0x8d300000', static_video_bytes=0x500000,
            pool_nomap_kept=True, runtime_prepared=False,
            parent_return_manifest_sha256=g.sha(g.X / 'return-review/sha256.json'),
            allocation_proof_manifest_sha256=g.sha(ALLOCATION / 'sha256.json'),
            recovery_definition_sha256=g.sha(out / 'working-recovery.json'),
            deployed=False, boot_selected=False, hardware_acceptance_closed=False)
        (out / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
        assert not g.recovery(a).get('next_entry', '')
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
        os.sync()
        out.rename(DEST)
        os.sync()
        (STAGE / 'prepared.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
    except BaseException:
        (STAGE / 'failure.txt').write_text(traceback.format_exc())
        os.sync()
        raise


if __name__ == '__main__':
    main()
