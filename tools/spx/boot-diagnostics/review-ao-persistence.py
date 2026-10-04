#!/usr/bin/python3
"""Archive read-only evidence for the missing AM-to-AO persistent console."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics');X=BASE/'attempts/20261002ao'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def command(*args):return subprocess.check_output(args,text=True,timeout=90)
a=json.loads((X/'attempt.json').read_text());h=json.loads((X/'handoff-review/report.json').read_text())
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==h['actual_boot_id']
assert h['actual_transition_verified'] and h['retained_console_records']==[]
for name in ('handoff-review','startup-discovery','preboot-snapshot'):
 root=X/name;expected=json.loads((root/'sha256.json').read_text())
 assert files(root)==expected|{'sha256.json':sha(root/'sha256.json')}
out=X/'persistence-review';assert not out.exists();out.mkdir(mode=0o700)
logs={}
for label,bid in (('outgoing-am',a['preboot_id']),('incoming-ao',h['actual_boot_id'])):
 log=command('journalctl','--boot='+bid.replace('-',''),'-k','-o','cat','--no-pager')
 assert 'pstore: Registered ramoops as persistent store backend' in log
 assert 'printk: legacy console [ramoops-1] enabled' in log
 assert 'ramoops: using 0x100000@0x9a480000, ecc: 0' in log
 (out/(label+'-kernel.log')).write_text(log);logs[label]=log
control=Path('/sys/kernel/debug/dynamic_debug/control').read_text()
sites=[line for line in control.splitlines() if line.startswith(('fs/pstore/ram.c:', 'fs/pstore/ram_core.c:'))]
assert len(sites)==5 and all('[ramoops]' in line and ' =_ ' in line for line in sites)
(out/'dynamic-debug-sites.txt').write_text('\n'.join(sites)+'\n')
for n in ('fs/pstore/Makefile','fs/pstore/ram.c','fs/pstore/ram_core.c','lib/dynamic_debug.c','arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts','.config'):
 p=out/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(REPO/n,p)
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
assert 'early_initcall(dynamic_debug_init);' in (REPO/'lib/dynamic_debug.c').read_text()
assert 'postcore_initcall(ramoops_init);' in (REPO/'fs/pstore/ram.c').read_text()
assert 'ramoops-objs += ram.o ram_core.o' in (REPO/'fs/pstore/Makefile').read_text()
assert 'CONFIG_DYNAMIC_DEBUG=y\n' in (REPO/'.config').read_text()
for name,path in (('pstore','/sys/fs/pstore'),('pstore-archive','/var/lib/systemd/pstore')):
 assert files(Path(path))=={}
 shutil.copytree(path,out/name)
(out/'systemd-pstore.txt').write_text(command('systemctl','show','systemd-pstore.service','-p','ActiveState','-p','Result','-p','UnitFileState'))
(out/'ramoops-layout').write_text((BASE/'boots'/h['actual_boot_id']/'ramoops-layout').read_text())
report=dict(attempt=a['attempt'],boot_id=h['actual_boot_id'],outgoing_boot_id=a['preboot_id'],
    backend_registered_on_both_boots=True,console_enabled_on_both_boots=True,
    retained_console_files=0,callback_execution_verified=False,
    invalid_signature_or_empty_buffer_distinguishable_now=False,
    pstore_archiver_active=False,existing_ramoops_debug_sites=len(sites),
    existing_sites_enabled=False,existing_debug_init_precedes_ramoops=True,
    possible_future_selector='ramoops.dyndbg=+p',selector_applied=False,
    reserved_overlap_is_other_region=True,
    limits=['Missing console does not identify whether firmware, loader, or buffer validation lost the data.',
            'The existing overlap warning is 96e00000/98715000, not the 9a480000 ramoops reservation.',
            'Existing debug sites report old signature/size before buffer initialization; enabling them requires a future boot to observe that stage.',
            'Debug logging would diagnose persistence, not establish callback execution, physical rail-off, or early reset recovery.'])
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');shutil.copy2(__file__,out/Path(__file__).name)
m=files(out);(out/'sha256.json').write_text(json.dumps(m,indent=2)+'\n');assert files(out)==m|{'sha256.json':sha(out/'sha256.json')}
os.sync();print(json.dumps(report|dict(files_verified=len(m),manifest_sha256=sha(out/'sha256.json')),indent=2))
