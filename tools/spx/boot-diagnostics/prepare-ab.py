#!/usr/bin/python3
"""Archive AB's isolated left identity DTB with exact AA kernel/modules/initramfs."""
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077)
ROOT=Path('/var/lib/spx-boot-diagnostics/attempts')
AA=ROOT/'20260930aa'
AB=ROOT/'20260930ab'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BID='4c68904a-46a5-4eb8-a9ee-3991fbb3c243'
RELEASE='7.3.0-rc2-spx-mainline-20260930aa+'
DTS='arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi'
DTB=REPO/'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()

def files(root):
 return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}

def command(*args):
 return subprocess.check_output(args,text=True,cwd=REPO,timeout=90).strip()

assert os.geteuid()==0 and not AB.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert command('uname','-r')==RELEASE
assert 'spx_attempt=20260930aa' in Path('/proc/cmdline').read_text().split()
review=json.loads((AA/'independent-result-review.json').read_text())
assert review['boot_id']==BID and review['scoped_passed'] and review['fallback_stopped']
assert sha(AA/'independent-result-review.json')=='5010c5f182febbc6d1e1004c614662717ce8377f7d6f5da90f33dbac345ff7a2'
word=json.loads((AA/'enumeration-word-review.json').read_text())
assert len(word['transactions'])==1 and word['transactions'][0]['independent_decoded_id']['part']==0x2110
assert word['transactions'][0]['independent_decoded_id']['unique_id']==3
assert word['transactions'][0]['decoded_line_matches']
for n,h in json.loads((AA/'final-result/sha256.json').read_text()).items(): assert sha(AA/'final-result'/n)==h,n
assert command('systemctl','show','spx-aa-fallback.timer','-p','ActiveState','--value')!='active'
env=command('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
a=json.loads((AA/'attempt.json').read_text())
for n,h in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items(): assert sha(n)==h,n
assert sha(REPO/'.config')==sha(AA/'build/artifacts/.config')
old_marker='left_spkr: speaker@0,3 {\n\t\t\t\t\tcompatible = "sdw10217201000";'
new_marker=old_marker.replace('sdw10217201000','sdw10217211000')
src=(REPO/DTS).read_text()
assert src.count(new_marker)==1 and src.count('compatible = "sdw10217201000";')==1
old_src=src.replace(new_marker,old_marker)
assert hashlib.sha256(old_src.encode()).hexdigest()==json.loads((AA/'build/build-complete.json').read_text())['source_sha256'][DTS]
current_diff=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)
old_diff=(AA/'build/source.diff').read_bytes()
def without_dt(data):
 return b''.join(p for p in re.split(rb'(?=^diff --git )',data,flags=re.M) if not p.startswith(b'diff --git a/'+DTS.encode()+b' '))
assert without_dt(current_diff)==without_dt(old_diff)
old=subprocess.run(['dtc','-I','dtb','-O','dts',str(AA/'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')],capture_output=True,check=True).stdout
new=subprocess.run(['dtc','-I','dtb','-O','dts',str(DTB)],capture_output=True,check=True).stdout
assert old.count(b'compatible = "sdw10217201000";')==2
assert new==old.replace(b'compatible = "sdw10217201000";',b'compatible = "sdw10217211000";',1)
parent=json.loads((AA/'build-sha256.json').read_text())
parent_links=json.loads((AA/'build-symlinks.json').read_text())
assert files(AA/'build')==parent
assert {str(p.relative_to(AA/'build')):os.readlink(p) for p in (AA/'build').rglob('*') if p.is_symlink()}==parent_links
modules=json.loads((AA/'build/module-sha256.json').read_text())
assert files(Path('/usr/lib/modules')/RELEASE)==modules
AB.mkdir(mode=0o700)
shutil.copytree(AA/'build',AB/'build',symlinks=True)
for n in ('build-sha256.json','build-symlinks.json'): shutil.copy2(AA/n,AB/n)
assert files(AB/'build')==parent
work=AB/'dtb-build'; work.mkdir()
shutil.copy2(DTB,work/'spx.dtb')
shutil.copy2(AA/'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb',work/'parent-spx.dtb')
(work/'parent-sc8180x-wcd9340.dtsi').write_text(old_src)
shutil.copy2(REPO/DTS,work/'sc8180x-wcd9340.dtsi')
shutil.copy2(REPO/'.config',work/'config')
shutil.copy2('/var/tmp/spx-ab-dtb-build.log',work/'build.log')
(work/'command.json').write_text(json.dumps({'command':['make','-j6','qcom/sc8180x-surface-pro-x.dtb'],'exit_code':0,'config_exact_aa':True},indent=2)+'\n')
(work/'source.diff').write_bytes(current_diff)
(work/'source-status.txt').write_text(command('git','status','--short','--untracked-files=all')+'\n')
(work/'commit').write_text(command('git','rev-parse','HEAD')+'\n')
(work/'dtc-old.dts').write_bytes(old); (work/'dtc-new.dts').write_bytes(new)
for n in ('AUDIO-AFTER-AA-20260930.md','RESULT-20260930aa.md','prepare-ab.py'):
 shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n,work/n)
hashes=files(work)
(AB/'dtb-sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
assert files(work)==hashes
report={'attempt':'20260930ab','release':RELEASE,'preboot_id':BID,'build_files_verified':len(parent),
 'build_symlinks_verified':len(parent_links),'module_files_verified':len(modules),
 'build_manifest_sha256':sha(AB/'build-sha256.json'),'module_manifest_sha256':sha(AB/'build/module-sha256.json'),
 'dtb_manifest_sha256':sha(AB/'dtb-sha256.json'),'dtb_files_verified':len(hashes),
 'config_sha256':sha(work/'config'),'current_source_diff_sha256':sha(work/'source.diff'),
 'boot_payload_sha256':{'vmlinuz':sha(AB/'build/vmlinuz'),'initramfs.img':sha(AB/'build/initramfs.img'),'spx.dtb':sha(work/'spx.dtb')},
 'exact_dtb_delta':'left compatible 2010 -> 2110 only','other_source_diff_exact_aa':True,
 'prior_result_review_sha256':sha(AA/'independent-result-review.json'),
 'prior_enumeration_word_review_sha256':sha(AA/'enumeration-word-review.json'),
 'boot_selected':False,'playback_requested':False}
(AB/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
os.sync()
print(json.dumps(report,indent=2))
