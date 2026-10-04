#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare a private AU output clone for the distinct AX RTC configuration."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from aw_boot_guard import X, REPO, files, sha, load, recovery, artifacts


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot == 'fbc6d663-8269-4d2f-9aac-c4a687583b00'
    a = load()
    assert not recovery(a).get('next_entry', '')
    artifacts(a)
    returned = X / 'return-result'
    manifest = json.loads((returned / 'sha256.json').read_text())
    assert files(returned) == manifest | {'sha256.json': sha(returned / 'sha256.json')}
    parent = Path('/var/tmp/spx-mainline-trial-20261003au')
    stage = Path('/var/tmp/spx-mainline-trial-20261003ax')
    assert not stage.exists()
    stage.mkdir(mode=0o700)
    assert sha(parent / 'source.tar.zst') == sha(X / 'build/source.tar.zst')
    assert sha(parent / 'work-build/.config') == sha(X / 'build/artifacts/.config')
    for name in ('source-files.json', 'source.tar.zst', 'source-tar.json', 'source-commit.txt',
                 'source.diff', 'source-status.txt', 'compiled-source-delta.json'):
        shutil.copy2(parent / name, stage / name)
    (stage / 'source').symlink_to(parent / 'source', target_is_directory=True)
    subprocess.run(['cp', '-a', '--reflink=auto', str(parent / 'work-build'),
                    str(stage / 'work-build')], check=True)
    shutil.copy2(parent / 'work-build/.config', stage / 'config-parent')
    shutil.copy2(REPO / '.config', stage / 'live-config-before')
    shutil.copy2(REPO / 'arch/arm64/configs/spx.config', stage / 'spx-config-overlay')
    shutil.copy2(Path(__file__), stage / 'prepare-ax.py')
    (stage / 'parent-output-sha256.json').write_text(json.dumps(files(parent / 'work-build'), indent=2) + '\n')
    (stage / 'stage-copy-complete.json').write_text(json.dumps({
        'boot_id': boot, 'parent_attempt': '20261003au', 'parent_result_attempt': '20261003aw',
        'parent_return_manifest_sha256': sha(returned / 'sha256.json'),
        'source_paths': len(json.loads((stage / 'source-files.json').read_text())),
        'immutable_source_root': str(parent / 'source'),
        'source_archive_sha256': sha(stage / 'source.tar.zst'),
        'source_code_changes': [], 'config_overlay_sha256': sha(stage / 'spx-config-overlay'),
        'parent_output_manifest_sha256': sha(stage / 'parent-output-sha256.json'),
        'clone_terminal': True, 'boot_selected': False}, indent=2) + '\n')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    assert not recovery(a).get('next_entry', '')
    os.sync()
    print('AX private output clone prepared; AU immutable source and parent output preserved', flush=True)


if __name__ == '__main__':
    main()
