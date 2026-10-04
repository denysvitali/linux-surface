#!/usr/bin/python3
"""Freeze AM final offline review, current recovery snapshots and handoff sources."""
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');X=Path('/var/lib/spx-boot-diagnostics/attempts/20261001am');P=X.parent/'20260930al';OUT=X/'offline-build-records-20261001';B=X/'build';BID='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert os.geteuid()==0 and not OUT.exists()
a=json.loads((X/'independent-build-review.json').read_text());v=json.loads((X/'initramfs-payload-review.json').read_text());parent=json.loads((P/'attempt.json').read_text());assert a['build_files_verified']==1354 and v['initramfs_module_count']==54 and v['compressed_kernel_exact_image']
assert sha(X/'build-sha256.json')==a['build_manifest_sha256']
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(B/'source.diff').read_bytes()
assert (REPO/'.config').read_bytes()==(B/'artifacts/.config').read_bytes()
for n,h in a['source_sha256'].items():assert sha(REPO/n)==h,n
for n,h in (parent['sha256']|parent['runtime_sha256']|parent['recovery_sha256']).items():assert sha(n)==h,n
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID and 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True);assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
efi=subprocess.check_output(['efibootmgr'],text=True);assert 'BootNext:' not in efi
assert not (Path('/usr/lib/modules')/a['release']).exists()
subprocess.run(['git','diff','--check'],cwd=REPO,check=True)
OUT.mkdir(mode=0o700)
for name in ('BUILD-20261001am.md','AM-PLAN-20261001.md','TOUCH-REBOOT-QUIESCE-20261001.md','prepare-am-build.py','build-am.py','assemble-am.py','archive-am.py','review-am-build.py','review-am-initramfs.py','freeze-am-offline-build.py'):shutil.copy2(REPO/'tools/spx/boot-diagnostics'/name,OUT/name)
for name in ('LOCAL-PROGRESS.md','AGENTS.md'):shutil.copy2(REPO/name,OUT/name)
for name in ('archive-review.json','independent-build-review.json','initramfs-payload-review.json'):shutil.copy2(X/name,OUT/name)
shutil.copytree(X/'initramfs-review-first-failure',OUT/'initramfs-review-first-failure')
shutil.copy2(REPO/'.config',OUT/'config');shutil.copy2(B/'source.diff',OUT/'source.diff');shutil.copy2(P/'attempt.json',OUT/'parent-attempt.json')
for name in ('spi-hid-core.c','spi-hid-core.h'):shutil.copy2(REPO/'drivers/hid/spi-hid'/name,OUT/name)
recovery=OUT/'recovery-payloads';recovery.mkdir();saved={}
for n,h in parent['recovery_sha256'].items():
 dst=recovery/Path(n).name;assert not dst.exists();shutil.copy2(n,dst);assert sha(dst)==h;saved[n]={'private_copy':str(dst.relative_to(OUT)),'sha256':h}
(OUT/'grubenv.txt').write_text(env);(OUT/'efibootmgr.txt').write_text(efi);(OUT/'boot-id.txt').write_text(BID+'\n');shutil.copy2('/proc/cmdline',OUT/'cmdline.txt');(OUT/'release.txt').write_text(os.uname().release+'\n')
warnings={}
for n in ('image-dtb.log','modules.log','modules-stage.log','depmod.log','initramfs-build.log'):
 lines=[s for s in (B/n).read_text(errors='replace').splitlines() if re.search(r'warning:|error:|WARNING:|ERROR:',s)]
 warnings[n]=lines
 if n!='initramfs-build.log':assert not lines
assert warnings['initramfs-build.log']==[s for s in (P/'build/initramfs-build.log').read_text(errors='replace').splitlines() if re.search(r'WARNING:|ERROR:',s)]
capacity=os.statvfs('/boot');sizes={n:(B/n).stat().st_size for n in ('vmlinuz','initramfs.img','artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')}
report={'attempt':'20261001am','release':a['release'],'current_boot_id':BID,'current_release':os.uname().release,'build_manifest_sha256':a['build_manifest_sha256'],'independent_build_review_sha256':sha(X/'independent-build-review.json'),'initramfs_payload_review_sha256':sha(X/'initramfs-payload-review.json'),'source_diff_sha256':sha(OUT/'source.diff'),'config_sha256':sha(OUT/'config'),'recovery_private_copies':saved,'payload_runtime_recovery_files_verified':15,'inherited_build_warnings':warnings,'payload_sizes_bytes':sizes,'boot_payload_bytes':sum(sizes.values()),'boot_free_bytes':capacity.f_bavail*capacity.f_frsize,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'boot_selected':False,'deployed':False,'slot_retired':False,'reboot_performed':False,'callback_executed_on_hardware':False,'efi_early_kernel_recovery_validated':False,'initial_touch_failure_resolved':False,'next_step':'Preserve and prove inactive boot-slot retirement, deploy AM with pin2 reference and unchanged strict620/900 criteria, then one-time trial selection after fresh reviews. Collect actual result before choosing any follow-up.'}
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');h={str(q.relative_to(OUT)):sha(q) for q in sorted(OUT.rglob('*')) if q.is_file() and not q.is_symlink()};(OUT/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(OUT/n)==d for n,d in h.items());os.sync();print(json.dumps(report|{'record_files':len(h),'record_manifest_sha256':sha(OUT/'sha256.json')},indent=2))
