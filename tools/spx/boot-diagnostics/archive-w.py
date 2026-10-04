#!/usr/bin/python3
"""Preserve and rehash W's complete build before installing any boot files."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
V = BASE / '20260927v'
W = BASE / '20260927w'
STAGE = Path('/var/tmp/spx-mainline-trial-20260927w')
RELEASE = '7.3.0-rc2-spx-mainline-20260927w+'
BID = 'b9a390b7-fb58-40bc-8ae2-8404ee9e88d2'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def links(root):
    return {str(p.relative_to(root)): os.readlink(p)
            for p in sorted(root.rglob('*')) if p.is_symlink()}


assert os.geteuid() == 0 and not W.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
return_review = json.loads((V / 'independent-return-review.json').read_text())
assert return_review['current_boot_id'] == BID
assert return_review['recovery_hashes_verified'] == 3
verification = json.loads((STAGE / 'build-verification.json').read_text())
assert verification['release'] == RELEASE
assert verification['modules'] == 187 and verification['module_tree_files'] == 202
assert verification['private_logger_exact'] and verification['embedded_config_exact']
assert (STAGE / 'config-extracted').read_bytes() == (
    STAGE / 'artifacts/.config').read_bytes()
assert sha(STAGE / 'artifacts/.config') == sha(REPO / '.config')
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (
    STAGE / 'source.diff').read_bytes()
for name, digest in json.loads((STAGE / 'build-complete.json').read_text())[
        'source_sha256'].items():
    assert sha(REPO / name) == digest, name
for name, digest in verification['artifacts'].items():
    assert sha(STAGE / name) == digest, name
root = STAGE / 'module-root/lib/modules' / RELEASE
modules = json.loads((STAGE / 'module-sha256.json').read_text())
assert len(modules) == 202
assert files(root) == modules
assert sha(root / 'vmlinuz') == sha(STAGE / 'artifacts/arch/arm64/boot/Image')
assert sha(STAGE / 'initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == \
    sha(STAGE / 'logging/initrd-log.sh')
assert (STAGE / 'assembly-retry-note').is_file()
assert (STAGE / 'modules-stage.first.log').is_file()

W.mkdir(mode=0o700)
shutil.copytree(STAGE, W / 'build', symlinks=True)
manifest = files(W / 'build')
symlinks = links(W / 'build')
(W / 'build-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
(W / 'build-symlinks.json').write_text(json.dumps(symlinks, indent=2) + '\n')
assert files(W / 'build') == manifest
assert links(W / 'build') == symlinks
for name, digest in modules.items():
    assert sha(W / 'build/module-root/lib/modules' / RELEASE / name) == digest, name
shutil.copy2(__file__, W / 'archive-w.py')
report = {'attempt': '20260927w', 'release': RELEASE,
          'build_files_verified': len(manifest),
          'build_symlinks_verified': len(symlinks),
          'build_manifest_sha256': sha(W / 'build-sha256.json'),
          'build_symlink_manifest_sha256': sha(W / 'build-symlinks.json'),
          'module_files_verified': len(modules),
          'module_manifest_sha256': sha(W / 'build/module-sha256.json'),
          'source_diff_sha256': sha(W / 'build/source.diff'),
          'config_sha256': sha(W / 'build/artifacts/.config'),
          'boot_payload_sha256': verification['artifacts'],
          'prior_return_review_sha256': sha(V / 'independent-return-review.json'),
          'boot_selected': False, 'deployed': False}
(W / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
