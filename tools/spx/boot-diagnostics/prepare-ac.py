#!/usr/bin/python3
"""Archive exact AB artifacts for the one-selector AC native attachment trial."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
AB=BASE/'20260930ab'; AC=BASE/'20260930ac'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BID='094a2a10-d6cd-4e86-ba50-dd99bff8c6dd'
RELEASE='7.3.0-rc2-spx-mainline-20260930aa+'

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def files(p):
 return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}

def cmd(*args):return subprocess.check_output(args,text=True,timeout=90).strip()

assert os.geteuid()==0 and not AC.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert cmd('uname','-r')==RELEASE
assert 'spx_attempt=20260930ab' in Path('/proc/cmdline').read_text().split()
review=json.loads((AB/'independent-result-review.json').read_text())
assert review['boot_id']==BID and review['scoped_passed'] and review['fallback_stopped']
assert sha(AB/'independent-result-review.json')=='a1b691b5a139ed713d6b37a0b4e46156fc28f7dac2edc249696a130b3e410b23'
for n,d in json.loads((AB/'final-result/sha256.json').read_text()).items():assert sha(AB/'final-result'/n)==d,n
assert cmd('systemctl','show','spx-ab-fallback.timer','-p','ActiveState','--value')!='active'
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in cmd('efibootmgr')
a=json.loads((AB/'attempt.json').read_text())
for n,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==d,n
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(AB/'dtb-build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(AB/'build/artifacts/.config')
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:assert files(AB/tree)==json.loads((AB/mf).read_text())
links=json.loads((AB/'build-symlinks.json').read_text())
assert {str(p.relative_to(AB/'build')):os.readlink(p) for p in (AB/'build').rglob('*') if p.is_symlink()}==links
mods=json.loads((AB/'build/module-sha256.json').read_text());assert files(Path('/usr/lib/modules')/RELEASE)==mods
AC.mkdir(mode=0o700)
for n in ('build','dtb-build'):shutil.copytree(AB/n,AC/n,symlinks=True)
for n in ('build-sha256.json','build-symlinks.json','dtb-sha256.json'):shutil.copy2(AB/n,AC/n)
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:assert files(AC/tree)==json.loads((AC/mf).read_text())
report=json.loads((AB/'archive-review.json').read_text())
report.update({'attempt':'20260930ac','preboot_id':BID,'exact_dtb_delta':'none; exact AB DTB',
 'comparison':'Exact AB payloads; only force_attach 1 -> 0 and attempt marker',
 'prior_result_review_sha256':sha(AB/'independent-result-review.json'),
 'prior_enumeration_word_review_sha256':sha(AB/'enumeration-word-review.json'),
 'boot_selected':False,'playback_requested':False})
(AC/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
src=AC/'preparation-sources';src.mkdir()
for n in ('prepare-ac.py','AUDIO-AFTER-AB-20260930.md','RESULT-20260930ab.md'):shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n,src/n)
h=files(src);(AC/'preparation-sources-sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(src)==h
os.sync();print(json.dumps(report,indent=2))
