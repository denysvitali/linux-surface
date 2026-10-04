#!/usr/bin/python3
"""Archive a DT-only WSA identity correction without selecting a boot."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
R = BASE / '20260927r'
T = BASE / '20260927t'
U = BASE / '20260927u'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
DTB = REPO / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
OLD = Path('/boot/spx-trial-20260927r/spx.dtb')
SOURCE = REPO / 'arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, cwd=REPO, timeout=90)


assert os.geteuid() == 0 and not U.exists()
result = json.loads((T / 'final-result/result.json').read_text())
review = json.loads((T / 'independent-result-review.json').read_text())
assert result['boot_id'] == review['boot_id']
assert result['attached_slave_count'] == result['force_attach_slave_markers'] == 0
assert review['scoped_result'] == 'failed-unattached'
assert sha(T / 'final-result/sha256.json') == review['result_manifest_sha256']
assert all(v['status'] == 'UNATTACHED' for v in result['soundwire_slaves'].values())
assert sha(OLD) == '5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
assert command('make', '-s', 'kernelrelease').strip() == '7.3.0-rc2-spx-mainline-20260927r+'
assert sha(REPO / '.config') == sha(R / 'build/artifacts/.config')
src = SOURCE.read_text()
assert src.count('compatible = "sdw10217201000";') == 2
assert src.count('compatible = "sdw10217211000";') == 0
old = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', str(OLD)],
                     capture_output=True, check=True).stdout
new = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', str(DTB)],
                     capture_output=True, check=True).stdout
assert old.count(b'sdw10217211000') == 2
assert new == old.replace(b'sdw10217211000', b'sdw10217201000')
parent = json.loads((R / 'build-sha256.json').read_text())
assert len(parent) == 922
for name, digest in parent.items():
    assert sha(R / 'build' / name) == digest, name

U.mkdir(mode=0o700)
shutil.copytree(R / 'build', U / 'reused-build', symlinks=True)
shutil.copy2(R / 'build-sha256.json', U / 'reused-build-sha256.json')
for name, digest in parent.items():
    assert sha(U / 'reused-build' / name) == digest, name
work = U / 'dtb-build'
work.mkdir()
shutil.copy2(DTB, work / 'spx.dtb')
shutil.copy2(OLD, work / 'parent-spx.dtb')
shutil.copy2(SOURCE, work / 'sc8180x-wcd9340.dtsi')
shutil.copy2(REPO / '.config', work / 'config')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/AUDIO-SOUNDWIRE-ID-20260927.md',
             work / 'plan.md')
shutil.copy2(REPO / 'tools/spx/boot-diagnostics/RESULT-20260927t.md',
             work / 'prior-result.md')
shutil.copy2(__file__, U / 'prepare-u.py')
(work / 'source.diff').write_bytes(subprocess.check_output(
    ['git', 'diff', '--binary', 'HEAD'], cwd=REPO))
(work / 'source-status.txt').write_text(command('git', 'status', '--short',
                                               '--untracked-files=all'))
(work / 'commit').write_text(command('git', 'rev-parse', 'HEAD'))
(work / 'dtc-old.dts').write_bytes(old)
(work / 'dtc-new.dts').write_bytes(new)
(work / 'dtb-build.log').write_text(
    'make -j6 qcom/sc8180x-surface-pro-x.dtb: exit 0; DTC target rebuilt\n')
manifest = {str(p.relative_to(U)): sha(p) for p in sorted(U.rglob('*'))
            if p.is_file() and not p.is_symlink()}
(U / 'preparation-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
report = {'attempt': '20260927u', 'boot_selected': False,
          'source_commit': command('git', 'rev-parse', 'HEAD').strip(),
          'source_diff_sha256': sha(work / 'source.diff'),
          'config_sha256': sha(work / 'config'),
          'parent_dtb_sha256': sha(work / 'parent-spx.dtb'),
          'new_dtb_sha256': sha(work / 'spx.dtb'),
          'reused_build_manifest_sha256': sha(U / 'reused-build-sha256.json'),
          'reused_build_files_verified': len(parent),
          'preparation_manifest_sha256': sha(U / 'preparation-sha256.json'),
          'preparation_files': len(manifest),
          'prior_result_review_sha256': sha(T / 'independent-result-review.json'),
          'exact_dtb_delta': 'two speaker compatible 2110 -> 2010 properties'}
(U / 'preparation-review.json').write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
