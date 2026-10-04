#!/usr/bin/python3
"""Independent frozen AF installation, selector and diagnostic-scope audit."""
import ast,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077)
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
SRC=REPO/'tools/spx/boot-diagnostics'
BASE=Path('/var/lib/spx-boot-diagnostics')
P=BASE/'attempts/20260930ae'; X=BASE/'attempts/20260930af'
BID='1b26cb6c-0e7f-4a3b-a290-f3bf44a6855c'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(root):return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}
def cmd(*a):return subprocess.check_output(a,text=True,timeout=90).strip()
assert os.geteuid()==0 and not (X/'prequeue-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert cmd('uname','-r')=='7.3.0-rc2-spx-mainline-20260930ae+'
assert 'spx_attempt=20260930ae' in Path('/proc/cmdline').read_text().split()
a=json.loads((X/'attempt.json').read_text());p=json.loads((P/'attempt.json').read_text())
assert a==json.loads((BASE/'attempt.json').read_text())
assert a['state']=='prepared AF; no boot selection' and not a['playback_requested']
assert a['preboot_id']==BID and a['sha256']==p['sha256'] and a['recovery_sha256']==p['recovery_sha256']
assert a['release']==p['release']
assert a['cmdline']==p['cmdline'].replace('spx_attempt=20260930ae','spx_attempt=20260930af').replace('wcd934x.spx_wsa_en_pin=1','wcd934x.spx_wsa_en_pin=2')
assert set(a['cmdline'].split())-set(p['cmdline'].split())=={'spx_attempt=20260930af','wcd934x.spx_wsa_en_pin=2'}
assert set(p['cmdline'].split())-set(a['cmdline'].split())=={'spx_attempt=20260930ae','wcd934x.spx_wsa_en_pin=1'}
for root in (P/'final-result',P/'post-result-records',X/'preboot-snapshot'):
 h=json.loads((root/'sha256.json').read_text());assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:
 assert (X/mf).read_bytes()==(P/mf).read_bytes()
 assert files(X/tree)==json.loads((X/mf).read_text())
assert {str(q.relative_to(X/'build')):os.readlink(q) for q in (X/'build').rglob('*') if q.is_symlink()}==json.loads((X/'build-symlinks.json').read_text())
assert files(Path('/usr/lib/modules')/a['release'])==json.loads((X/'build/module-sha256.json').read_text())
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(X/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
for name,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(name)==d,name
for directory in ('preparation-sources','deployment-sources'):
 assert files(X/directory)==json.loads((X/(directory+'-sha256.json')).read_text())
 for name,d in json.loads((X/(directory+'-sha256.json')).read_text()).items():assert sha(SRC/name)==d,name
review=json.loads((X/'installed-review.json').read_text())
assert review['payload_recovery_runtime_hashes_verified']==15 and review['modules_verified']==202
assert review['build_files_verified']==1084 and review['build_symlinks_verified']==272
native=json.loads((X/'native-continuation-review.json').read_text())
assert native['boot_id']==BID and native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage']=='continue'
assert native['codexThreadId']=='01a0f1ab-5218-7880-a0f0-feff144bca7d'
assert native['lifecycleState']=='running' and native['startedBy']=='daemon' and native['startedFromDaemon']
assert native['legacy_resume_marker_absent'];os.kill(native['hostPid'],0)
prior=ast.parse((SRC/'ae-finalize.py').read_text());trial=ast.parse((SRC/'af-finalize.py').read_text())
def assignment(t,name):return next(n.value for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(q,ast.Name) and q.id==name for q in n.targets))
same=('passed','identity_diag_passed','topology_preserved','native_path_passed','touch_diag_passed','healthy','power_path_passed')
for name in same:assert ast.dump(assignment(prior,name))==ast.dump(assignment(trial,name)),name
# Replay the classifier on actual archived native words and reject malformed pairings.
paired=eval(compile(ast.Expression(assignment(trial,'paired')),'pin2-pairing','eval'),{'re':re})
kernel=(P/'final-result/kernel.log').read_text()
trace='\n'.join(line for line in kernel.splitlines() if 'SPX enum diag slot=' in line)
assert paired.search(trace) and paired.search(trace.replace('unique=3','unique=4'))
negative=('',trace.replace('rc=0/0','rc=-5/0'),trace.replace('slot=1 decoded','slot=2 decoded'),trace.replace('unique=3','unique=5'),trace.replace('2110 unique','9999 unique'))
assert all(not paired.search(t) for t in negative)
assert 'pin2_diagnostic' not in ast.dump(assignment(trial,'passed'))
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env and 'BootNext:' not in cmd('efibootmgr')
assert Path('/boot/grub/custom.cfg').read_text()==(X/'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
for name in ('spx-af-finalize.timer','spx-af-fallback.timer'):
 assert cmd('systemctl','is-enabled',name)=='enabled'
 assert cmd('systemctl','show',name,'-p','ActiveState','--value')!='active'
assert '!spx_attempt=20260930af' in Path('/etc/systemd/system/spx-diag-long-return.timer.d/104-af-exclude.conf').read_text()
subprocess.run(['systemd-analyze','verify']+[str(Path('/etc/systemd/system')/('spx-af-'+name)) for name in ('finalize.service','finalize.timer','fallback.service','fallback.timer')],check=True,timeout=30)
for path in ('/boot/grub/custom.cfg','/boot/grub/grub.cfg'):subprocess.run(['grub-script-check',path],check=True,timeout=30)
subprocess.run(['git','diff','--check'],cwd=REPO,check=True,timeout=30)
records=X/'prequeue-records';records.mkdir(mode=0o700)
for path in ('review-af-prequeue.py','RESULT-20260930ae.md','AUDIO-AFTER-AE-20260930.md'):shutil.copy2(SRC/path,records/path)
for path in ('installed-review.json','native-continuation-review.json','archive-review.json'):shutil.copy2(X/path,records/path)
h=files(records);(records/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
report={'attempt':'20260930af','preboot_id':BID,'strict_ae_predicates_unchanged':list(same),
 'pin2_diagnostic_controls_fallback':False,'actual_parent_trace_classifier_passed':True,
 'negative_pairing_cases':len(negative),'exact_parent_build_files':1084,'exact_parent_build_symlinks':272,
 'module_files_verified':202,'payload_recovery_runtime_hashes_verified':15,
 'installed_review_sha256':sha(X/'installed-review.json'),
 'native_continuation_review_sha256':sha(X/'native-continuation-review.json'),
 'prequeue_records_manifest_sha256':sha(records/'sha256.json'),
 'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,
 'boot_selected':False,'no_audio_pcm_capture_input_events_or_live_intervention':True}
(X/'prequeue-review.json').write_text(json.dumps(report,indent=2)+'\n')
os.sync();print(json.dumps(report,indent=2))
