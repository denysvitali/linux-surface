#!/usr/bin/python3
"""Freeze actual AQ transition and newly retained, identity-bound late console."""
import fcntl, json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from aq_boot_guard import BASE, X, load, recovery, artifacts, files, sha, command
os.umask(0o077)
a=load(); bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert bid!=a['preboot_id'] and os.uname().release==a['release']
assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20261003aq/vmlinuz']+a['cmdline'].split()
assert a['state'].startswith('AQ selected once') and not recovery(a).get('next_entry','')
artifacts(a)
proof=json.loads((X/'reboot-check-passed.json').read_text())
assert proof==dict(boot_id=a['preboot_id'],queued_entry=a['entry'],saved_entry='spx-known-good',payloads_verified=3,recovery_payloads_verified=3,working_module_files_links_verified=5183,trial_module_files_verified=202)
assert 'next_entry='+a['entry'] in (X/'grubenv.immediate-preboot.txt').read_text().splitlines()
marker=(X/'outgoing-identity-marker.txt').read_text().strip()
assert marker==f"SPX: outgoing handoff attempt=20261002ap boot_id={a['preboot_id']} release={a['preboot_release']} next_attempt=20261003aq"
before=X/'preboot-snapshot'; h=json.loads((before/'sha256.json').read_text())
assert files(before)==h|{'sha256.json':sha(before/'sha256.json')}
baseline=json.loads((before/'pstore-baseline-sha256.json').read_text())
subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'],check=True,timeout=90)
out=X/'handoff-review'; assert not out.exists(); out.mkdir(mode=0o700)
collector=BASE/'boots'/bid
with (collector/'collect.lock').open('a') as f:
    fcntl.flock(f,fcntl.LOCK_EX)
    for n in ('pstore','pstore-archive'): shutil.copytree(collector/n,out/n,symlinks=True)
records=[]
for n in ('pstore','pstore-archive'):
    for p in sorted((out/n).rglob('*')):
        if not p.is_file() or p.is_symlink(): continue
        name=str(p.relative_to(out/n)); digest=sha(p); text=p.read_bytes().decode(errors='replace')
        identity=text.find(marker); begin=text.find('spi_hid spi0.0: SPX: shutdown quiesce begin',max(0,identity)); end=text.find('spi_hid spi0.0: SPX: shutdown quiesce complete',max(0,begin))
        fresh=baseline[n].get(name)!=digest
        records.append(dict(path=str(p.relative_to(out)),sha256=digest,new_or_changed_since_outgoing_snapshot=fresh,identity_marker_present=identity>=0,shutdown_begin_after_identity=identity>=0 and begin>identity,shutdown_complete_after_begin=identity>=0 and begin>identity and end>begin,identity_bound_software_completion_verified=bool(fresh and identity>=0 and begin>identity and end>begin),regulator_failure_lines=[line for line in text.splitlines() if 'spi_hid spi0.0:' in line and 'regulator' in line.casefold() and any(w in line.casefold() for w in ('fail','error'))]))
log=command('journalctl','--boot='+a['preboot_id'].replace('-',''),'-u','spx-trial-20261003aq-reboot.service','-o','short-monotonic','--no-pager')
assert 'Started' in log and str(X/'reboot-check.py') in log
(out/'guard-journal.log').write_text(log+'\n')
(out/'kernel.log').write_text(command('journalctl','-b','-k','-o','short-monotonic','--no-pager')+'\n')
(out/'dmesg-raw.log').write_text(command('dmesg','--raw')+'\n')
(out/'boot-id').write_text(bid+'\n'); (out/'cmdline').write_text(Path('/proc/cmdline').read_text())
for n in ('reboot-check-passed.json','grubenv.immediate-preboot.txt','outgoing-identity-marker.txt','reboot-check.py'): shutil.copy2(X/n,out/n)
r=dict(attempt=a['attempt'],preboot_id=a['preboot_id'],actual_boot_id=bid,release=a['release'],actual_transition_verified=True,retained_console_records=records,candidate_shutdown_software_completion_verified=any(x['identity_bound_software_completion_verified'] for x in records),physical_rail_off_verified=False,efi_early_recovery_validated=False,no_manual_device_operations=True,limits=['Absence of retained markers leaves callback execution/persistence unverified; journald can stop before device_shutdown.', 'Completion means the software teardown helper returned, not successful electrical rail-off.', 'A single handoff does not establish causality or startup reliability.'])
(out/'report.json').write_text(json.dumps(r,indent=2)+'\n'); shutil.copy2(__file__,out/Path(__file__).name)
h=files(out); (out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n'); assert files(out)==h|{'sha256.json':sha(out/'sha256.json')}
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid
os.sync(); print(json.dumps(r|dict(manifest_sha256=sha(out/'sha256.json')),indent=2))
