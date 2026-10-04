#!/usr/bin/python3
"""Verify AK complete build against AJ and the frozen BOOST Switch guard candidate."""
import hashlib,json,os,re,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
X=BASE/'20260930ak';P=BASE/'20260930aj';B=X/'build'
RELEASE='7.3.0-rc2-spx-mainline-20260930ak+'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(root):return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}
def chunks(s):return {p.split(b'\n',1)[0]:p for p in re.split(b'(?=^diff --git )',s,flags=re.M) if p.startswith(b'diff --git ')}
assert os.geteuid()==0 and not (X/'independent-build-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='d3b9f9b1-7e95-4963-8225-adf840755102'
a=json.loads((X/'archive-review.json').read_text());h=json.loads((X/'build-sha256.json').read_text())
assert files(B)==h and sha(X/'build-sha256.json')==a['build_manifest_sha256']
symlinks={str(p.relative_to(B)):os.readlink(p) for p in B.rglob('*') if p.is_symlink()}
assert symlinks==json.loads((X/'build-symlinks.json').read_text())
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(B/'source.diff').read_bytes()
candidate=P/'boost-switch-guard-candidate'
assert (B/'source.diff').read_bytes()==(candidate/'source.diff').read_bytes()
assert sha(REPO/'sound/soc/codecs/wsa881x.c')==sha(candidate/'wsa881x.c')
review=json.loads((candidate/'independent-review.json').read_text())
assert review['sanitizers_passed'] and review['exact_C_differential_cases']==256 and review['native_codec_object_compile_exit_code']==0
before=chunks((P/'post-result-records/source.diff').read_bytes());after=chunks((B/'source.diff').read_bytes());key=b'diff --git a/sound/soc/codecs/wsa881x.c b/sound/soc/codecs/wsa881x.c'
assert {k:v for k,v in before.items() if k!=key}=={k:v for k,v in after.items() if k!=key}
before=set((P/'post-result-records/config').read_text().splitlines());after=set((REPO/'.config').read_text().splitlines())
assert before-after=={'CONFIG_LOCALVERSION="-spx-mainline-20260930aj"'}
assert after-before=={'CONFIG_LOCALVERSION="-spx-mainline-20260930ak"'}
assert (B/'config-extracted').read_bytes()==(REPO/'.config').read_bytes()==(B/'artifacts/.config').read_bytes()
assert sha(B/'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')=='5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
modules=json.loads((B/'module-sha256.json').read_text());root=B/'module-root/lib/modules'/RELEASE
assert len(modules)==202 and files(root)==modules and len(list(root.rglob('*.ko')))==187
vm=json.loads((B/'module-vermagic.json').read_text());assert len(vm)==187 and all(v.split()[0]==RELEASE for v in vm.values())
for n,d in a['boot_payload_sha256'].items():assert sha(B/n)==d,n
assert sha(B/'initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh')==sha(B/'logging/initrd-log.sh')==sha(P/'build/logging/initrd-log.sh')
for n,d in json.loads((X/'dtb-sha256.json').read_text()).items():assert sha(X/'dtb-build'/n)==d,n
params=subprocess.check_output(['modinfo','-F','parm',str(root/'kernel/drivers/soundwire/soundwire-qcom.ko')],text=True)
assert 'spx_cmd_diag:SPX: dump the last sixteen FIFO command submissions on at most two command errors (bool)' in params
report={'attempt':'20260930ak','preboot_id':a['preboot_id'],'release':RELEASE,'build_files_verified':len(h),'build_symlinks_verified':len(symlinks),'module_tree_files_verified':202,'module_vermagic_records_verified':187,'driver_delta':'detached BOOST Switch availability guard only','driver_sha256':sha(REPO/'sound/soc/codecs/wsa881x.c'),'config_delta':'LOCALVERSION only','other_source_diff_chunks_unchanged':True,'dtb_exact_ag':True,'embedded_config_exact':True,'private_initramfs_logger_exact':True,'functional_driver_policy_unchanged':False,'detached_boost_guard_verified':True,'command_history_records':16,'command_history_dumps':2,'command_diagnostic_maximum_log_lines':34,'build_manifest_sha256':sha(X/'build-sha256.json'),'boot_payload_sha256':a['boot_payload_sha256'],'boot_selected':False,'playback_requested':False}
(X/'independent-build-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
