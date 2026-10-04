#!/usr/bin/python3
"""Prepare AJ only after the frozen AI result, verified recovery, and gain tests."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
repo = Path('/home/dvitali/Documents/git/linux-surface-next')
parent = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ai')
stage = Path('/var/tmp/spx-mainline-trial-20260930aj')
bid = '81412181-f873-4ba8-a5fe-07f5376bf680'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
assert os.geteuid() == 0 and not stage.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
for directory in ('final-result', 'post-result-records', 'recovery-return', 'pa-gain-guard-candidate'):
    root = parent / directory
    h = json.loads((root / 'sha256.json').read_text())
    assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()} == h | {'sha256.json':sha(root / 'sha256.json')}
recovery = json.loads((parent / 'recovery-return/report.json').read_text())
assert recovery['recovery_boot_id'] == bid and recovery['userspace_fallback_return_verified']
candidate = parent / 'pa-gain-guard-candidate'
review = json.loads((candidate / 'independent-review.json').read_text())
assert review['sanitizers_passed'] and review['exact_C_differential_cases'] == 624
assert review['native_codec_object_compile_exit_code'] == 0
assert sha(repo / 'sound/soc/codecs/wsa881x.c') == review['driver_sha256']
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo) == (candidate / 'source.diff').read_bytes()
assert sha(repo / '.config') == sha(parent / 'post-result-records/config')
a = json.loads((parent / 'attempt.json').read_text())
assert a == json.loads((parent.parent.parent / 'attempt.json').read_text())
for n,d in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
    assert sha(Path(n)) == d,n
env = subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
stage.mkdir(mode=0o700)
for n in ('logging','initcpio'):
    shutil.copytree(parent / 'build' / n,stage / n,symlinks=True)
hook = stage / 'initcpio/install/spx_diagnostics'
hook.write_text(hook.read_text().replace('20260930ai','20260930aj'))
shutil.copy2(parent / 'build/mkinitcpio.conf',stage / 'mkinitcpio.conf')
c = stage / 'mkinitcpio.conf'
c.write_text(c.read_text().replace('20260930ai','20260930aj'))
shutil.copy2(repo / '.config',stage / 'config-before')
shutil.copytree(parent / 'build/command-source-review',stage / 'command-source-review')
shutil.copytree(candidate,stage / 'gain-source-review')
report = {'preboot_id':bid,'parent_attempt':'20260930ai',
          'parent_result_manifest_sha256':sha(parent / 'final-result/sha256.json'),
          'parent_recovery_manifest_sha256':sha(parent / 'recovery-return/sha256.json'),
          'candidate_manifest_sha256':sha(candidate / 'sha256.json'),'boot_selected':False}
(stage / 'preparation-review.json').write_text(json.dumps(report,indent=2)+'\n')
shutil.copy2(__file__,stage / 'prepare-build.py')
os.sync()
print(json.dumps(report,indent=2))
