#!/usr/bin/python3
"""Archive AA's verified diagnostic build without installing boot files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
Z = BASE / '20260930z'
AA = BASE / '20260930aa'
STAGE = Path('/var/tmp/spx-mainline-trial-20260930aa')
RELEASE = '7.3.0-rc2-spx-mainline-20260930aa+'
BID = 'e0479717-1fe0-4a8f-a6ac-af198c4b703a'


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
assert review['scoped_failure_reasons'] == ['expected two-device topology']
assert review['gpio_software_state_passed'] and review['system_baseline_passed']
recovery = json.loads((Z / 'recovery-result/report.json').read_text())
assert recovery['recovery_boot_id'] == BID and recovery['automatic_fallback_invoked']
for name, digest in json.loads((Z / 'recovery-result/sha256.json').read_text()).items():
    assert sha(Z / 'recovery-result' / name) == digest, name
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
    'ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a'
module_root = STAGE / 'module-root/lib/modules' / RELEASE
modules = json.loads((STAGE / 'module-sha256.json').read_text())
assert len(modules) == 202 and files(module_root) == modules
module = module_root / 'kernel/drivers/soundwire/soundwire-qcom.ko'
params = subprocess.check_output(['modinfo', '-F', 'parm', str(module)], text=True)
assert 'spx_enum_diag:SPX: log at most eight enumerator-table transactions per controller (bool)' in params

AA.mkdir(mode=0o700)
shutil.copytree(STAGE, AA / 'build', symlinks=True)
manifest = files(AA / 'build')
symlinks = links(AA / 'build')
(AA / 'build-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
(AA / 'build-symlinks.json').write_text(json.dumps(symlinks, indent=2) + '\n')
assert files(AA / 'build') == manifest and links(AA / 'build') == symlinks
shutil.copy2(__file__, AA / 'archive-aa.py')
report = {'attempt': '20260930aa', 'release': RELEASE, 'preboot_id': BID,
          'build_files_verified': len(manifest), 'build_symlinks_verified': len(symlinks),
          'module_files_verified': len(modules),
          'build_manifest_sha256': sha(AA / 'build-sha256.json'),
          'module_manifest_sha256': sha(AA / 'build/module-sha256.json'),
          'source_diff_sha256': sha(AA / 'build/source.diff'),
          'config_sha256': sha(AA / 'build/artifacts/.config'),
          'boot_payload_sha256': verification['artifacts'],
          'dtb_exact_z': True, 'bounded_enum_diag_parameter_present': True,
          'source_unchanged_during_build': True, 'embedded_config_exact': True,
          'parent_result_review_sha256': sha(Z / 'independent-result-review.json'),
          'parent_recovery_manifest_sha256': sha(Z / 'recovery-result/sha256.json'),
          'boot_selected': False, 'deployed': False, 'playback_requested': False}
(AA / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
