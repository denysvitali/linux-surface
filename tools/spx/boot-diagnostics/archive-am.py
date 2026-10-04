#!/usr/bin/python3
"""Archive verified AM source/config/kernel/modules/DTB/initramfs without deployment."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');BASE=Path('/var/lib/spx-boot-diagnostics/attempts');P=BASE/'20260930al';X=BASE/'20261001am';S=Path('/var/tmp/spx-mainline-trial-20261001am');R='7.3.0-rc2-spx-mainline-20261001am+';BID='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def links(p):return {str(q.relative_to(p)):os.readlink(q) for q in sorted(p.rglob('*')) if q.is_symlink()}
assert os.geteuid()==0 and not X.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID and 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
pre=json.loads((S/'preparation-review.json').read_text())
for n,h in pre['parent_archives_rehashed'].items():
 p=P/n;assert sha(p/'sha256.json')==h;hs=json.loads((p/'sha256.json').read_text());assert files(p)==hs|{'sha256.json':sha(p/'sha256.json')}
a=json.loads((P/'attempt.json').read_text())
for n,h in (a['sha256']|a['runtime_sha256']|a['recovery_sha256']).items():assert sha(n)==h,n
v=json.loads((S/'build-verification.json').read_text());built=json.loads((S/'build-complete.json').read_text());assert v['release']==built['release']==R
assert v['modules']==187 and v['module_tree_files']==202 and v['private_logger_exact'] and v['embedded_config_exact']
assert (S/'config-extracted').read_bytes()==(S/'artifacts/.config').read_bytes()==(REPO/'.config').read_bytes()
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(S/'source.diff').read_bytes()==(P/'reboot-quiesce-review-20261001/source.diff').read_bytes()
for n,h in built['source_sha256'].items():assert sha(REPO/n)==h,n
for n,h in v['artifacts'].items():assert sha(S/n)==h,n
assert sha(S/'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')=='5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
mods=json.loads((S/'module-sha256.json').read_text());assert files(S/'module-root/lib/modules'/R)==mods and len(mods)==202
params=subprocess.check_output(['modinfo','-F','parm',str(S/'module-root/lib/modules'/R/'kernel/drivers/soundwire/soundwire-qcom.ko')],text=True)
assert 'spx_enum_diag:SPX: log at most eight enumerator-table transactions per controller (bool)' in params
assert 'spx_cmd_diag:SPX: dump the last sixteen FIFO command submissions on at most two command errors (bool)' in params
X.mkdir(mode=0o700);shutil.copytree(S,X/'build',symlinks=True);shutil.copytree(P/'dtb-build',X/'dtb-build',symlinks=True);shutil.copy2(P/'dtb-sha256.json',X/'dtb-sha256.json');assert files(X/'dtb-build')==json.loads((X/'dtb-sha256.json').read_text())
h=files(X/'build');l=links(X/'build');(X/'build-sha256.json').write_text(json.dumps(h,indent=2)+'\n');(X/'build-symlinks.json').write_text(json.dumps(l,indent=2)+'\n');assert files(X/'build')==h and links(X/'build')==l
shutil.copy2(__file__,X/'archive-am.py')
report={'attempt':'20261001am','release':R,'preboot_id':BID,'build_files_verified':len(h),'build_symlinks_verified':len(l),'module_files_verified':202,'build_manifest_sha256':sha(X/'build-sha256.json'),'build_symlink_manifest_sha256':sha(X/'build-symlinks.json'),'module_manifest_sha256':sha(X/'build/module-sha256.json'),'source_diff_sha256':sha(X/'build/source.diff'),'config_sha256':sha(X/'build/artifacts/.config'),'boot_payload_sha256':v['artifacts'],'dtb_exact_ag':True,'dtb_manifest_sha256':sha(X/'dtb-sha256.json'),'dtb_files_verified':len(files(X/'dtb-build')),'source_unchanged_during_build':True,'embedded_config_exact':True,'parent_attempt':'20260930al','parent_result_review_sha256':sha(P/'independent-result-review.json'),'parent_touch_review_sha256':sha(P/'touch-startup-review.json'),'parent_post_result_manifest_sha256':sha(P/'post-result-records/sha256.json'),'parent_reboot_quiesce_review_manifest_sha256':sha(P/'reboot-quiesce-review-20261001/sha256.json'),'functional_delta':'SPI-HID worker recovery/publisher drain/output-power exclusion/shared packet ownership/reboot shutdown callback','audio_driver_policy_unchanged':True,'startup_diag_windows':8,'startup_diag_events_per_window':48,'command_history_records':16,'command_history_dumps':2,'boot_selected':False,'deployed':False,'playback_requested':False,'callback_executed_on_hardware':False}
(X/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
