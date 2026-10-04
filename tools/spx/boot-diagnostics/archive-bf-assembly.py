#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal BF's private assembled payloads without changing its first build archive."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bf_build', HERE / 'build-bf.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
g = b.g
STAGE = b.STAGE
X = g.BASE / 'attempts/20261004bf'


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.BOOT
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    first_sha = '0faf4fa9c249d139319f5dc1ca7d33cfc9be2825455c9ec7b64b78c22211cf7e'
    review_sha = '2b35e937da781140297bf1e927a309409c5c6a9ef13e3b539cf03e166e9dcd81'
    assert g.sha(X / 'build-sha256.json') == first_sha and g.sha(X / 'build-review.json') == review_sha
    assert g.files(X / 'build') == read(X / 'build-sha256.json')
    built = read(STAGE / 'build-complete.json')
    assembled = read(STAGE / 'build-verification.json')
    assert built['release'] == assembled['release'] == b.RELEASE
    assert assembled['modules'] == built['modules'] == 202
    assert assembled['embedded_modules'] == 55 and assembled['module_tree_files'] == 217
    assert assembled['embedded_module_payloads_exact'] and assembled['private_logger_exact']
    assert assembled['boot_dtb_exact_parent_be'] and assembled['raw_compiled_board_dtb_exact_parent_be']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    for name, digest in assembled['artifacts'].items():
        assert g.sha(STAGE / name) == digest, name
    root = STAGE / 'module-root/lib/modules' / b.RELEASE
    assert g.files(root) == read(STAGE / 'module-sha256.json') and len(g.files(root)) == 217
    modules = sorted(root.rglob('*.ko'))
    assert len(modules) == 202
    for module in modules:
        name = str(module.relative_to(root)).removeprefix('kernel/')
        assert g.sha(module) == built['artifacts'][name] == g.sha(STAGE / 'artifacts' / name), name
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).split()[0] == b.RELEASE
    assert not (STAGE / 'depmod.log').read_text().strip()
    assert read(STAGE / 'videocc-alias-resolution.json')['modules'] == ['videocc_sm8150']
    extract = STAGE / 'initramfs-extracted'
    embedded = sorted(extract.rglob('*.ko'))
    assert len(embedded) == 55
    prefix = 'usr/lib/modules/' + b.RELEASE + '/'
    for module in embedded:
        name = str(module.relative_to(extract))
        assert name.startswith(prefix) and g.sha(module) == g.sha(root / name[len(prefix):])
    assert g.sha(extract / 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == g.sha(STAGE / 'logging/initrd-log.sh')
    assert g.sha(STAGE / 'logging/initrd-log.sh') == g.sha(b.PARENT / 'logging/initrd-log.sh')
    assert (STAGE / 'mkinitcpio.conf').read_text() == (b.PARENT / 'mkinitcpio.conf').read_text().replace('20261004bc', '20261004bf')
    assert (STAGE / 'initcpio/install/spx_diagnostics').read_text() == (b.PARENT / 'initcpio/install/spx_diagnostics').read_text().replace('20261004bc', '20261004bf')
    assert g.files(STAGE / 'dtb-build') == read(g.X / 'dtb-sha256.json')
    assert g.sha(STAGE / 'dtb-build/spx.dtb') == '2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252'
    assert b.records(STAGE / 'source') == read(STAGE / 'source-files.json')
    diagnostic = read(g.X / 'offline-venus-startup-diag-20261004/report.json')
    assert b.live_source(diagnostic) == 84669
    assert g.sha(STAGE / 'work-build/.config') == built['config_sha256']
    shutil.copy2(__file__, STAGE / Path(__file__).name)
    target = X / 'assembly'
    shutil.copytree(STAGE, target, symlinks=True,
        ignore=lambda path, names: {'source', 'work-build'} if Path(path) == STAGE else set())
    # Compare the exact included namespace without hashing the excluded trees.
    expected_files, expected_links = {}, {}
    for child in STAGE.iterdir():
        if child.name in ('source', 'work-build'):
            continue
        if child.is_symlink():
            expected_links[child.name] = os.readlink(child)
        elif child.is_file():
            expected_files[child.name] = g.sha(child)
        else:
            expected_files.update({child.name + '/' + n: h for n, h in g.files(child).items()})
            expected_links.update({child.name + '/' + n: h for n, h in g.links(child).items()})
    assert g.files(target) == expected_files and g.links(target) == expected_links
    module_target = target / 'module-root/lib/modules' / b.RELEASE
    (target / 'module-links.json').write_text(json.dumps(g.links(module_target), indent=2) + '\n')
    (X / 'assembly-sha256.json').write_text(json.dumps(g.files(target), indent=2) + '\n')
    (X / 'assembly-symlinks.json').write_text(json.dumps(g.links(target), indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), release=b.RELEASE,
        current_boot_id=b.BOOT, first_build_manifest_sha256=first_sha, first_build_review_sha256=review_sha,
        module_count=202, module_tree_files=217, all_staged_module_bytes_exact_compiled=True,
        all_module_vermagic_exact=True, depmod_clean=True, actual_of_fallback_alias_resolves=True,
        embedded_modules=55, embedded_module_payloads_exact=True, private_logger_exact=True,
        initramfs_sha256=g.sha(target / 'initramfs.img'), raw_and_retained_dtb_exact_be=True,
        boot_dtb_sha256=g.sha(target / 'dtb-build/spx.dtb'),
        full_private_source_records_verified=96938, live_compiled_source_paths_verified=84669,
        assembly_files=len(g.files(target)), assembly_links=len(g.links(target)),
        assembly_manifest_sha256=g.sha(X / 'assembly-sha256.json'),
        assembly_symlinks_sha256=g.sha(X / 'assembly-symlinks.json'),
        original_build_archive_unchanged=True, recovery_reverified=True,
        persistent_default='spx-known-good', next_entry_empty=True,
        runtime_prepared=False, module_tree_installed=False, deployed=False,
        boot_selected=False, hardware_acceptance_closed=False)
    (X / 'assembly-review.json').write_text(json.dumps(report, indent=2) + '\n')
    os.sync()
    assert g.files(target) == read(X / 'assembly-sha256.json')
    assert g.links(target) == read(X / 'assembly-symlinks.json')
    assert g.files(X / 'build') == read(X / 'build-sha256.json')
    assert not g.recovery(a).get('next_entry', '')
    print(json.dumps(report | dict(assembly_review_sha256=g.sha(X / 'assembly-review.json'))), flush=True)


if __name__ == '__main__':
    main()
