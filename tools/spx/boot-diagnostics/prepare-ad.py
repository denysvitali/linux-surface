#!/usr/bin/python3
"""Archive exact AC artifacts for AD after verified failed-touch return."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
AB=BASE/'20260930ac'; AC=BASE/'20260930ad'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BID='2b761569-5b25-4ec5-a67e-f960c8fea28d'
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
assert cmd('uname','-r')=='6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
review=json.loads((AB/'independent-result-review.json').read_text())
assert review['boot_id']=='ef072ab7-3596-41c1-bf4f-ff4a5164737f'
assert not review['scoped_passed'] and not review['fallback_stopped']
assert review['native_force_off_path_passed']
assert review['scoped_failure_reasons']==['graphics/Wi-Fi/touch baseline']
assert sha(AB/'independent-result-review.json')=='bebcec4f022e23588d1162748e2991c1c43000b90f357c483ca309b24e0bb84e'
result=json.loads((AB/'final-result/result.json').read_text())
assert not result['spi_hid_ready'] and result['fd680_renderer'] and result['wifi_connected']
for directory in ('final-result','recovery-return','touch-failure-snapshot'):
 root=AB/directory
 assert files(root)==json.loads((root/'sha256.json').read_text())|{'sha256.json':sha(root/'sha256.json')}
recovery=json.loads((AB/'recovery-return/report.json').read_text())
assert recovery['recovery_boot_id']==BID and recovery['userspace_fallback_return_verified']
assert sha(AB/'recovery-return/sha256.json')=='739c6264c1762499f014b692c947c0519823c7c848ee9f72064ceb5ec0e404d9'
assert cmd('systemctl','show','spx-ac-fallback.timer','-p','ActiveState','--value')!='active'
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
report.update({'attempt':'20260930ad','preboot_id':BID,'exact_dtb_delta':'none; exact AB DTB',
 'comparison':'Exact AC payloads; only startup_diag 0 -> 1 and attempt marker',
 'prior_result_review_sha256':sha(AB/'independent-result-review.json'),
 'prior_enumeration_word_review_sha256':sha(AB/'enumeration-word-review.json'),
 'prior_recovery_manifest_sha256':sha(AB/'recovery-return/sha256.json'),
 'boot_selected':False,'playback_requested':False})
(AC/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
src=AC/'preparation-sources';src.mkdir()
for n in ('prepare-ad.py','generate-ad.py','AUDIO-AFTER-AC-20260930.md','RESULT-20260930ac.md','archive-ac-return.py'):shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n,src/n)
h=files(src);(AC/'preparation-sources-sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(src)==h
os.sync();print(json.dumps(report,indent=2))
