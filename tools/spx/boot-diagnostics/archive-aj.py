#!/usr/bin/python3
"""Archive AJ's verified bounded command-history diagnostic build without installing boot files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
Z = BASE / '20260930ai'
AA = BASE / '20260930aj'
STAGE = Path('/var/tmp/spx-mainline-trial-20260930aj')
RELEASE = '7.3.0-rc2-spx-mainline-20260930aj+'
BID = '81412181-f873-4ba8-a5fe-07f5376bf680'


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


assert os.geteuid() == 0 and not AA.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
review = json.loads((Z / 'independent-result-review.json').read_text())
assert not review['scoped_passed'] and not review['fallback_stopped']
assert review['boot_id'] == '45fe6dfc-cd08-4536-9cdf-d5423699080d'
assert review['scoped_failure_reasons'] == ['native bus/clock-stop path', 'graphics/Wi-Fi/touch baseline']
for directory in ('final-result', 'post-result-records', 'recovery-return', 'pa-gain-guard-candidate'):
    root = Z / directory
    hashes = json.loads((root / 'sha256.json').read_text())
    assert files(root) == hashes | {'sha256.json': sha(root / 'sha256.json')}
assert json.loads((Z / 'recovery-return/report.json').read_text())['recovery_boot_id'] == BID
parent = json.loads((Z / 'attempt.json').read_text())
for name, digest in (parent['sha256'] | parent['recovery_sha256'] | parent['runtime_sha256']).items():
    assert sha(Path(name)) == digest, name
verification = json.loads((STAGE / 'build-verification.json').read_text())
assert verification['release'] == RELEASE
assert verification['modules'] == 187 and verification['module_tree_files'] == 202
assert verification['private_logger_exact'] and verification['embedded_config_exact']
assert (STAGE / 'config-extracted').read_bytes() == (STAGE / 'artifacts/.config').read_bytes()
assert sha(STAGE / 'artifacts/.config') == sha(REPO / '.config')
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (STAGE / 'source.diff').read_bytes()
for name, digest in json.loads((STAGE / 'build-complete.json').read_text())['source_sha256'].items():
    assert sha(REPO / name) == digest, name
for name, digest in verification['artifacts'].items():
    assert sha(STAGE / name) == digest, name
assert sha(STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb') == \
    '5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
module_root = STAGE / 'module-root/lib/modules' / RELEASE
modules = json.loads((STAGE / 'module-sha256.json').read_text())
assert len(modules) == 202 and files(module_root) == modules
module = module_root / 'kernel/drivers/soundwire/soundwire-qcom.ko'
params = subprocess.check_output(['modinfo', '-F', 'parm', str(module)], text=True)
assert 'spx_enum_diag:SPX: log at most eight enumerator-table transactions per controller (bool)' in params

assert 'spx_cmd_diag:SPX: dump the last sixteen FIFO command submissions on at most two command errors (bool)' in params
AA.mkdir(mode=0o700)
shutil.copytree(STAGE, AA / 'build', symlinks=True)
shutil.copytree(Z / 'dtb-build', AA / 'dtb-build', symlinks=True)
shutil.copy2(Z / 'dtb-sha256.json', AA / 'dtb-sha256.json')
assert files(AA / 'dtb-build') == json.loads((AA / 'dtb-sha256.json').read_text())
manifest = files(AA / 'build')
symlinks = links(AA / 'build')
(AA / 'build-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
(AA / 'build-symlinks.json').write_text(json.dumps(symlinks, indent=2) + '\n')
assert files(AA / 'build') == manifest and links(AA / 'build') == symlinks
shutil.copy2(__file__, AA / 'archive-aj.py')
report = {'attempt': '20260930aj', 'release': RELEASE, 'preboot_id': BID,
          'build_files_verified': len(manifest), 'build_symlinks_verified': len(symlinks),
          'module_files_verified': len(modules),
          'build_manifest_sha256': sha(AA / 'build-sha256.json'),
          'module_manifest_sha256': sha(AA / 'build/module-sha256.json'),
          'source_diff_sha256': sha(AA / 'build/source.diff'),
          'config_sha256': sha(AA / 'build/artifacts/.config'),
          'boot_payload_sha256': verification['artifacts'],
          'dtb_exact_ag': True, 'bounded_enum_diag_parameter_present': True, 'bounded_cmd_diag_parameter_present': True,
          'dtb_manifest_sha256': sha(AA / 'dtb-sha256.json'),
          'dtb_files_verified': len(files(AA / 'dtb-build')),
          'source_unchanged_during_build': True, 'embedded_config_exact': True,
          'parent_result_review_sha256': sha(Z / 'independent-result-review.json'),
          'parent_touch_review_sha256': sha(Z / 'touch-startup-review.json'),
          'parent_post_result_manifest_sha256': sha(Z / 'post-result-records/sha256.json'),
          'startup_diag_windows': 8, 'startup_diag_events_per_window': 48,
          'startup_diag_record_lifetime_limit': 384, 'functional_policy_unchanged': False, 'functional_delta': 'detached PA gain setter returns ENODEV before PM/IO/delay',
          'boot_selected': False, 'deployed': False, 'playback_requested': False}
(AA / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
