#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently review BD's exact BC payload reuse and complete corrected DT source."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bc_boot_guard as g
sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_aq_dtb_delta_ar import flatten
sys.path.insert(0, str(Path(__file__).resolve().parent / 'video-power-20261003'))
from video_dt_contract import validate

X = g.BASE / 'attempts/20261004bd'
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bd')
BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '78d60cce-ef40-4cea-93e1-42727db4a851'
    assert os.uname().release == '6.18.3-1-surface+'
    a = g.load()
    assert a['state'].startswith('BC terminal;') and not g.recovery(a).get('next_entry', '')
    review = read(X / 'archive-review.json')
    assert review['kernel_modules_initramfs_reused_exact_bc']
    assert review['external_dt_only_source_delta'] == [BOARD]
    assert g.files(X / 'build') == read(X / 'build-sha256.json') == read(g.X / 'build-sha256.json')
    assert g.links(X / 'build') == read(X / 'build-symlinks.json') == read(g.X / 'build-symlinks.json')
    dt = X / 'dtb-build'
    assert g.files(dt) == read(X / 'dtb-sha256.json')
    # The original preparation retained the scoped compile manifest in its
    # old filename after adding packaging inputs. Preserve it explicitly as
    # the scoped subset and add a complete directory manifest, without any
    # change to compiled/source/payload bytes.
    if not (dt / 'scoped-build-sha256.json').exists():
        assert g.sha(dt / 'sha256.json') == '2fdcbeea98a96d7cf13bd7ec034dc19f5ed5d17b9abd070614bf0472383f9c58'
        old = read(dt / 'sha256.json')
        assert all(g.sha(dt / name) == digest for name, digest in old.items())
        capsule = X / 'dt-manifest-normalization'
        assert not capsule.exists()
        capsule.mkdir(mode=0o700)
        for source, name in ((X / 'archive-review.json', 'archive-review-before.json'),
                             (X / 'dtb-sha256.json', 'dtb-manifest-before.json'),
                             (dt / 'sha256.json', 'scoped-compile-manifest.json'),
                             (STAGE / 'prepared.json', 'stage-prepared-before.json')):
            shutil.copy2(source, capsule / name)
        (dt / 'sha256.json').rename(dt / 'scoped-build-sha256.json')
        (dt / 'sha256.json').write_text(json.dumps(g.files(dt), indent=2) + '\n')
        (X / 'dtb-sha256.json').write_text(json.dumps(g.files(dt), indent=2) + '\n')
        review.update(dtb_files_verified=len(g.files(dt)),
                      dtb_manifest_sha256=g.sha(X / 'dtb-sha256.json'),
                      scoped_manifest_preserved_separately=True,
                      complete_dtb_directory_manifest_verified=True)
        for path in (X / 'archive-review.json', STAGE / 'prepared.json'):
            path.write_text(json.dumps(review, indent=2) + '\n')
        shutil.copy2(X / 'archive-review.json', capsule / 'archive-review-after.json')
        shutil.copy2(X / 'dtb-sha256.json', capsule / 'dtb-manifest-after.json')
        shutil.copy2(__file__, capsule / Path(__file__).name)
        (capsule / 'sha256.json').write_text(json.dumps(g.files(capsule), indent=2) + '\n')
        os.sync()
    assert g.files(dt) == read(dt / 'sha256.json') | {'sha256.json': g.sha(dt / 'sha256.json')}
    assert g.files(dt) == read(X / 'dtb-sha256.json')
    assert g.sha(X / 'dtb-sha256.json') == review['dtb_manifest_sha256']
    rows = read(dt / 'candidate-source-files.json')
    original = read(X / 'build/source-files.json')
    assert len(rows) == len(original) == 96938 and rows.keys() == original.keys()
    assert {name for name in rows if rows[name] != original[name]} == {BOARD}
    assert rows[BOARD]['sha256'] == '1534c6579dd98a7056930ec5d7a2ce4ce3db7ebdb6d530ec7e4b024fb221dcea'
    assert g.sha(dt / 'candidate-source.tar.zst') == review['candidate_source_archive_sha256']
    # Independently parse and rehash every archive entry, including modes and links.
    seen = set()
    with subprocess.Popen(['zstd', '-dc', str(dt / 'candidate-source.tar.zst')], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                name = entry.name.removeprefix('./')
                assert name in rows and name not in seen
                seen.add(name)
                row = rows[name]
                if entry.issym():
                    assert row == dict(symlink=entry.linkname)
                else:
                    assert entry.isfile() and entry.mode == row['mode'] and entry.size == row['bytes']
                    stream = archive.extractfile(entry)
                    h = hashlib.sha256()
                    for data in iter(lambda: stream.read(1048576), b''):
                        h.update(data)
                    assert h.hexdigest() == row['sha256'], name
        assert proc.wait() == 0
    assert seen == set(rows)
    checked = 0
    for name, row in rows.items():
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
    assert g.sha(g.REPO / '.config') == g.sha(dt / 'live-config-before')
    for name in ('vmlinuz', 'initramfs.img', 'config-extracted', 'module-sha256.json'):
        assert g.sha(X / 'build' / name) == g.sha(g.X / 'build' / name)
    modules = read(X / 'build/module-sha256.json')
    assert len(modules) == 217 and g.files(Path('/usr/lib/modules') / review['release']) == modules
    for kind, before, after in (
            ('raw', X / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb', dt / 'raw-after.dtb'),
            ('boot', X / 'build/dtb-build/spx.dtb', dt / 'spx.dtb')):
        left, right = flatten(before.read_bytes()), flatten(after.read_bytes())
        assert left.keys() == right.keys()
        delta = [(path, prop) for path in left for prop in set(left[path]) | set(right[path])
                 if left[path].get(prop) != right[path].get(prop)]
        assert delta == [('/reserved-memory/video-firmware', 'alloc-ranges')], (kind, delta)
        assert right['/reserved-memory/video-firmware']['alloc-ranges'] == '000000008b700000000000000f400000'
        validate(after.read_bytes())
    assert not g.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=bid,
        release=review['release'], source_paths_checked=checked,
        full_source_records_verified=96938, source_archive_stream_verified=True,
        exactly_one_external_dt_source_delta=True, exactly_one_raw_and_boot_property_delta=True,
        kernel_modules_initramfs_reused_exact_bc=True, live_config_exact=True,
        installed_module_files_verified=217, build_files_verified=2849, build_links_verified=272,
        dtb_files_verified=len(g.files(dt)), archive_review_sha256=g.sha(X / 'archive-review.json'),
        persistent_default='spx-known-good', next_entry_empty=True,
        deployed=False, boot_selected=False, hardware_acceptance_closed=False)
    destination = X / 'independent-preparation-review.json'
    assert not destination.exists()
    destination.write_text(json.dumps(report, indent=2) + '\n')
    shutil.copy2(__file__, X / Path(__file__).name)
    os.sync()
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
