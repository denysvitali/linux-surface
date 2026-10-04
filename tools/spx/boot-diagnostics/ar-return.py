#!/usr/bin/python3
"""Only return the actual AR boot after900s and fresh known-good recovery checks."""
import json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ar_boot_guard import X,load,recovery
os.umask(0o077)
a=load();bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert bid!=a['preboot_id'] and os.uname().release==a['release']
assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20261003ar/vmlinuz']+a['cmdline'].split()
uptime=float(Path('/proc/uptime').read_text().split()[0]);assert uptime>=900
assert not (X/'fallback-recovery-check.json').exists()
env=recovery(a);assert not env.get('next_entry','')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid
with (X/'fallback-recovery-check.json').open('x') as f:json.dump({'boot_id':bid,'uptime_seconds':uptime,'known_good_payloads_modules_entry_verified':True,'next_entry_empty':True,'efi_bootnext_absent':True},f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
os.sync()
# Shared return path collects evidence and rechecks actual boot ID/selection again.
subprocess.run(['/usr/local/lib/spx-boot-diagnostics/return.sh'],check=True,timeout=120)
