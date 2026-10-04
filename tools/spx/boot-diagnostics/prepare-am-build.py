#!/usr/bin/python3
"""Prepare a distinct AM build from AL baseline and reviewed SPI-HID candidates."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');parent=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al');stage=Path('/var/tmp/spx-mainline-trial-20261001am');bid='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in p.rglob('*') if q.is_file() and not q.is_symlink()}
assert os.geteuid()==0 and not stage.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid and 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
reviewroot=parent/'reboot-quiesce-review-20261001';review=json.loads((reviewroot/'report.json').read_text())
records={}
for name in ('final-result','post-result-records','recovery-return','worker-recovery-review-20261001','output-power-lock-candidate-20261001','reboot-quiesce-candidate-20261001','reboot-quiesce-review-20261001'):
 p=parent/name;h=json.loads((p/'sha256.json').read_text());assert files(p)==h|{'sha256.json':sha(p/'sha256.json')};records[name]=sha(p/'sha256.json')
assert review['final_output_power_functions_exact_tested'] and review['candidate_driver_sha256']=='74ae8e4d3d586fa7112622f4d85a800e83509b4cb876231b0afc79dc9ebc49b7'
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==(reviewroot/'source.diff').read_bytes()
assert (repo/'.config').read_bytes()==(reviewroot/'config').read_bytes()
assert json.loads((parent/'recovery-return/report.json').read_text())['recovery_boot_id']==bid
result=json.loads((parent/'independent-result-review.json').read_text());assert not result['scoped_passed'] and not result['fallback_stopped']
a=json.loads((parent/'attempt.json').read_text());assert a==json.loads((parent.parent.parent/'attempt.json').read_text())
for n,h in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==h,n
mods=json.loads((parent/'build/module-sha256.json').read_text())
for n,h in mods.items():assert sha(Path('/usr/lib/modules')/a['release']/n)==h,n
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
stage.mkdir(mode=0o700)
for n in ('logging','initcpio','command-source-review','boost-source-review'):shutil.copytree(parent/'build'/n,stage/n,symlinks=True)
for n in ('worker-recovery-review-20261001','output-power-lock-candidate-20261001','reboot-quiesce-candidate-20261001','reboot-quiesce-review-20261001'):shutil.copytree(parent/n,stage/n,symlinks=True)
hook=stage/'initcpio/install/spx_diagnostics';hook.write_text(hook.read_text().replace('20260930ak','20261001am'));shutil.copy2(parent/'build/mkinitcpio.conf',stage/'mkinitcpio.conf');c=stage/'mkinitcpio.conf';c.write_text(c.read_text().replace('20260930ak','20261001am'))
assert str(stage/'logging') in hook.read_text()
assert '20260930ak' not in c.read_text() and '20260930ak' not in hook.read_text()
shutil.copy2(repo/'.config',stage/'config-before');shutil.copy2(__file__,stage/'prepare-build.py')
report={'preboot_id':bid,'parent_attempt':'20260930al','parent_archives_rehashed':records,'installed_parent_module_files_verified':len(mods),'payload_runtime_recovery_files_verified':15,'known_good_default':True,'next_entry_empty':True,'boot_selected':False,'deployed':False}
(stage/'preparation-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
