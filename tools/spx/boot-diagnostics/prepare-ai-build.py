#!/usr/bin/python3
"""Prepare AI private logging and reviewed source without selecting a boot."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
P=Path('/var/lib/spx-boot-diagnostics/attempts/20260930ah')
S=Path('/var/tmp/spx-mainline-trial-20260930ai')
BID='b1485998-0a40-46b7-bd77-88796fa99a89'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert os.geteuid()==0 and not S.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert 'spx_attempt=20260930ah' in Path('/proc/cmdline').read_text().split()
review=json.loads((P/'independent-result-review.json').read_text())
assert review['boot_id']==BID and review['scoped_passed'] and review['fallback_stopped']
assert sha(P/'independent-result-review.json')=='ab33bf28d19b27a6bc4a4aea532c3d2e761857b2df15f00409a9466bfbdc4698'
for directory in ('final-result','post-result-records','command-history-candidate'):
 root=P/directory;h=json.loads((root/'sha256.json').read_text())
 assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}==h|{'sha256.json':sha(root/'sha256.json')}
a=json.loads((P/'attempt.json').read_text());assert a==json.loads((P.parent.parent/'attempt.json').read_text())
for n,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==d,n
candidate=P/'command-history-candidate/validation'
assert sha(REPO/'drivers/soundwire/qcom.c')==json.loads((candidate/'independent-review.json').read_text())['driver_sha256']
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(candidate/'source.diff').read_bytes()
assert sha(REPO/'.config')==sha(P/'post-result-records/config-before')
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
S.mkdir(mode=0o700)
for n in ('logging','initcpio'):shutil.copytree(P/'build'/n,S/n,symlinks=True)
hook=S/'initcpio/install/spx_diagnostics';hook.write_text(hook.read_text().replace('20260930ae','20260930ai'))
shutil.copy2(P/'build/mkinitcpio.conf',S/'mkinitcpio.conf')
c=S/'mkinitcpio.conf';c.write_text(c.read_text().replace('20260930ae','20260930ai'))
shutil.copy2(REPO/'.config',S/'config-before')
shutil.copytree(candidate,S/'command-source-review')
report={'preboot_id':BID,'parent_attempt':'20260930ah','parent_result_manifest_sha256':sha(P/'final-result/sha256.json'),'parent_post_result_manifest_sha256':sha(P/'post-result-records/sha256.json'),'candidate_manifest_sha256':sha(P/'command-history-candidate/sha256.json'),'candidate_driver_sha256':sha(REPO/'drivers/soundwire/qcom.c'),'boot_selected':False}
(S/'preparation-review.json').write_text(json.dumps(report,indent=2)+'\n')
shutil.copy2(__file__,S/'prepare-build.py');os.sync();print(json.dumps(report,indent=2))
