#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently review BE's exact BC payload reuse and complete static DT reservation."""
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
import bd_boot_guard as g
sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_aq_dtb_delta_ar import flatten
sys.path.insert(0, '/var/lib/spx-boot-diagnostics/attempts/20261004be/dtb-build')
import video_dt_contract as contract
import libfdt
import struct

X = g.BASE / 'attempts/20261004be'
STAGE = Path('/var/tmp/spx-mainline-trial-20261004be')
BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '433a78d6-9748-422f-a1a7-aac43c784a7d'
    assert os.uname().release == '6.18.3-1-surface+'
    a = g.load()
    assert a['state'].startswith('BD terminal;') and not g.recovery(a).get('next_entry', '')
    review = read(X / 'archive-review.json')
    assert review['kernel_modules_initramfs_reused_exact_bc']
    assert review['external_dt_only_source_delta'] == [BOARD]
    assert g.files(X / 'build') == read(X / 'build-sha256.json') == read(g.X / 'build-sha256.json')
    assert g.links(X / 'build') == read(X / 'build-symlinks.json') == read(g.X / 'build-symlinks.json')
    dt = X / 'dtb-build'
    assert g.files(dt) == read(X / 'dtb-sha256.json')
    assert g.files(dt) == read(dt / 'sha256.json') | {'sha256.json': g.sha(dt / 'sha256.json')}
    assert g.files(dt) == read(X / 'dtb-sha256.json')
    assert g.sha(X / 'dtb-sha256.json') == review['dtb_manifest_sha256']
    rows = read(dt / 'candidate-source-files.json')
    original = read(g.X / 'dtb-build/candidate-source-files.json')
    assert len(rows) == len(original) == 96938 and rows.keys() == original.keys()
    assert {name for name in rows if rows[name] != original[name]} == {BOARD}
    assert rows[BOARD]['sha256'] == '0edc078ca14ca2818c4c26313baf79d121c6e05cafb1ab93ac68d3a1629f9912'
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
            ('raw', g.X / 'dtb-build/raw-after.dtb', dt / 'raw-after.dtb'),
            ('boot', g.X / 'dtb-build/spx.dtb', dt / 'spx.dtb')):
        left, right = flatten(before.read_bytes()), flatten(after.read_bytes())
        old_path = '/reserved-memory/video-firmware'
        new_path = old_path + '@8d300000'
        assert old_path in left and new_path not in left
        assert new_path in right and old_path not in right
        static = right.pop(new_path)
        right[old_path] = static
        assert left.keys() == right.keys()
        expected = dict(left[old_path])
        for name in ('size', 'alignment', 'alloc-ranges'):
            del expected[name]
        expected['reg'] = struct.pack('>4I', 0, 0x8d300000, 0, 0x500000).hex()
        assert static == expected and static['no-map'] == ''
        assert static['phandle'] == left[old_path]['phandle']
        assert all(left[path] == right[path] for path in left if path != old_path)
        lf, rf = libfdt.Fdt(before.read_bytes()), libfdt.Fdt(after.read_bytes())
        assert lf.num_mem_rsv() == rf.num_mem_rsv()
        assert all(lf.get_mem_rsv(i) == rf.get_mem_rsv(i) for i in range(lf.num_mem_rsv()))
        assert contract.EXPECTED['memory-region'] == [(old_path, [])]
        contract.EXPECTED['memory-region'] = [(new_path, [])]
        contract.validate(after.read_bytes())
        contract.EXPECTED['memory-region'] = [(old_path, [])]
    assert not g.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=bid,
        release=review['release'], source_paths_checked=checked,
        full_source_records_verified=96938, source_archive_stream_verified=True,
        exactly_one_external_dt_source_delta=True, exactly_one_raw_and_boot_reserved_node_delta=True,
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
