#!/usr/bin/python3
"""Archive exact AG corrected artifacts for the silent pin1 control."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
P=BASE/'20260930ag'; X=BASE/'20260930ah'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BID='43efd328-c5ba-48bf-9edf-797ccf268b1f'
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
assert cmd('uname','-r')=='6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
review=json.loads((P/'independent-result-review.json').read_text())
assert review['boot_id']=='06d871cf-3529-49e2-9c02-3b9256e6fb06' and not review['scoped_passed'] and not review['fallback_stopped']
assert review['scoped_failure_reasons']==['native bus/clock-stop path']
assert review['touch_startup_clean'] and review['firmware_identity_match_passed']
assert sha(P/'independent-result-review.json')=='007bdfaa7b76258d5cc941a8ea21cf428c53830a7a2775ecba07073b0772c6b9'
assert sha(P/'touch-startup-review.json')=='8376cbf27b9e190f4e73cf36b52d156f527106c598d8f52be1b90bb78ee7a1c6'
assert sha(P/'enumeration-word-review.json')=='4625ee9e196f2e2beacfcc4804c4558515e23625f846a6e73d35e6c84ad6fad2'
recovery=json.loads((P/'recovery-return/report.json').read_text())
assert recovery['recovery_boot_id']==BID and recovery['userspace_fallback_return_verified']
for directory in ('post-result-records','recovery-return'):
 d=P/directory;assert files(d)==json.loads((d/'sha256.json').read_text())|{'sha256.json':sha(d/'sha256.json')}
root=P/'final-result'
assert files(root)==json.loads((root/'sha256.json').read_text())|{'sha256.json':sha(root/'sha256.json')}
assert cmd('systemctl','show','spx-ag-fallback.timer','-p','ActiveState','--value')!='active'
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in cmd('efibootmgr')
a=json.loads((P/'attempt.json').read_text())
assert a==json.loads((BASE.parent/'attempt.json').read_text())
for n,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==d,n
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(P/'dtb-build/source.diff').read_bytes()
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
report['ag_prior_af_recovery_manifest_sha256']=report.pop('prior_recovery_manifest_sha256')
report.update({'attempt':'20260930ah','preboot_id':BID,'exact_dtb_delta':'none; exact AG corrected DTB',
 'comparison':'Exact AG payloads; only pin2 -> pin1 and attempt marker',
 'parent_result_review_sha256':sha(P/'independent-result-review.json'),
 'parent_touch_review_sha256':sha(P/'touch-startup-review.json'),
 'parent_enumeration_word_review_sha256':sha(P/'enumeration-word-review.json'),
 'parent_result_manifest_sha256':sha(P/'final-result/sha256.json'),
 'parent_recovery_manifest_sha256':sha(P/'recovery-return/sha256.json'),
 'parent_post_result_manifest_sha256':sha(P/'post-result-records/sha256.json'),
 'boot_selected':False,'deployed':False,'playback_requested':False})
(X/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
src=X/'preparation-sources';src.mkdir()
for n in ('prepare-ah.py','generate-ah.py','AUDIO-AFTER-AG-20260930.md','RESULT-20260930ag.md','review-ag-touch.py','review-ag-enumeration.py','review-ag-command-errors.py','archive-ag-return.py'):shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n,src/n)
h=files(src);(X/'preparation-sources-sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(src)==h
os.sync();print(json.dumps(report,indent=2))
