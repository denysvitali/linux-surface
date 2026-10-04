#!/usr/bin/python3
"""Archive exact verified AK artifacts for the isolated silent pin1 control."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS']='0'
base=Path('/var/lib/spx-boot-diagnostics/attempts')
parent=base/'20260930ak'
out=base/'20260930al'
repo=Path('/home/dvitali/Documents/git/linux-surface-next')
bid='db98e8ac-8aa3-44d4-8899-47c4fab5fb07'
release='7.3.0-rc2-spx-mainline-20260930ak+'
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p):
    return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def cmd(*a):
    return subprocess.check_output(a,text=True,timeout=90).strip()
assert os.geteuid()==0 and not out.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid
assert cmd('uname','-r')==release and 'spx_attempt=20260930ak' in Path('/proc/cmdline').read_text().split()
review=json.loads((parent/'independent-result-review.json').read_text())
assert review['boot_id']==bid and review['scoped_passed'] and review['fallback_stopped']
assert not review['scoped_failure_reasons'] and review['firmware_identity_match_passed']
for directory in ('final-result','post-result-records','startup-discovery','boot-transition-review'):
    root=parent/directory
    h=json.loads((root/'sha256.json').read_text())
    assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}
assert cmd('systemctl','show','spx-ak-fallback.timer','-p','ActiveState','--value')!='active'
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in cmd('efibootmgr')
a=json.loads((parent/'attempt.json').read_text())
assert a==json.loads((base.parent/'attempt.json').read_text())
for n,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():
    assert sha(n)==d,n
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==(parent/'build/source.diff').read_bytes()
assert sha(repo/'.config')==sha(parent/'build/artifacts/.config')
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:
    assert files(parent/tree)==json.loads((parent/mf).read_text())
links=json.loads((parent/'build-symlinks.json').read_text())
assert {str(p.relative_to(parent/'build')):os.readlink(p) for p in (parent/'build').rglob('*') if p.is_symlink()}==links
modules=json.loads((parent/'build/module-sha256.json').read_text())
assert len(modules)==202 and files(Path('/usr/lib/modules')/release)==modules
out.mkdir(mode=0o700)
for name in ('build','dtb-build'):
    shutil.copytree(parent/name,out/name,symlinks=True)
for name in ('build-sha256.json','build-symlinks.json','dtb-sha256.json'):
    shutil.copy2(parent/name,out/name)
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:
    assert files(out/tree)==json.loads((out/mf).read_text())
assert {str(p.relative_to(out/'build')):os.readlink(p) for p in (out/'build').rglob('*') if p.is_symlink()}==links
report=json.loads((parent/'archive-review.json').read_text())
report.update({'attempt':'20260930al','preboot_id':bid,'release':release,
               'functional_policy_unchanged':True,'functional_delta':'none; exact AK artifacts/source/config',
               'comparison':'Exact AK payloads; only pin2 -> pin1 and attempt marker',
               'parent_archive_review_sha256':sha(parent/'archive-review.json'),
               'parent_result_review_sha256':sha(parent/'independent-result-review.json'),
               'parent_touch_review_sha256':sha(parent/'touch-startup-review.json'),
               'parent_enumeration_word_review_sha256':sha(parent/'enumeration-word-review.json'),
               'parent_result_manifest_sha256':sha(parent/'final-result/sha256.json'),
               'parent_post_result_manifest_sha256':sha(parent/'post-result-records/sha256.json'),
               'boot_selected':False,'deployed':False,'playback_requested':False})
(out/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
shutil.copy2(__file__,out/'prepare-al.py')
os.sync()
print(json.dumps(report,indent=2))
