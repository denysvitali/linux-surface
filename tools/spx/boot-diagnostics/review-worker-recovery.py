#!/usr/bin/python3
"""Freeze the local worker wait graph and independently recheck candidate provenance."""
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al');out=run/'worker-recovery-review-20261001'
assert os.geteuid()==0 and not out.exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
records={}
for d in ('final-result','recovery-return','reset-self-wait-candidate-v2','deferred-recovery-candidate-20261001','hid-publisher-stop-candidate-20261001','worker-recovery-combined-20261001'):
 p=run/d;h=json.loads((p/'sha256.json').read_text());assert {str(q.relative_to(p)):sha(q) for q in p.rglob('*') if q.is_file() and not q.is_symlink()}==h|{'sha256.json':sha(p/'sha256.json')};records[d]={'files':len(h),'manifest_sha256':sha(p/'sha256.json')}
old=(run/'reset-self-wait-candidate-v2/spi-hid-core.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text();assert (run/'worker-recovery-combined-20261001/spi-hid-core.c').read_text()==new
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==(run/'worker-recovery-combined-20261001/source.diff').read_bytes()
assert (repo/'.config').read_bytes()==(run/'build/artifacts/.config').read_bytes()
assert sha(repo/'drivers/hid/spi-hid/spi-hid.o')==sha(run/'hid-publisher-stop-candidate-20261001/spi-hid.tested.o')
assert new.count('spi_hid_error_handler(shid)')==1 and new.count('spi_hid_stop_hid(shid)')==2
workers=['error_work','reset_work','create_device_work','refresh_device_work','startup_work']
def graph(s):
 names=set(re.findall(r'^static [^;{}]*\b(spi_hid_\w+)\([^;{}]*\)\n\{',s,re.M));bodies={n:function(s,n).split('{',1)[1] for n in names}
 # Known HID-core callbacks reached during add/destroy; these are not literal C calls.
 callback_edges={'spi_hid_create_device':['spi_hid_ll_parse','spi_hid_ll_open','spi_hid_ll_close'],'spi_hid_stop_hid':['spi_hid_ll_close']}
 result={}
 for w in workers:
  seen=set();todo=['spi_hid_'+w]
  while todo:
   n=todo.pop()
   if n in seen:continue
   seen.add(n);body=bodies[n]
   calls=set(re.findall(r'\b(spi_hid_\w+)\s*\(',body))&names
   todo.extend(calls-set(seen));todo.extend(q for q in callback_edges.get(n,[]) if q in names and q not in seen)
  waits=set()
  for n in seen:
   waits.update(re.findall(r'(?:cancel_work_sync|flush_work|cancel_delayed_work_sync)\(&shid->(\w+)\)',bodies[n]))
  # Existing current_work guard makes reset's own cancel nonblocking.
  if w=='reset_work':waits.discard('reset_work')
  result[w]=sorted(waits&set(workers))
 return result
def cycles(g):
 found=[]
 def visit(n,path):
  for q in g[n]:
   if q in path:found.append(path[path.index(q):]+[q])
   else:visit(q,path+[q])
 for n in g:visit(n,[n])
 return found
before=graph(old);after=graph(new);assert cycles(before) and not cycles(after),(before,after)
assert after['reset_work']==['create_device_work','refresh_device_work']
assert after['error_work']==['create_device_work','refresh_device_work','reset_work','startup_work']
assert 'spi_hid_schedule_error' in function(new,'spi_hid_sync_request')
assert '.shutdown' not in new[new.index('static struct spi_driver spi_hid_driver = {'):]
a=json.loads((run/'attempt.json').read_text());assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
for p,h in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(p)==h,p
mods=json.loads((run/'build/module-sha256.json').read_text());assert len(mods)==202
for p,h in mods.items():assert sha(Path('/usr/lib/modules')/a['release']/p)==h,p
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
out.mkdir(mode=0o700)
for n in ('TOUCH-WORKER-RECOVERY-20261001.md','review-worker-recovery.py','verify-deferred-recovery.py','verify-hid-publisher-stop.py','verify-worker-recovery-combined.py'):shutil.copy2(repo/'tools/spx/boot-diagnostics'/n,out/n)
for n in ('spi-hid-core.c','source.diff','config','spi-hid.tested.o','independent-review.json'):shutil.copy2(run/'worker-recovery-combined-20261001'/n,out/n)
report={'archives_rehashed':records,'previous_possible_synchronous_work_waits':before,'current_possible_synchronous_work_waits':after,'current_modeled_work_wait_graph_acyclic':True,'only_error_work_enters_recovery_handler':True,'stop_gate_before_publisher_drain_and_disconnect':True,'known_good_boot_id':'5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5','next_entry_empty':True,'known_good_default':True,'installed_module_files_verified':202,'payload_recovery_runtime_files_verified':15,'candidate_driver_sha256':sha(repo/'drivers/hid/spi-hid/spi-hid-core.c'),'candidate_source_diff_sha256':sha(out/'source.diff'),'new_hardware_trial_selected':False,'limitations':['Graph covers this driver’s synchronous work waits and declared HID callbacks, not all kernel locks/completions or workqueue interleavings.','Outgoing reboot callback and initial-probe recovery are not implemented.','The source candidate has not been installed or tested on hardware.']}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');h={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()};(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(out/n)==v for n,v in h.items());os.sync();print(json.dumps(report|{'review_files':len(h),'review_manifest_sha256':sha(out/'sha256.json')},indent=2))
