#!/usr/bin/python3
"""Select reviewed AP once and schedule the immediate guard; never re-arm a request."""
import datetime,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ap_boot_guard import BASE,X,load,preboot,sha,files,command,frozen_prequeue
os.umask(0o077)
assert not (X/'reboot-requested').exists()
a=load();assert a['state']=='prepared AP; no boot selection'
review=json.loads((X/'installed-review.json').read_text());assert review['preboot_id']==a['preboot_id'] and not review['boot_selected']
assert review['modules_verified']==202 and review['working_module_files_links_verified']==5183 and review['build_files_verified']==1354
assert review['strict_am_scope_unchanged'] and review['known_good_default'] and review['next_entry_empty'] and review['efi_bootnext_absent']
for n,h in json.loads((X/'deployment-sources-sha256.json').read_text()).items():assert sha(Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')/n)==h,n
for n,h in json.loads((X/'preboot-snapshot/sha256.json').read_text()).items():assert sha(X/'preboot-snapshot'/n)==h,n
assert (X/'preboot-snapshot/boot-id').read_text().strip()==a['preboot_id']
native=json.loads((X/'native-continuation-review.json').read_text());assert native['boot_id']==a['preboot_id'] and native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage']=='continue' and native['lifecycleState']=='running' and native['legacy_resume_marker_absent'];os.kill(native['hostPid'],0)
for p in ('/boot/grub/grub.cfg','/boot/grub/custom.cfg'):subprocess.run(['grub-script-check',p],check=True,timeout=30)
preboot(a)
frozen_prequeue(a)
when=datetime.datetime.now(datetime.timezone.utc).isoformat()
with (X/'reboot-requested').open('x') as f:f.write(when+'\n'+a['preboot_id']+'\n');f.flush();os.fsync(f.fileno())
def save(p):
 tmp=p.with_name(p.name+'.ap-queue-new');assert not tmp.exists();tmp.write_text(json.dumps(a,indent=2)+'\n');os.replace(tmp,p)
try:
 subprocess.run(['grub-reboot',a['entry']],check=True,timeout=30)
 env=command('grub-editenv','/boot/grub/grubenv','list').splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry='+a['entry'] in env
 assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==a['preboot_id']
 (X/'grubenv.queued.txt').write_text('\n'.join(env)+'\n');a['state']='AP selected once; scheduled immediate guard will verify before reboot';a['reboot_requested_at']=when;save(X/'attempt.json');save(BASE/'attempt.json');os.sync()
 subprocess.run(['systemd-run','--unit=spx-trial-20261002ap-reboot','--on-active=30s','/usr/bin/python3',str(X/'reboot-check.py')],check=True,timeout=30)
 assert command('systemctl','is-active','spx-trial-20261002ap-reboot.timer')=='active'
 (X/'queue-review.json').write_text(json.dumps({'preboot_id':a['preboot_id'],'entry':a['entry'],'selected_once':True,'guarded_reboot_timer_active':True,'guard_delay_seconds':30,'known_good_default':True,'request_marker_exclusive':True},indent=2)+'\n');os.sync()
 print('AP selected once; guarded reboot scheduled in30 seconds. Known-good remains persistent default.')
except BaseException:
 current=command('grub-editenv','/boot/grub/grubenv','list').splitlines()
 if 'next_entry='+a['entry'] in current:subprocess.run(['grub-editenv','/boot/grub/grubenv','unset','next_entry'],check=True,timeout=30)
 a['state']='queue failed; exclusive request marker retained; inspect before any retry';save(X/'attempt.json');save(BASE/'attempt.json');os.sync();raise
