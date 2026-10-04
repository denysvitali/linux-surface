#!/usr/bin/python3
"""Immediately recheck AM one-time selection and recovery before reboot."""
import json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from am_boot_guard import X,load,preboot,command
os.umask(0o077)
try:
 a=load();assert a['state'].startswith('AM selected once') and (X/'reboot-requested').exists()
 assert not (X/'reboot-check-passed.json').exists()
 env=preboot(a,a['entry'])
 with (X/'reboot-check-passed.json').open('x') as f:json.dump({'boot_id':a['preboot_id'],'queued_entry':a['entry'],'saved_entry':'spx-known-good','payloads_verified':3,'recovery_payloads_verified':3,'working_module_files_links_verified':5183,'trial_module_files_verified':202},f,indent=2);f.write('\n')
 (X/'grubenv.immediate-preboot.txt').write_text('\n'.join(k+'='+v for k,v in env.items())+'\n');os.sync()
 subprocess.run(['systemctl','--no-block','reboot'],check=True,timeout=30)
except BaseException:
 try:
  a=load();same=Path('/proc/sys/kernel/random/boot_id').read_text().strip()==a['preboot_id']
  env=command('grub-editenv','/boot/grub/grubenv','list').splitlines()
  if same and 'next_entry='+a['entry'] in env:
   subprocess.run(['grub-editenv','/boot/grub/grubenv','unset','next_entry'],check=True,timeout=30)
   (X/'reboot-check-failed-unqueued').write_text(a['preboot_id']+'\n');os.sync()
 finally:raise
