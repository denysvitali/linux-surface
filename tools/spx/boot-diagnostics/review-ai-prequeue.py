#!/usr/bin/python3
"""Audit installed AI artifacts, AG error scope, bounded history and boot guards."""
import ast,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');SRC=REPO/'tools/spx/boot-diagnostics'
BASE=Path('/var/lib/spx-boot-diagnostics');P=BASE/'attempts/20260930ah';X=BASE/'attempts/20260930ai'
BID='b1485998-0a40-46b7-bd77-88796fa99a89'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def cmd(*a):return subprocess.check_output(a,text=True,timeout=90).strip()
def assignment(t,name):return next(n.value for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(q,ast.Name) and q.id==name for q in n.targets))
assert os.geteuid()==0 and not (X/'prequeue-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert cmd('uname','-r')=='7.3.0-rc2-spx-mainline-20260930ae+' and 'spx_attempt=20260930ah' in Path('/proc/cmdline').read_text().split()
a=json.loads((X/'attempt.json').read_text());p=json.loads((P/'attempt.json').read_text())
assert a==json.loads((BASE/'attempt.json').read_text()) and a['state']=='prepared AI; no boot selection'
assert a['preboot_id']==BID and not a['playback_requested'] and a['recovery_sha256']==p['recovery_sha256']
assert a['release']=='7.3.0-rc2-spx-mainline-20260930ai+'
assert a['cmdline']==p['cmdline'].replace('spx_attempt=20260930ah','spx_attempt=20260930ai').replace('wcd934x.spx_wsa_en_pin=1','wcd934x.spx_wsa_en_pin=2')+' soundwire_qcom.spx_cmd_diag=1'
assert set(a['cmdline'].split())-set(p['cmdline'].split())=={'spx_attempt=20260930ai','wcd934x.spx_wsa_en_pin=2','soundwire_qcom.spx_cmd_diag=1'}
assert set(p['cmdline'].split())-set(a['cmdline'].split())=={'spx_attempt=20260930ah','wcd934x.spx_wsa_en_pin=1'}
for root in (P/'final-result',P/'post-result-records',P/'command-history-candidate',X/'preboot-snapshot',X/'retired-unused-backup'):
 h=json.loads((root/'sha256.json').read_text());assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}
assert json.loads((P/'independent-result-review.json').read_text())['scoped_passed']
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:assert files(X/tree)==json.loads((X/mf).read_text())
assert {str(q.relative_to(X/'build')):os.readlink(q) for q in (X/'build').rglob('*') if q.is_symlink()}==json.loads((X/'build-symlinks.json').read_text())
modules=json.loads((X/'build/module-sha256.json').read_text());assert len(modules)==202 and files(Path('/usr/lib/modules')/a['release'])==modules
initrd=X/'build/initramfs-extracted/usr/lib/modules'/a['release']
assert {q.name for q in initrd.parent.iterdir() if q.is_dir()}=={a['release']}
included=0
for name,d in modules.items():
 path=initrd/name
 if name.endswith('.ko') and path.is_file() and not path.is_symlink():assert sha(path)==d,name;included+=1
for name in ('kernel/drivers/soundwire/soundwire-qcom.ko','kernel/drivers/mfd/wcd934x.ko','kernel/sound/soc/codecs/snd-soc-wsa881x.ko'):
 assert sha(initrd/name)==modules[name]
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(X/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
for name,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(name)==d,name
assert sha('/boot/spx-trial-20260930ai/spx.dtb')=='5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
assert files(X/'deployment-sources')==json.loads((X/'deployment-sources-sha256.json').read_text())
for name,d in json.loads((X/'deployment-sources-sha256.json').read_text()).items():assert sha(SRC/name)==d,name
review=json.loads((X/'installed-review.json').read_text());assert review['modules_verified']==202 and review['build_files_verified']==1170 and review['build_symlinks_verified']==272 and review['payload_recovery_runtime_hashes_verified']==15
native=json.loads((X/'native-continuation-review.json').read_text())
assert native['boot_id']==BID and native['codexThreadId']=='01a0f1ab-5218-7880-a0f0-feff144bca7d'
assert native['lifecycleState']=='running' and native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage']=='continue'
assert native['startedBy']=='daemon' and native['startedFromDaemon'] and native['legacy_resume_marker_absent'];os.kill(native['hostPid'],0)
old=ast.parse((SRC/'ag-finalize.py').read_text());trial=ast.parse((SRC/'ai-finalize.py').read_text())
same=('native_path_passed','touch_diag_passed','healthy','power_path_passed','pin_state_passed','pin2_diagnostic','topology_preserved','declared_names','firmware_identity_match','identity_diag_passed','right_init')
for name in same:assert ast.dump(assignment(old,name))==ast.dump(assignment(trial,name)),name
passed=assignment(trial,'passed');assert ast.dump(ast.BoolOp(op=ast.And(),values=passed.values[1:]))==ast.dump(assignment(old,'passed'))
assert isinstance(passed.values[0],ast.Name) and passed.values[0].id=='cmd_diag_passed' and 'pin2_diagnostic' not in ast.dump(passed)
base={n.id:True for n in ast.walk(passed) if isinstance(n,ast.Name) and n.id!='len'}
base.update(right_init=1,slim_devices=['a','b'],no_cards=False,force_start=0,force_done=0,force_slaves=0,attached=1,wsa_mode='Y',wsa_init=1,wsa_init_fail=0,wsa_status_fail=0,wsa_write_overflows=0,wsa_read_underflows=0,taint='0')
judge=compile(ast.Expression(passed),'AI-scope','eval');assert eval(judge,{},base)
for patch in ({'cmd_diag_passed':False},{'native_path_passed':False},{'right_init':0},{'topology_preserved':False},{'pin_state_passed':False},{'touch':False}):assert not eval(judge,{},base|patch)
parser=next(n for n in trial.body if isinstance(n,ast.FunctionDef) and n.name=='command_history_summary')
ind=ast.parse((SRC/'review-ai-result.py').read_text());assert ast.dump(parser)==ast.dump(next(n for n in ind.body if isinstance(n,ast.FunctionDef) and n.name==parser.name))
namespace={'re':re};exec(compile(ast.Module(body=[parser],type_ignores=[]),'AI-history-parser','exec'),namespace);f=namespace[parser.name]
prefix='qcom-soundwire wcd934x: SPX cmd diag ';lines=[prefix+'history count=2 submission-only',prefix+'seq=11 submitted_ns=100 op=W packed=001b3005 bridge_rc=0',prefix+'seq=12 submitted_ns=101 op=R packed=011c0050 bridge_rc=1'];trace='\n'.join(lines)
assert f('',{'spx_cmd_diag':'Y'})['well_formed'] and f(trace,{'spx_cmd_diag':'Y'})['well_formed'] and not f(trace,{})['enabled']
negative=['\n'.join(lines[:2]),trace.replace('count=2','count=17'),trace.replace('seq=12','seq=14'),trace.replace('submitted_ns=101','submitted_ns=99'),trace.replace('packed=011c0050','packed=xyz'),trace+'\n'+prefix+'unexpected',trace+'\n'+trace+'\n'+trace]
assert all(not f(t,{'spx_cmd_diag':'Y'})['well_formed'] for t in negative)
maxtrace='\n'.join([prefix+'history count=16 submission-only']+[prefix+f'seq={i+1} submitted_ns={i+1} op=W packed=001b3005 bridge_rc=0' for i in range(16)])
assert f(maxtrace+'\n'+maxtrace,{'spx_cmd_diag':'Y'})['well_formed']
assert f(maxtrace+'\n'+maxtrace,{'spx_cmd_diag':'Y'})['line_count']==34
# Reproduce the six generated helpers in memory, without touching frozen sources.
class Read:
 def __init__(self,path):self.path=path
 def read_text(self):return self.path.read_text()
class Root:
 def __truediv__(self,name):return Read(SRC/name)
generator=ast.parse((SRC/'generate-ai-boot.py').read_text());generator.body=[n for n in generator.body if not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROOT' for t in n.targets)) and not (isinstance(n,ast.FunctionDef) and n.name=='save')]
outputs={};exec(compile(generator,'AI-generator-memory-check','exec'),{'ROOT':Root(),'save':lambda n,s:outputs.update({n:s})})
assert len(outputs)==6
for name,text in outputs.items():assert (SRC/name).read_text()==text,name
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in cmd('efibootmgr') and Path('/boot/grub/custom.cfg').read_text()==(X/'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
for name in ('spx-ai-finalize.timer','spx-ai-fallback.timer'):
 assert cmd('systemctl','is-enabled',name)=='enabled' and cmd('systemctl','show',name,'-p','ActiveState','--value')!='active'
assert '!spx_attempt=20260930ai' in Path('/etc/systemd/system/spx-diag-long-return.timer.d/107-ai-exclude.conf').read_text()
subprocess.run(['systemd-analyze','verify']+[str(Path('/etc/systemd/system')/('spx-ai-'+name)) for name in ('finalize.service','finalize.timer','fallback.service','fallback.timer')],check=True,timeout=30)
for path in ('/boot/grub/custom.cfg','/boot/grub/grub.cfg'):subprocess.run(['grub-script-check',path],check=True,timeout=30)
subprocess.run(['git','diff','--check'],cwd=REPO,check=True)
records=X/'prequeue-records';records.mkdir(mode=0o700)
for name in ('review-ai-prequeue.py','PREPARED-20260930ai.md'):shutil.copy2(SRC/name,records/name)
for name in ('installed-review.json','independent-build-review.json','native-continuation-review.json','archive-review.json'):shutil.copy2(X/name,records/name)
h=files(records);(records/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
report={'attempt':'20260930ai','preboot_id':BID,'unchanged_ag_boundaries':list(same),'strict_negative_scope_cases':6,'malformed_history_negative_cases':len(negative),'maximum34_line_history_case_passed':True,'generated_helpers_reproduce_reviewed_sources':True,'private_initramfs_module_hashes_verified':included,'build_files_verified':1170,'build_symlinks_verified':272,'module_files_verified':202,'payload_recovery_runtime_hashes_verified':15,'pin2_diagnostic_controls_fallback':False,'native_error_still_fails_scope':True,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'prequeue_records_manifest_sha256':sha(records/'sha256.json'),'native_continuation_review_sha256':sha(X/'native-continuation-review.json'),'boot_selected':False,'playback_requested':False}
(X/'prequeue-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
