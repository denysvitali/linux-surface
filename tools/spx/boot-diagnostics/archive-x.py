#!/usr/bin/python3
"""Preserve and rehash X's complete build before installing any boot files."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
W = BASE / '20260927w'
X = BASE / '20260927x'
STAGE = Path('/var/tmp/spx-mainline-trial-20260927x')
RELEASE = '7.3.0-rc2-spx-mainline-20260927x+'
BID = 'e6989b7a-9ee5-4138-939d-84f8f73f53d5'


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


assert os.geteuid() == 0 and not X.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_attempt=20260927w' in Path('/proc/cmdline').read_text().split()
parent_review = json.loads((W / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed']
assert parent_review['fallback_stopped']
assert sha(W / 'silent-pcm-test/sha256.json') == 'b907ddaa6fa6611ed6d796285c417cb6931360a5effbaad0b56fb95f9ce492d1'
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

X.mkdir(mode=0o700)
shutil.copytree(STAGE, X / 'build', symlinks=True)
manifest = files(X / 'build')
symlinks = links(X / 'build')
(X / 'build-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
(X / 'build-symlinks.json').write_text(json.dumps(symlinks, indent=2) + '\n')
assert files(X / 'build') == manifest
assert links(X / 'build') == symlinks
for name, digest in modules.items():
    assert sha(X / 'build/module-root/lib/modules' / RELEASE / name) == digest, name
shutil.copy2(__file__, X / 'archive-x.py')
report = {'attempt': '20260927x', 'release': RELEASE,
          'build_files_verified': len(manifest),
          'build_symlinks_verified': len(symlinks),
          'build_manifest_sha256': sha(X / 'build-sha256.json'),
          'build_symlink_manifest_sha256': sha(X / 'build-symlinks.json'),
          'module_files_verified': len(modules),
          'module_manifest_sha256': sha(X / 'build/module-sha256.json'),
          'source_diff_sha256': sha(X / 'build/source.diff'),
          'config_sha256': sha(X / 'build/artifacts/.config'),
          'boot_payload_sha256': verification['artifacts'],
          'parent_result_review_sha256': sha(W / 'independent-result-review.json'),
          'parent_silent_test_manifest_sha256': sha(W / 'silent-pcm-test/sha256.json'),
          'boot_selected': False, 'deployed': False}
(X / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
