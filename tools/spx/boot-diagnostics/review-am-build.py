#!/usr/bin/python3
"""Independently verify AM full build provenance, exact scope and private payloads."""
import hashlib,json,os,re,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');BASE=Path('/var/lib/spx-boot-diagnostics/attempts');P=BASE/'20260930al';X=BASE/'20261001am';B=X/'build';R='7.3.0-rc2-spx-mainline-20261001am+';BID='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def chunks(s):return {p.split(b'\n',1)[0]:p for p in re.split(b'(?=^diff --git )',s,flags=re.M) if p.startswith(b'diff --git ')}
assert os.geteuid()==0 and not (X/'independent-build-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
a=json.loads((X/'archive-review.json').read_text());h=json.loads((X/'build-sha256.json').read_text());assert files(B)==h and sha(X/'build-sha256.json')==a['build_manifest_sha256']
l={str(q.relative_to(B)):os.readlink(q) for q in B.rglob('*') if q.is_symlink()};assert l==json.loads((X/'build-symlinks.json').read_text()) and sha(X/'build-symlinks.json')==a['build_symlink_manifest_sha256']
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(B/'source.diff').read_bytes()==(P/'reboot-quiesce-review-20261001/source.diff').read_bytes()
before=chunks((P/'build/source.diff').read_bytes());after=chunks((B/'source.diff').read_bytes());keys={b'diff --git a/drivers/hid/spi-hid/spi-hid-core.'+s+b' b/drivers/hid/spi-hid/spi-hid-core.'+s for s in (b'c',b'h')}
assert {k:v for k,v in before.items() if k not in keys}=={k:v for k,v in after.items() if k not in keys}
candidate=B/'reboot-quiesce-candidate-20261001';review=B/'reboot-quiesce-review-20261001'
for n in ('spi-hid-core.c','spi-hid-core.h'):assert (REPO/'drivers/hid/spi-hid'/n).read_bytes()==(candidate/n).read_bytes()==(review/n).read_bytes()
for name in ('worker-recovery-review-20261001','output-power-lock-candidate-20261001','reboot-quiesce-candidate-20261001','reboot-quiesce-review-20261001'):
 p=B/name;hs=json.loads((p/'sha256.json').read_text());assert files(p)==hs|{'sha256.json':sha(p/'sha256.json')};assert sha(p/'sha256.json')==sha(P/name/'sha256.json')
power=json.loads((B/'output-power-lock-candidate-20261001/independent-review.json').read_text());q=json.loads((candidate/'independent-review.json').read_text());assert power['sanitizers_passed'] and power['output_cases']==60 and power['unchanged_power_cases']==24;assert q['sanitizers_passed'] and q['actual_dispatch_cleanup_cases']==144 and q['absent_driver_or_callback_cases']==2
before=set((P/'build/artifacts/.config').read_text().splitlines());after=set((REPO/'.config').read_text().splitlines());assert before-after=={'CONFIG_LOCALVERSION="-spx-mainline-20260930ak"'} and after-before=={'CONFIG_LOCALVERSION="-spx-mainline-20261001am"'}
assert (B/'config-extracted').read_bytes()==(REPO/'.config').read_bytes()==(B/'artifacts/.config').read_bytes()
assert subprocess.check_output(['scripts/extract-ikconfig',str(B/'artifacts/arch/arm64/boot/Image')],cwd=REPO)==(B/'artifacts/.config').read_bytes()
assert sha(B/'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')=='5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
mods=json.loads((B/'module-sha256.json').read_text());root=B/'module-root/lib/modules'/R;assert len(mods)==202 and files(root)==mods
ko=sorted(root.rglob('*.ko'));vm=json.loads((B/'module-vermagic.json').read_text());assert len(ko)==len(vm)==187
for m in ko:assert subprocess.check_output(['modinfo','-F','vermagic',str(m)],text=True).strip()==vm[str(m.relative_to(root))] and vm[str(m.relative_to(root))].split()[0]==R
for n,d in a['boot_payload_sha256'].items():assert sha(B/n)==d,n
assert sha(B/'initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh')==sha(B/'logging/initrd-log.sh')==sha(P/'build/logging/initrd-log.sh')
for n,d in json.loads((X/'dtb-sha256.json').read_text()).items():assert sha(X/'dtb-build'/n)==d,n
source=json.loads((B/'build-complete.json').read_text())['source_sha256']
for n,d in source.items():assert sha(REPO/n)==d,n
assert source['sound/soc/codecs/wsa881x.c']=='e30ce5e45474e472031e647c17577f51547b944aa89292230ac58d169957bcc4' and source['drivers/soundwire/qcom.c']=='33aeace2b61741347c3015affa700c3ca875c6db719d1c19998252948253e83c'
params=subprocess.check_output(['modinfo','-F','parm',str(root/'kernel/drivers/soundwire/soundwire-qcom.ko')],text=True);assert 'spx_cmd_diag:' in params and 'spx_enum_diag:' in params
parent=json.loads((P/'attempt.json').read_text());installed=json.loads((P/'build/module-sha256.json').read_text())
for n,d in installed.items():assert sha(Path('/usr/lib/modules')/parent['release']/n)==d,n
for n,d in (parent['sha256']|parent['recovery_sha256']|parent['runtime_sha256']).items():assert sha(n)==d,n
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env;assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
assert not (Path('/usr/lib/modules')/R).exists()
report={'attempt':'20261001am','preboot_id':BID,'release':R,'build_files_verified':len(h),'build_symlinks_verified':len(l),'private_module_files_verified':202,'module_vermagic_records_verified':187,'other_source_diff_chunks_unchanged':True,'source_sha256':source,'config_delta':'LOCALVERSION only','config_sha256':sha(B/'artifacts/.config'),'source_diff_sha256':sha(B/'source.diff'),'audio_driver_policy_unchanged':True,'dtb_exact_ag':True,'embedded_config_exact':True,'private_initramfs_logger_exact':True,'output_cases':60,'unchanged_power_cases':24,'callback_dispatch_cleanup_cases':144,'absent_driver_callback_cases':2,'build_manifest_sha256':sha(X/'build-sha256.json'),'boot_payload_sha256':a['boot_payload_sha256'],'installed_parent_module_files_verified':len(installed),'payload_runtime_recovery_files_verified':15,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'deployed':False,'boot_selected':False,'callback_executed_on_hardware':False,'playback_requested':False,'efi_early_kernel_recovery_validated':False}
(X/'independent-build-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
