#!/usr/bin/python3
"""Check AM compressed Image and all embedded initramfs modules independently."""
import gzip,hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
X=Path('/var/lib/spx-boot-diagnostics/attempts/20261001am');B=X/'build';R='7.3.0-rc2-spx-mainline-20261001am+';P=X.parent/'20260930al/build';out=X/'initramfs-payload-review.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert os.geteuid()==0 and not out.exists()
assert gzip.decompress((B/'vmlinuz').read_bytes())==(B/'artifacts/arch/arm64/boot/Image').read_bytes()
ex=B/'initramfs-extracted';parent=P/'initramfs-extracted';prefix='usr/lib/modules/'+R+'/'
ko=sorted(ex.rglob('*.ko'));old=sorted(parent.rglob('*.ko'));assert len(ko)==len(old)==54
expected={str(n.relative_to(parent)).split('/kernel/',1)[1] for n in old};current={str(n.relative_to(ex)).split('/kernel/',1)[1] for n in ko};assert expected==current
releases=sorted(p.name for p in (ex/'usr/lib/modules').iterdir());assert releases==[R]
records={}
for m in ko:
 name=str(m.relative_to(ex));assert name.startswith(prefix)
 full=B/'module-root/lib/modules'/R/name[len(prefix):];assert sha(m)==sha(full),name
 value=subprocess.check_output(['modinfo','-F','vermagic',str(m)],text=True).strip();assert value.split()[0]==R
 records[name]={'sha256':sha(m),'vermagic':value}
for n in ('logging/initrd-log.sh','logging/initrd-log.service'):
 assert (B/n).read_bytes()==(P/n).read_bytes()
hook=(B/'initcpio/install/spx_diagnostics').read_text();assert hook==(P/'initcpio/install/spx_diagnostics').read_text().replace('20260930ak','20261001am');assert str(Path('/var/tmp/spx-mainline-trial-20261001am/logging')) in hook and '20260930ak' not in hook
assert (B/'mkinitcpio.conf').read_text()==(P/'mkinitcpio.conf').read_text().replace('20260930ak','20261001am')
report={'attempt':'20261001am','release':R,'compressed_kernel_exact_image':True,'initramfs_module_count':len(ko),'embedded_module_paths_match_parent':True,'embedded_module_payloads_exact_private_staged_modules':True,'embedded_module_releases':[R],'private_logging_hook_exact_except_path':True,'mkinitcpio_config_exact_except_path':True,'embedded_modules':records,'boot_selected':False,'deployed':False}
out.write_text(json.dumps(report,indent=2)+'\n');shutil.copy2(__file__,X/'review-am-initramfs.py');os.sync();print(json.dumps({k:v for k,v in report.items() if k!='embedded_modules'},indent=2))
