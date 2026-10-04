#!/usr/bin/python3
"""Verify AL selection, accepting a completed reboot while preserving its proof."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
base=Path('/var/lib/spx-boot-diagnostics')
run=base/'attempts/20260930al'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cmd(*a):return subprocess.check_output(a,text=True,timeout=30).strip()
assert os.geteuid()==0 and not (run/'queue-review').exists()
a=json.loads((run/'attempt.json').read_text())
assert a==json.loads((base/'attempt.json').read_text())
assert a['state'].startswith('AL selected once') and (run/'reboot-requested').exists()
bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
env=cmd('grub-editenv','/boot/grub/grubenv','list')
assert 'saved_entry=spx-known-good' in env.splitlines() and 'BootNext:' not in cmd('efibootmgr')
for n,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==d,n
modules=json.loads((run/'build/module-sha256.json').read_text())
for n,d in modules.items():assert sha(Path('/usr/lib/modules')/a['release']/n)==d,n
executed=False
actual_trial=None
guard_log=''
if bid==a['preboot_id']:
    assert 'next_entry='+a['entry'] in env.splitlines()
    assert cmd('uname','-r')==a['release'] and 'spx_attempt=20260930ak' in Path('/proc/cmdline').read_text().split()
    active=cmd('systemctl','show','spx-trial-20260930al-reboot.timer','-p','ActiveState','--value')=='active'
    assert active or (run/'reboot-check-passed.json').exists()
    mode='pending one-shot reboot'
else:
    guard=json.loads((run/'reboot-check-passed.json').read_text())
    assert guard['boot_id']==a['preboot_id'] and guard['queued_entry']==a['entry'] and guard['saved_entry']=='spx-known-good'
    assert 'next_entry='+a['entry'] in (run/'grubenv.immediate-preboot.txt').read_text().splitlines()
    assert 'next_entry=' in env.splitlines()
    guard_log=cmd('journalctl','--boot='+a['preboot_id'].replace('-',''),'-u','spx-trial-20260930al-reboot.service','-o','short-monotonic','--no-pager')
    assert 'Started' in guard_log and 'Deactivated successfully' in guard_log and str(run/'reboot-check.py') in guard_log
    if 'spx_attempt=20260930al' in Path('/proc/cmdline').read_text().split():
        assert cmd('uname','-r')==a['release']
        assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20260930ak/vmlinuz']+a['cmdline'].split()
        actual_trial=bid
        mode='actual AL boot verified'
    else:
        assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
        root=run/'final-result'
        h=json.loads((root/'sha256.json').read_text())
        assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}==h|{'sha256.json':sha(root/'sha256.json')}
        result=json.loads((root/'result.json').read_text())
        assert result['attempt']=='20260930al' and result['release']==a['release']
        assert (root/'cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20260930ak/vmlinuz']+a['cmdline'].split()
        actual_trial=result['boot_id']
        assert (base/'boots'/actual_trial/'return-requested').read_text().strip()==actual_trial
        fallback=cmd('journalctl','--boot='+actual_trial.replace('-',''),'-u','spx-al-fallback.service','-o','short-monotonic','--no-pager')
        assert 'Evidence saved' in fallback and 'Deactivated successfully' in fallback
        mode='archived AL boot and fallback return verified'
    executed=True
out=run/'queue-review';out.mkdir(mode=0o700)
(out/'grubenv').write_text(env+'\n')
shutil.copy2(__file__,out/'review-al-selection.py')
if executed:
    shutil.copy2(run/'reboot-check-passed.json',out/'reboot-check-passed.json')
    (out/'guard-journal.log').write_text(guard_log+'\n')
report={'attempt':'20260930al','preboot_id':a['preboot_id'],'current_boot_id':bid,
        'actual_trial_boot_id':actual_trial,'selected_once':True,'verification_mode':mode,
        'guard_execution_verified':executed,'known_good_default':True,'efi_bootnext_absent':True,
        'payload_recovery_runtime_hashes_verified':15,'module_files_verified':len(modules),
        'final_hardware_result_verified':False}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
h={p.name:sha(p) for p in out.iterdir()};(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
assert all(sha(out/n)==d for n,d in h.items())
os.sync();print(json.dumps(report|{'records':len(h),'manifest_sha256':sha(out/'sha256.json')},indent=2))
