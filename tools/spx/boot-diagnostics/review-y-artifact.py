#!/usr/bin/python3
"""Independently check Y's immutable build archive before deployment."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
X = BASE / '20260927x'
Y = BASE / '20260927y'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'
BID = 'f5039e57-1a71-4833-9193-6da333d4d4f9'


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


assert os.geteuid() == 0 and not (Y / 'independent-artifact-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_attempt=20260927x' in Path('/proc/cmdline').read_text().split()
parent = json.loads((X / 'independent-result-review.json').read_text())
assert parent['boot_id'] == BID and parent['scoped_passed']
assert parent['fallback_stopped']
archive = json.loads((Y / 'archive-review.json').read_text())
build = Y / 'build'
manifest = json.loads((Y / 'build-sha256.json').read_text())
symlinks = json.loads((Y / 'build-symlinks.json').read_text())
assert len(manifest) == archive['build_files_verified'] == 977
assert len(symlinks) == archive['build_symlinks_verified'] == 272
assert files(build) == manifest and links(build) == symlinks
assert sha(Y / 'build-sha256.json') == archive['build_manifest_sha256']
assert sha(Y / 'build-symlinks.json') == archive['build_symlink_manifest_sha256']
modules = json.loads((build / 'module-sha256.json').read_text())
root = build / 'module-root/lib/modules' / RELEASE
assert len(modules) == 202 and files(root) == modules
assert sha(build / 'module-sha256.json') == archive['module_manifest_sha256']
assert len(list(root.rglob('*.ko'))) == 187
for module in root.rglob('*.ko'):
    vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic',
                                        str(module)], text=True).split()[0]
    assert vermagic == RELEASE, module
assert (build / 'artifacts/.config').read_bytes() == (build / 'config-extracted').read_bytes()
assert sha(build / 'artifacts/.config') == archive['config_sha256']
assert (build / 'kernel-release.txt').read_text().strip() == RELEASE
assert sha(build / 'logging/initrd-log.sh') == sha(
    build / 'initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh')
assert sha(build / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb') == \
    sha(X / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')
for name, digest in archive['boot_payload_sha256'].items():
    assert sha(build / name) == digest, name
source = json.loads((build / 'build-complete.json').read_text())['source_sha256']
assert sha(REPO / 'sound/soc/codecs/wsa881x.c') == \
    source['sound/soc/codecs/wsa881x.c'] == \
    'f7d46a6cbebf37c071b43c4709fea68e99032a22f740423f53a80dc51c5bb825'
assert (build / 'diagnostic-sources/AUDIO-WSA-CONTROL-READ-20260927.md').is_file()
assert sha(build / 'diagnostic-sources/AUDIO-WSA-CONTROL-READ-20260927.md') == \
    source['tools/spx/boot-diagnostics/AUDIO-WSA-CONTROL-READ-20260927.md']
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == \
    (build / 'source.diff').read_bytes()
assert sha(build / 'source.diff') == archive['source_diff_sha256']
attempt = json.loads((X / 'attempt.json').read_text())
for path, digest in attempt['recovery_sha256'].items():
    assert sha(path) == digest, path
env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'],
                              text=True).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
assert not Path('/boot/spx-trial-20260927y').exists()
report = {'attempt': '20260927y', 'regular_files_verified': len(manifest),
          'symlinks_verified': len(symlinks), 'module_files_verified': len(modules),
          'module_vermagic': RELEASE, 'embedded_config_exact': True,
          'private_logger_exact': True, 'dtb_matches_x': True,
          'source_patch_exact': True,
          'recovery_files_verified': len(attempt['recovery_sha256']),
          'known_good_default': True, 'next_entry_empty': True,
          'efi_bootnext_absent': True, 'boot_selected': False}
(Y / 'independent-artifact-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
