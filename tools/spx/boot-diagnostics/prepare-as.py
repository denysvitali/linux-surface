#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive exact AR build reuse and reviewed rear-only DT; select no boot."""
import json
import os
from pathlib import Path
import shutil
import sys

SRC = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ar_boot_guard import BASE, artifacts, files, links, load, recovery, sha


def verify(root):
    h = json.loads((root / 'sha256.json').read_text())
    assert files(root) == h | {'sha256.json': sha(root / 'sha256.json')}


def main():
    os.umask(0o077)
    parent = BASE / 'attempts/20261003ar'
    final = BASE / 'attempts/20261003as'
    out = BASE / 'attempts/20261003as.new'
    assert os.geteuid() == 0 and not out.exists() and not final.exists()
    a = load()
    assert not recovery(a).get('next_entry', '')
    artifacts(a)
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '5b14cce2-951f-4b43-a786-3cd2339f79b5'
    assert os.uname().release == a['release']
    review = json.loads((parent / 'independent-result-review.json').read_text())
    assert review['boot_id'] == bid and review['scoped_passed'] and review['fallback_stopped']
    for name in ('final-result', 'post-result-records', 'offline-rear-as-candidate-20261003'):
        verify(parent / name)
    out.mkdir(mode=0o700)
    shutil.copytree(parent / 'build', out / 'build', symlinks=True)
    for name in ('build-sha256.json', 'build-symlinks.json', 'working-recovery.json'):
        shutil.copy2(parent / name, out / name)
    assert files(out / 'build') == json.loads((out / 'build-sha256.json').read_text())
    assert links(out / 'build') == json.loads((out / 'build-symlinks.json').read_text())
    shutil.copytree(parent / 'embedded-config-review', out / 'embedded-config-review')
    verify(out / 'embedded-config-review')
    shutil.copy2(parent / 'independent-build-review.json', out / 'parent-build-review.json')
    dt = parent / 'offline-rear-as-candidate-20261003'
    shutil.copytree(dt, out / 'dtb-build')
    shutil.copy2(dt / 'enabled-review/candidate.dtb', out / 'dtb-build/spx.dtb')
    (out / 'dtb-sha256.json').write_text(json.dumps(files(out / 'dtb-build'), indent=2) + '\n')
    inputs = {str((SRC / 'camera-rear-only-20261003' / name).relative_to(SRC.parents[2])):
              sha(SRC / 'camera-rear-only-20261003' / name) for name in (
        'spx-rear-identification-disabled.dtsi', 'ovti,ov13858.yaml')}
    (out / 'dt-input-files-sha256.json').write_text(json.dumps(inputs, indent=2) + '\n')
    for name in inputs:
        archived = out / 'dtb-build/source' / Path(name).name
        assert sha(archived) == inputs[name]
    # The initrd logger identifies every boot by live UUID/cmdline, not a fixed attempt.
    logger = out / 'build/logging/initrd-log.sh'
    assert '/proc/sys/kernel/random/boot_id' in logger.read_text()
    assert '/proc/cmdline' in logger.read_text() and '20261003ar' not in logger.read_text()
    extracted = out / 'build/initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh'
    assert sha(extracted) == sha(logger)
    report = {
        'attempt': '20261003as', 'release': a['release'], 'preboot_id': bid,
        'parent_attempt': '20261003ar', 'kernel_modules_initramfs_reused_exact_ar': True,
        'parent_attempt_sha256': sha(parent / 'attempt.json'),
        'parent_result_review_sha256': sha(parent / 'independent-result-review.json'),
        'parent_result_manifest_sha256': sha(parent / 'final-result/sha256.json'),
        'parent_post_result_manifest_sha256': sha(parent / 'post-result-records/sha256.json'),
        'parent_build_review_sha256': sha(parent / 'independent-build-review.json'),
        'build_files_verified': len(files(out / 'build')),
        'build_links_verified': len(links(out / 'build')),
        'build_manifest_sha256': sha(out / 'build-sha256.json'),
        'full_source_archive_sha256': sha(out / 'build/source.tar.zst'),
        'candidate_dtb_sha256': sha(out / 'dtb-build/spx.dtb'),
        'candidate_review_manifest_sha256': sha(out / 'dtb-build/enabled-review/sha256.json'),
        'generic_private_initrd_logger_verified': True,
        'hardware_acceptance_closed': False, 'boot_selected': False, 'deployed': False}
    assert report['candidate_dtb_sha256'] == 'fa3b89f98697573d61bf23180bd81307de7e762e3a305b3240d087b4f4dc1561'
    (out / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert not recovery(a).get('next_entry', '')
    os.sync()
    out.rename(final)
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
