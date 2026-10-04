#!/usr/bin/python3
"""Freeze AK's actual reboot guard and independently verify boot transition."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics')
X=BASE/'attempts/20260930ak'
BID='db98e8ac-8aa3-44d4-8899-47c4fab5fb07'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cmd(*a):return subprocess.check_output(a,text=True,timeout=90).strip()
assert os.geteuid()==0 and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
a=json.loads((X/'attempt.json').read_text());assert a==json.loads((BASE/'attempt.json').read_text())
assert a['preboot_id']=='d3b9f9b1-7e95-4963-8225-adf840755102' and a['attempt']=='20260930ak'
assert a['state'].startswith('AK selected once')
assert cmd('uname','-r')==a['release']
assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20260930ak/vmlinuz']+a['cmdline'].split()
for p,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(p)==d,p
mods=json.loads((X/'build/module-sha256.json').read_text())
assert len(mods)==202
for p,d in mods.items():assert sha(Path('/usr/lib/modules')/a['release']/p)==d,p
guard=json.loads((X/'reboot-check-passed.json').read_text())
assert guard=={'boot_id':a['preboot_id'],'queued_entry':a['entry'],'saved_entry':'spx-known-good','payloads_verified':3,'recovery_files_verified':3,'module_files_verified':202}
assert 'next_entry='+a['entry'] in (X/'grubenv.immediate-preboot.txt').read_text().splitlines()
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in cmd('efibootmgr')
log=cmd('journalctl','--boot='+a['preboot_id'].replace('-',''),'-u','spx-trial-20260930ak-reboot.service','-o','short-monotonic','--no-pager')
assert 'Started' in log and 'Deactivated successfully' in log and str(X/'reboot-check.py') in log
out=X/'boot-transition-review';assert not out.exists();out.mkdir(mode=0o700)
for n in ('reboot-check-passed.json','grubenv.immediate-preboot.txt','reboot-check.py'):shutil.copy2(X/n,out/n)
(out/'guard-journal.log').write_text(log+'\n')
report={'attempt':'20260930ak','preboot_id':a['preboot_id'],'actual_trial_boot_id':BID,'actual_transition_verified':True,'payload_recovery_runtime_hashes_verified':15,'module_files_verified':202,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'efi_early_kernel_recovery_validated':False}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
h={p.name:sha(p) for p in out.iterdir()};(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(out/n)==d for n,d in h.items());os.sync();print(json.dumps(report|{'manifest_sha256':sha(out/'sha256.json')},indent=2))
