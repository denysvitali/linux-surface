#!/usr/bin/python3
"""Archive verified AE artifacts for a silent alternate-pin native trial."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
P=BASE/'20260930ae'; X=BASE/'20260930af'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BID='1b26cb6c-0e7f-4a3b-a290-f3bf44a6855c'
RELEASE='7.3.0-rc2-spx-mainline-20260930ae+'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def files(p):
 return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def cmd(*args):return subprocess.check_output(args,text=True,timeout=90).strip()
assert os.geteuid()==0 and not X.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert cmd('uname','-r')==RELEASE
assert 'spx_attempt=20260930ae' in Path('/proc/cmdline').read_text().split()
review=json.loads((P/'independent-result-review.json').read_text())
assert review['boot_id']==BID and review['scoped_passed'] and review['fallback_stopped']
assert review['touch_startup_clean'] and review['native_force_off_path_passed']
assert sha(P/'independent-result-review.json')=='194e6623767fa9a26194e9f1d4bd9b4f998377f21a97c74b514143e4335aa2bc'
assert sha(P/'touch-startup-review.json')=='e93278445715ea4e38a3bf9acd5b1c4f53356a38c75cff320abdd702383bfe28'
assert sha(P/'enumeration-word-review.json')=='82eac90648577d11577e3115fee1a12eebbb2b967972b859e0667ca23877fced'
root=P/'final-result'
assert files(root)==json.loads((root/'sha256.json').read_text())|{'sha256.json':sha(root/'sha256.json')}
assert cmd('systemctl','show','spx-ae-fallback.timer','-p','ActiveState','--value')!='active'
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in cmd('efibootmgr')
a=json.loads((P/'attempt.json').read_text())
assert a==json.loads((BASE.parent/'attempt.json').read_text())
for n,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==d,n
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(P/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(P/'build/artifacts/.config')
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:assert files(P/tree)==json.loads((P/mf).read_text())
links=json.loads((P/'build-symlinks.json').read_text())
assert {str(p.relative_to(P/'build')):os.readlink(p) for p in (P/'build').rglob('*') if p.is_symlink()}==links
mods=json.loads((P/'build/module-sha256.json').read_text());assert files(Path('/usr/lib/modules')/RELEASE)==mods
X.mkdir(mode=0o700)
for n in ('build','dtb-build'):shutil.copytree(P/n,X/n,symlinks=True)
for n in ('build-sha256.json','build-symlinks.json','dtb-sha256.json'):shutil.copy2(P/n,X/n)
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:assert files(X/tree)==json.loads((X/mf).read_text())
assert {str(p.relative_to(X/'build')):os.readlink(p) for p in (X/'build').rglob('*') if p.is_symlink()}==links
report=json.loads((P/'archive-review.json').read_text())
report['ae_build_parent_ad_post_result_manifest_sha256']=report.pop('parent_post_result_manifest_sha256')
report.update({'attempt':'20260930af','preboot_id':BID,'exact_dtb_delta':'none; exact AE/AB DTB',
 'comparison':'Exact AE payloads; only pin1 -> pin2 and attempt marker',
 'parent_result_review_sha256':sha(P/'independent-result-review.json'),
 'parent_touch_review_sha256':sha(P/'touch-startup-review.json'),
 'parent_enumeration_word_review_sha256':sha(P/'enumeration-word-review.json'),
 'parent_result_manifest_sha256':sha(P/'final-result/sha256.json'),
 'boot_selected':False,'deployed':False,'playback_requested':False})
(X/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
src=X/'preparation-sources';src.mkdir()
for n in ('prepare-af.py','generate-af.py','AUDIO-AFTER-AE-20260930.md','RESULT-20260930ae.md','review-ae-touch.py','review-ae-enumeration.py'):shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n,src/n)
h=files(src);(X/'preparation-sources-sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(src)==h
os.sync();print(json.dumps(report,indent=2))
