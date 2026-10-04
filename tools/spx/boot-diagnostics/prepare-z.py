#!/usr/bin/python3
"""Rehash and archive exact Y artifacts for the silent Z GPIO trial."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
Y = BASE / '20260927y'
Z = BASE / '20260930z'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BID = 'b5f0a540-3e81-4415-b08c-f869e01349a2'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


assert os.geteuid() == 0 and not Z.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r') == RELEASE
assert 'spx_attempt=20260927y' in Path('/proc/cmdline').read_text().split()
review = json.loads((Y / 'independent-result-review.json').read_text())
assert review['boot_id'] == BID and review['scoped_passed'] and review['fallback_stopped']
result_hashes = json.loads((Y / 'final-result/sha256.json').read_text())
assert sha(Y / 'final-result/sha256.json') == review['result_manifest_sha256']
for name, digest in result_hashes.items():
    assert sha(Y / 'final-result' / name) == digest, name
assert command('systemctl', 'show', 'spx-y-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
a = json.loads((Y / 'attempt.json').read_text())
for name, digest in (a['sha256'] | a['recovery_sha256']).items():
    assert sha(name) == digest, name
current_diff = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO)
current_commit = command('git', '-C', str(REPO), 'rev-parse', 'HEAD')
committed_changes = command('git', '-C', str(REPO), 'diff', '--name-only',
                            a['source_commit'], 'HEAD').splitlines()
assert all(name.startswith('tools/spx/boot-diagnostics/') or name.endswith('.md')
           for name in committed_changes), committed_changes


def kernel_diff(data):
    return b''.join(part for part in re.split(rb'(?=^diff --git )', data, flags=re.M)
                    if part.startswith((b'diff --git a/arch/', b'diff --git a/drivers/',
                                        b'diff --git a/net/', b'diff --git a/sound/')))


assert kernel_diff(current_diff) == kernel_diff((Y / 'build/source.diff').read_bytes())
assert sha(REPO / '.config') == sha(Y / 'build/artifacts/.config')
build = json.loads((Y / 'build-sha256.json').read_text())
links = json.loads((Y / 'build-symlinks.json').read_text())
assert len(build) == 977 and len(links) == 272
for name, digest in build.items():
    assert sha(Y / 'build' / name) == digest, name
for name, target in links.items():
    assert os.readlink(Y / 'build' / name) == target, name
modules = json.loads((Y / 'build/module-sha256.json').read_text())
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(Path('/usr/lib/modules') / RELEASE / name) == digest, name
assert Path('/sys/module/wcd934x/parameters/spx_wsa_en_pin').read_text().strip() == '-1'

Z.mkdir(mode=0o700)
(Z / 'current-source.diff').write_bytes(current_diff)
(Z / 'source-comparison.json').write_text(json.dumps({
    'built_source_commit': a['source_commit'], 'current_commit': current_commit,
    'committed_changes_since_build': committed_changes, 'kernel_diff_exact': True,
    'config_exact': True, 'current_source_diff_sha256': sha(Z / 'current-source.diff')}, indent=2) + '\n')
shutil.copytree(Y / 'build', Z / 'build', symlinks=True)
for name in ('build-sha256.json', 'build-symlinks.json'):
    shutil.copy2(Y / name, Z / name)
for name, digest in build.items():
    assert sha(Z / 'build' / name) == digest, name
for name, target in links.items():
    assert os.readlink(Z / 'build' / name) == target, name
sources = Z / 'preparation-sources'
sources.mkdir(mode=0o700)
names = ('prepare-z.py', 'deploy-z.py', 'z-finalize.py', 'review-z-install.py',
         'queue-z-once.py', 'z-reboot-check.py', 'review-z-result.py',
         'AUDIO-CONTINUATION-20260930.md', 'spx-mic-judge.py', 'test_mic_judge.py')
for name in names:
    shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, sources / name)
for name in ('AGENTS.md', 'LOCAL-PROGRESS.md'):
    shutil.copy2(REPO / name, sources / name)
manifest = {p.name: sha(p) for p in sorted(sources.iterdir())}
(Z / 'preparation-sources-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
(Z / 'reuse-review.json').write_text(json.dumps({
    'attempt': '20260930z', 'preboot_id': BID, 'release': RELEASE,
    'build_files_verified': len(build), 'build_symlinks_verified': len(links),
    'installed_module_files_verified': len(modules),
    'build_manifest_sha256': sha(Z / 'build-sha256.json'),
    'parent_result_manifest_sha256': sha(Y / 'final-result/sha256.json'),
    'preparation_manifest_sha256': sha(Z / 'preparation-sources-sha256.json'),
    'boot_selected': False, 'playback_requested': False,
    'comparison': 'Exact Y payloads; one boot-time SD_N pin selector'}, indent=2) + '\n')
os.sync()
print('Z exact-artifact archive verified; no boot files or boot selection changed')
