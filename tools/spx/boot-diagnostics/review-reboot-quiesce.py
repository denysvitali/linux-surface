#!/usr/bin/python3
"""Independently freeze final output ownership/callback source and recovery state."""
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al');out=run/'reboot-quiesce-review-20261001'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
assert os.geteuid()==0 and not out.exists()
records={}
for d in ('final-result','post-result-records','recovery-return','reset-self-wait-candidate-v2','deferred-recovery-candidate-20261001','hid-publisher-stop-candidate-20261001','worker-recovery-combined-20261001','worker-recovery-review-20261001','output-power-lock-candidate-20261001','reboot-quiesce-candidate-20261001'):
 p=run/d;h=json.loads((p/'sha256.json').read_text());assert files(p)==h|{'sha256.json':sha(p/'sha256.json')};records[d]={'files':len(h),'manifest_sha256':sha(p/'sha256.json')}
candidate=run/'reboot-quiesce-candidate-20261001';power=run/'output-power-lock-candidate-20261001'
c=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text()
for n in ('spi-hid-core.c','spi-hid-core.h'):assert (repo/'drivers/hid/spi-hid'/n).read_bytes()==(candidate/n).read_bytes()
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==(candidate/'source.diff').read_bytes()
assert (repo/'.config').read_bytes()==(candidate/'config').read_bytes()==(run/'build/artifacts/.config').read_bytes()
assert sha(repo/'drivers/hid/spi-hid/spi-hid.o')==sha(candidate/'spi-hid.tested.o')
p=json.loads((power/'independent-review.json').read_text());q=json.loads((candidate/'independent-review.json').read_text())
assert p['output_cases']==60 and p['unchanged_power_cases']==24 and p['controlled_interleaving_and_shutdown_gate_scenarios_passed']
assert q['actual_dispatch_cleanup_cases']==144 and q['absent_driver_or_callback_cases']==2
for r in (p,q):assert r['sanitizers_passed'] and r['native_compile_exit_code']==r['compiler_warnings']==r['style_exit_code']==0
# Callback-only difference preserves all final tested output/power functions.
for n in ('spi_hid_output','spi_hid_power_down','spi_hid_power_up','spi_hid_reset_work'):assert function(c,n)==function((power/'spi-hid-core.c').read_text(),n)
for n in ('spi_hid_output','spi_hid_power_down','spi_hid_power_up'):
 f=function(c,n);assert f.count('mutex_lock(&shid->output_lock)')==f.count('mutex_unlock(&shid->output_lock)')==1
 assert f.index('mutex_lock(&shid->output_lock)')<min([f.index(t) for t in ('spi_sync(', 'regulator_enable(', 'spin_lock_irqsave(') if t in f])
f=function(c,'spi_hid_reset_work');assert f.index('mutex_lock(&shid->lock)')<f.index('memset(&buf->body')<f.index('spi_hid_output(shid')<f.index('mutex_unlock(&shid->lock)')<f.index('spi_hid_schedule_error(shid)')
assert '.shutdown\t= spi_hid_spi_shutdown' in c
f=function(c,'spi_hid_spi_shutdown');assert f.index('quiesce begin')<f.index('spi_hid_shutdown(')<f.index('quiesce complete')
assert c.count('spi_hid_error_handler(shid)')==1
# Source closure for startup/input callbacks must not wait for output/request locks.
names=set(re.findall(r'^static [^;{}]*\b(spi_hid_\w+)\([^;{}]*\)\n\{',c,re.M));seen=set();todo=['spi_hid_startup_work','spi_hid_input_header_complete','spi_hid_input_body_complete']
# Find completion symbols rather than relying on spelling.
todo=['spi_hid_startup_work']+re.findall(r'^static void (spi_hid_\w*complete)\(',c,re.M)
while todo:
 n=todo.pop()
 if n in seen:continue
 seen.add(n);f=function(c,n);assert 'mutex_lock(&shid->output_lock)' not in f and 'mutex_lock(&shid->lock)' not in f,n
 todo.extend((set(re.findall(r'\b(spi_hid_\w+)\s*\(',f))&names)-seen)
a=json.loads((run/'attempt.json').read_text());bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert bid=='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
for n,h in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(n)==h,n
mods=json.loads((run/'build/module-sha256.json').read_text());assert len(mods)==202
for n,h in mods.items():assert sha(Path('/usr/lib/modules')/a['release']/n)==h,n
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
out.mkdir(mode=0o700)
for n in ('TOUCH-REBOOT-QUIESCE-20261001.md','AM-PLAN-20261001.md','review-reboot-quiesce.py','verify-output-power-lock.py','verify-reboot-quiesce.py'):shutil.copy2(repo/'tools/spx/boot-diagnostics'/n,out/n)
for n in ('spi-hid-core.c','spi-hid-core.h','source.diff','config','spi-hid.tested.o'):shutil.copy2(candidate/n,out/n)
report={'archives_rehashed':records,'known_good_boot_id':bid,'candidate_driver_sha256':sha(out/'spi-hid-core.c'),'candidate_header_sha256':sha(out/'spi-hid-core.h'),'candidate_source_diff_sha256':sha(out/'source.diff'),'config_sha256':sha(out/'config'),'output_cases':60,'unchanged_power_cases':24,'callback_dispatch_cleanup_cases':144,'absent_driver_callback_cases':2,'final_output_power_functions_exact_tested':True,'startup_input_local_call_closure':sorted(seen),'local_lock_order':'request -> output -> input','installed_module_files_verified':202,'payload_runtime_recovery_files_verified':15,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'deployed':False,'new_boot_selected':False,'hardware_callback_executed':False,'efi_early_kernel_recovery_validated':False,'limits':['Local call closure excludes external HID-core/driver internals; no exhaustive kernel lock proof.','Callback completion does not establish successful regulator disable.','Initial AL bootstrap failure remains unresolved; outgoing marker retention unvalidated.']}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');h=files(out);(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(out)==h|{'sha256.json':sha(out/'sha256.json')};os.sync();print(json.dumps(report|{'review_files':len(h),'review_manifest_sha256':sha(out/'sha256.json')},indent=2))
