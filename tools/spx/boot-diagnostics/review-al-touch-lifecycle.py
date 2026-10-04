#!/usr/bin/python3
"""Freeze local source evidence and archived metadata for AL's lifecycle audit."""
import difflib,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al');out=run/'touch-lifecycle-audit'
assert os.geteuid()==0 and not out.exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^(?:static )?[^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
for d in ('final-result','post-result-records','recovery-return','reset-self-wait-candidate','reset-self-wait-candidate-v2'):
 root=run/d;h=json.loads((root/'sha256.json').read_text());assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}==h|{'sha256.json':sha(root/'sha256.json')}
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
a=json.loads((run/'attempt.json').read_text())
for p,h in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(p)==h,p
mods=json.loads((run/'build/module-sha256.json').read_text());assert len(mods)==202
for p,h in mods.items():assert sha(Path('/usr/lib/modules')/a['release']/p)==h,p
old=(run/'reset-self-wait-candidate-v2/spi-hid-core.before.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text()
assert sha(repo/'drivers/hid/spi-hid/spi-hid-core.c')==sha(run/'reset-self-wait-candidate-v2/spi-hid-core.c')
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==(run/'reset-self-wait-candidate-v2/source.diff').read_bytes()
assert (repo/'.config').read_bytes()==(run/'build/artifacts/.config').read_bytes()
registration=old[old.index('static struct spi_driver spi_hid_driver = {'):]
assert '.shutdown' not in registration and '.remove' in registration
probe=function(old,'spi_hid_probe');assert 'spi_hid_startup_arm(shid)' in probe and 'wait_for_completion' not in probe
reset=function(old,'spi_hid_reset_work');assert 'spi_hid_error_handler(shid)' in reset
handler=function(old,'spi_hid_error_handler');assert 'cancel_work_sync(&shid->reset_work)' in handler
bus=(repo/'drivers/spi/spi.c').read_text();assert 'if (sdrv->shutdown)' in function(bus,'spi_shutdown')
core=(repo/'drivers/base/core.c').read_text();assert 'dev->bus->shutdown(dev)' in function(core,'device_shutdown')
wq=(repo/'kernel/workqueue.c').read_text();assert '__flush_work(work, true)' in function(wq,'__cancel_work_sync')
assert '__cancel_work(work, 0)' in function(wq,'cancel_work')
r=json.loads((run/'final-result/result.json').read_text());assert not r['spi_hid_ready'] and r['native_force_off_path_passed']
irq=next(s for s in (run/'final-result/interrupts').read_text().splitlines() if s.endswith('spi0.0'))
assert all(int(s)==0 for s in irq.split()[1:9])
assert not (run/'final-result/iptsd-state').read_text().strip()
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
out.mkdir(mode=0o700)
(out/'self-wait.patch').write_text('diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c\n'+''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/drivers/hid/spi-hid/spi-hid-core.c',tofile='b/drivers/hid/spi-hid/spi-hid-core.c')))
with (out/'checkpatch.log').open('wb') as f:
 check=subprocess.run(['perl','scripts/checkpatch.pl','--no-tree','--strict','--no-signoff',str(out/'self-wait.patch')],cwd=repo,stdout=f,stderr=subprocess.STDOUT)
assert check.returncode==0,(out/'checkpatch.log').read_text()
for n in ('drivers/spi/spi.c','drivers/base/core.c','kernel/workqueue.c','include/linux/workqueue.h'):
 dest=out/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/n,dest)
for n in ('TOUCH-AFTER-AL-20260930.md','review-al-touch-lifecycle.py','verify-reset-self-wait.py'):shutil.copy2(repo/'tools/spx/boot-diagnostics'/n,out/n)
(out/'source-paths.txt').write_text('\n\n'.join(function(old,n) for n in ('spi_hid_probe','spi_hid_startup_work','spi_hid_reset_work','spi_hid_error_handler','spi_hid_shutdown'))+'\n\n'+function(bus,'spi_shutdown')+'\n\n'+function(wq,'__cancel_work_sync')+'\n\n'+function(wq,'current_work')+'\n')
report={'attempt':'20260930al','recovery_boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'archived_touch_IRQ_line':irq,'archived_iptsd_instance_absent':True,'probe_returns_before_HID_publication':True,'reboot_shutdown_callback_missing':True,'reset_worker_self_wait_source_path_verified':True,'candidate_uses_nonblocking_self_cancel_and_sync_other_contexts':True,'candidate_manifest_sha256':sha(run/'reset-self-wait-candidate-v2/sha256.json'),'actual_recovery_manifest_sha256':sha(run/'recovery-return/sha256.json'),'original_post_manifest_sha256':sha(run/'post-result-records/sha256.json'),'installed_AK_modules_payloads_and_recovery_unchanged':True,'checkpatch_exit_code':0,'next_entry_empty':True,'known_good_default':True,'hardware_startup_cause_established':False,'next_hardware_experiment_selected':False}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');h={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()};(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(out/n)==v for n,v in h.items());os.sync();print(json.dumps(report|{'audit_files':len(h),'audit_manifest_sha256':sha(out/'sha256.json')},indent=2))
