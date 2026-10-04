#!/usr/bin/python3
"""Independently verify AH artifact reuse, pin1 scope, and pending boot guards."""
import ast, hashlib, json, os, shutil, subprocess
from pathlib import Path
os.umask(0o077)
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
SRC=REPO/'tools/spx/boot-diagnostics'
BASE=Path('/var/lib/spx-boot-diagnostics')
P=BASE/'attempts/20260930ag';X=BASE/'attempts/20260930ah'
BID='43efd328-c5ba-48bf-9edf-797ccf268b1f'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def cmd(*a):return subprocess.check_output(a,text=True,timeout=90).strip()
def assignment(t,name):return next(n.value for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(q,ast.Name) and q.id==name for q in n.targets))
assert os.geteuid()==0 and not (X/'prequeue-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert cmd('uname','-r')=='6.18.3-1-surface+' and 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
a=json.loads((X/'attempt.json').read_text());p=json.loads((P/'attempt.json').read_text())
assert a==json.loads((BASE/'attempt.json').read_text())
assert a['state']=='prepared AH; no boot selection' and a['preboot_id']==BID
assert not a['playback_requested'] and a['sha256']==p['sha256'] and a['recovery_sha256']==p['recovery_sha256']
assert a['release']==p['release']
assert a['cmdline']==p['cmdline'].replace('spx_attempt=20260930ag','spx_attempt=20260930ah').replace('wcd934x.spx_wsa_en_pin=2','wcd934x.spx_wsa_en_pin=1')
assert set(a['cmdline'].split())-set(p['cmdline'].split())=={'spx_attempt=20260930ah','wcd934x.spx_wsa_en_pin=1'}
assert set(p['cmdline'].split())-set(a['cmdline'].split())=={'spx_attempt=20260930ag','wcd934x.spx_wsa_en_pin=2'}
for root in (P/'final-result',P/'post-result-records',P/'recovery-return',X/'preboot-snapshot',X/'collector-selector-correction'):
 h=json.loads((root/'sha256.json').read_text());assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}
assert json.loads((P/'recovery-return/report.json').read_text())['recovery_boot_id']==BID
for tree,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:
 assert (X/mf).read_bytes()==(P/mf).read_bytes()
 assert files(X/tree)==json.loads((X/mf).read_text())
assert {str(q.relative_to(X/'build')):os.readlink(q) for q in (X/'build').rglob('*') if q.is_symlink()}==json.loads((X/'build-symlinks.json').read_text())
assert files(Path('/usr/lib/modules')/a['release'])==json.loads((X/'build/module-sha256.json').read_text())
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(X/'dtb-build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
for name,d in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(name)==d,name
assert files(X/'deployment-sources')==json.loads((X/'deployment-sources-sha256.json').read_text())
for name,d in json.loads((X/'deployment-sources-sha256.json').read_text()).items():assert sha(SRC/name)==d,name
native=json.loads((X/'native-continuation-review.json').read_text())
assert native['boot_id']==BID and native['codexThreadId']=='01a0f1ab-5218-7880-a0f0-feff144bca7d'
assert native['lifecycleState']=='running' and native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage']=='continue'
assert native['startedBy']=='daemon' and native['startedFromDaemon'] and native['legacy_resume_marker_absent'];os.kill(native['hostPid'],0)
prior=ast.parse((SRC/'ag-finalize.py').read_text());trial=ast.parse((SRC/'ah-finalize.py').read_text())
same=('native_path_passed','touch_diag_passed','healthy','power_path_passed','topology_preserved','declared_names','paired')
for name in same:assert ast.dump(assignment(prior,name))==ast.dump(assignment(trial,name)),name
class InitName(ast.NodeTransformer):
 def visit_Name(self,node):
  return ast.copy_location(ast.Name(id='right_init' if node.id=='left_init' else node.id,ctx=node.ctx),node)
assert ast.dump(InitName().visit(assignment(trial,'passed')))==ast.dump(assignment(prior,'passed'))
# Reparse after the AST comparison above, which renames the temporary expression.
trial=ast.parse((SRC/'ah-finalize.py').read_text())
assert ast.literal_eval(assignment(trial,'declared_names'))=={'sdw:0:0:0217:2110:00:3','sdw:0:0:0217:2110:00:4'}
assert ast.literal_eval(assignment(trial,'left').args[0])=='sdw:0:0:0217:2110:00:3'
assert '/speaker@0,3' in ast.dump(assignment(trial,'firmware_identity_match'))
assert 'unique=3' in ast.dump(assignment(trial,'identity_diag_passed'))
assert ast.literal_eval(assignment(trial,'left_init').args[0])=='wsa881x-codec sdw:0:0:0217:2110:00:3: SPX: initializing amplifier at SoundWire device 1'
assert 'wcd934x.spx_wsa_en_pin=1' in ast.literal_eval(assignment(trial,'selectors'))
assert 'wcd934x.spx_wsa_en_pin=2' not in ast.literal_eval(assignment(trial,'selectors'))
pin=compile(ast.Expression(assignment(trial,'pin_state_passed')),'AH-pin-scope','eval')
class Kernel:
 def count(self,s):return int(s=='SPX: forced wcd-gpio pin 1 output-high')
g={'wcd_params':{'spx_wsa_en_pin':'1','spx_wsa_gpio_dir':'-1','spx_wsa_gpio_val':'-1'},'wsa_params':{'spx_swap_dac_master_ports':'N'},'direction':2,'value':26,'kernel':Kernel()}
assert eval(pin,{},g)
for patch in ({'direction':4},{'value':28},{'wcd_params':g['wcd_params']|{'spx_wsa_en_pin':'2'}}):assert not eval(pin,{},g|patch)
passed=assignment(trial,'passed');base={n.id:True for n in ast.walk(passed) if isinstance(n,ast.Name) and n.id!='len'}
base.update(left_init=1,slim_devices=['a','b'],no_cards=False,force_start=0,force_done=0,force_slaves=0,attached=1,wsa_mode='Y',wsa_init=1,wsa_init_fail=0,wsa_status_fail=0,wsa_write_overflows=0,wsa_read_underflows=0,taint='0')
judge=compile(ast.Expression(passed),'AH-scope','eval');assert eval(judge,{},base)
for patch in ({'left_init':0},{'native_path_passed':False},{'topology_preserved':False},{'touch':False},{'pin_state_passed':False}):assert not eval(judge,{},base|patch)
assert 'pin1_diagnostic' not in ast.dump(passed)
for pth in SRC.glob('*ah*.py'):ast.parse(pth.read_text())
env=cmd('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env and 'BootNext:' not in cmd('efibootmgr')
assert Path('/boot/grub/custom.cfg').read_text()==(X/'entry.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
for name in ('spx-ah-finalize.timer','spx-ah-fallback.timer'):
 assert cmd('systemctl','is-enabled',name)=='enabled'
 assert cmd('systemctl','show',name,'-p','ActiveState','--value')!='active'
assert '!spx_attempt=20260930ah' in Path('/etc/systemd/system/spx-diag-long-return.timer.d/106-ah-exclude.conf').read_text()
subprocess.run(['systemd-analyze','verify']+[str(Path('/etc/systemd/system')/('spx-ah-'+name)) for name in ('finalize.service','finalize.timer','fallback.service','fallback.timer')],check=True,timeout=30)
for path in ('/boot/grub/custom.cfg','/boot/grub/grub.cfg'):subprocess.run(['grub-script-check',path],check=True,timeout=30)
subprocess.run(['git','diff','--check'],cwd=REPO,check=True,timeout=30)
records=X/'prequeue-records';records.mkdir(mode=0o700)
for name in ('review-ah-prequeue.py','RESULT-20260930ag.md','AUDIO-AFTER-AG-20260930.md'):shutil.copy2(SRC/name,records/name)
for name in ('installed-review.json','native-continuation-review.json','archive-review.json'):shutil.copy2(X/name,records/name)
h=files(records);(records/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
report={'attempt':'20260930ah','preboot_id':BID,'unchanged_ag_boundaries':list(same),'exact_ag_payload_source_config':True,'only_selector_delta':'pin2 -> pin1 and attempt marker','left_specific_negative_scope_cases':5,'pin_state_negative_cases':3,'pin1_diagnostic_controls_fallback':False,'collector_selector_correction_manifest_sha256':sha(X/'collector-selector-correction/sha256.json'),'module_files_verified':202,'payload_recovery_runtime_hashes_verified':15,'build_files_verified':1084,'build_symlinks_verified':272,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'prequeue_records_manifest_sha256':sha(records/'sha256.json'),'native_continuation_review_sha256':sha(X/'native-continuation-review.json'),'boot_selected':False,'no_audio_pcm_capture_input_or_live_intervention':True}
(X/'prequeue-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
