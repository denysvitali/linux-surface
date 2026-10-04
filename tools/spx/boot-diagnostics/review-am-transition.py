#!/usr/bin/python3
"""Freeze the consumed AM one-time selection and verified recovery state."""
import json, os, shutil, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from am_boot_guard import X, load, recovery, artifacts, command, sha
os.umask(0o077)
BID = '6dfad462-25b7-4e5e-90fc-3bd18c1c3095'
a = load()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert os.uname().release == a['release'] and BID != a['preboot_id']
assert Path('/proc/cmdline').read_text().split() == ['BOOT_IMAGE=/spx-trial-20261001am/vmlinuz'] + a['cmdline'].split()
assert a['state'].startswith('AM selected once')
env = recovery(a)
assert env.get('next_entry', '') == ''
artifacts(a)
proof = json.loads((X/'reboot-check-passed.json').read_text())
assert proof == dict(boot_id=a['preboot_id'], queued_entry=a['entry'], saved_entry='spx-known-good', payloads_verified=3, recovery_payloads_verified=3, working_module_files_links_verified=5183, trial_module_files_verified=202)
assert 'next_entry='+a['entry'] in (X/'grubenv.immediate-preboot.txt').read_text().splitlines()
log = command('journalctl', '--boot='+a['preboot_id'].replace('-', ''), '-u', 'spx-trial-20261001am-reboot.service', '-o', 'short-monotonic', '--no-pager')
assert 'Started' in log and 'Deactivated successfully' in log and str(X/'reboot-check.py') in log
out = X/'boot-transition-review'
assert not out.exists()
out.mkdir(mode=0o700)
for n in ('reboot-check-passed.json', 'grubenv.immediate-preboot.txt', 'reboot-check.py', 'working-recovery.json'):
    shutil.copy2(X/n, out/n)
(out/'guard-journal.log').write_text(log+'\n')
(out/'grubenv').write_text(command('grub-editenv', '/boot/grub/grubenv', 'list')+'\n')
report = dict(attempt=a['attempt'], preboot_id=a['preboot_id'], actual_trial_boot_id=BID, actual_transition_verified=True, payload_recovery_runtime_hashes_verified=17, trial_module_files_verified=202, working_module_files_links_verified=5183, known_good_default=True, next_entry_empty=True, efi_bootnext_absent=True, efi_early_kernel_recovery_validated=False)
(out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
shutil.copy2(__file__, out/Path(__file__).name)
h = {p.name: sha(p) for p in out.iterdir()}
(out/'sha256.json').write_text(json.dumps(h, indent=2)+'\n')
assert all(sha(out/n) == d for n,d in h.items())
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
os.sync()
print(json.dumps(report | {'manifest_sha256': sha(out/'sha256.json')}, indent=2))
