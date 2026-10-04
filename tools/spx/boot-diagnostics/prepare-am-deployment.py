#!/usr/bin/python3
"""Revalidate AM and derive current recovery/entry against the pruned known-good boot."""
import ast,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');SRC=REPO/'tools/spx/boot-diagnostics';BASE=Path('/var/lib/spx-boot-diagnostics');X=BASE/'attempts/20261001am';P=BASE/'attempts/20260930ak';PRUNE=BASE/'boot-prune-20261002';OUT=X/'deployment-preparation';BID='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def links(p):return {str(q.relative_to(p)):os.readlink(q) for q in sorted(p.rglob('*')) if q.is_symlink()}
def assignment(t,n):return next(x.value for x in ast.walk(t) if isinstance(x,ast.Assign) and any(isinstance(y,ast.Name) and y.id==n for y in x.targets))
assert os.geteuid()==0 and not OUT.exists() and not (X/'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID and os.uname().release=='6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
clean=json.loads((PRUNE/'plan.json').read_text());original=json.loads((PRUNE/'snapshot-manifest.json').read_text());result=json.loads((PRUNE/'result.json').read_text());assert sha(PRUNE/'snapshot-manifest.json')==result['snapshot_manifest_sha256']
for p,h in clean['keep_payload_sha256'].items():assert sha(p)==h,p
root=Path(clean['kept_module_tree']);prefix=root.name+'/';kept={n[len(prefix):]:r for n,r in original['/usr/lib/modules'].items() if n.startswith(prefix)};actual={}
for p in root.rglob('*'):
 n=str(p.relative_to(root))
 if p.is_symlink():actual[n]={'symlink':os.readlink(p)}
 elif p.is_file():actual[n]={'sha256':sha(p),'bytes':p.stat().st_size}
assert actual==kept and len(kept)==5183
assert sorted(p.name for p in Path('/usr/lib/modules').iterdir())==[root.name]
assert sha('/boot/grub/grub.cfg')==result['new_grub_config_sha256'] and not Path('/boot/grub/custom.cfg').exists()
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
archive=json.loads((X/'archive-review.json').read_text());review=json.loads((X/'independent-build-review.json').read_text());assert review['release']=='7.3.0-rc2-spx-mainline-20261001am+'
assert sha(X/'build-sha256.json')==archive['build_manifest_sha256']==review['build_manifest_sha256'] and files(X/'build')==json.loads((X/'build-sha256.json').read_text())
assert links(X/'build')==json.loads((X/'build-symlinks.json').read_text())
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(X/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==archive['config_sha256']
for n,h in review['source_sha256'].items():assert sha(REPO/n)==h,n
for n,h in archive['boot_payload_sha256'].items():assert sha(X/'build'/n)==h,n
assert files(X/'dtb-build')==json.loads((X/'dtb-sha256.json').read_text())
# Only identity substitutions in the real AK collector/reviewer; strict policies preserved.
for old,new in [('ak-finalize.py','am-finalize.py'),('review-ak-result.py','review-am-result.py')]:
 expected=(SRC/old).read_text().replace('20260930ak','20261001am').replace('spx-ak-','spx-am-').replace('AK','AM');assert (SRC/new).read_text()==expected
old=ast.parse((SRC/'ak-finalize.py').read_text());new=ast.parse((SRC/'am-finalize.py').read_text())
same=('passed','native_path_passed','touch_diag_passed','healthy','power_path_passed','pin_state_passed','pin2_diagnostic','topology_preserved','declared_names','firmware_identity_match','identity_diag_passed','right_init')
for n in same:assert ast.dump(assignment(old,n))==ast.dump(assignment(new,n)),n
passed=assignment(new,'passed');base={n.id:True for n in ast.walk(passed) if isinstance(n,ast.Name) and n.id!='len'};base.update(right_init=1,slim_devices=['a','b'],no_cards=False,force_start=0,force_done=0,force_slaves=0,attached=1,wsa_mode='Y',wsa_init=1,wsa_init_fail=0,wsa_status_fail=0,wsa_write_overflows=0,wsa_read_underflows=0,taint='0');judge=compile(ast.Expression(passed),'AM-scope','eval');assert eval(judge,{},base)
for patch in ({'cmd_diag_passed':False},{'native_path_passed':False},{'right_init':0},{'topology_preserved':False},{'pin_state_passed':False},{'touch':False}):assert not eval(judge,{},base|patch)
parent=json.loads((P/'attempt.json').read_text());cmdline=parent['cmdline'].replace('spx_attempt=20260930ak','spx_attempt=20261001am');assert set(cmdline.split())-set(parent['cmdline'].split())=={'spx_attempt=20261001am'} and set(parent['cmdline'].split())-set(cmdline.split())=={'spx_attempt=20260930ak'}
entry=(P/'entry.cfg').read_text().replace('20260930ak','20261001am').replace('AK silent detached BOOST Switch guard','AM SPI-HID lifecycle')
assert (' '+cmdline+'; then') in entry and entry.count('--id spx-trial-20261001am')==1
assert all(entry.count('/spx-trial-20261001am/'+n)==1 for n in ('vmlinuz','initramfs.img','spx.dtb'))
OUT.mkdir(mode=0o700);(OUT/'entry.cfg').write_text(entry);subprocess.run(['grub-script-check',str(OUT/'entry.cfg')],check=True)
efi={str(Path('/boot')/n):r['sha256'] for n,r in original['/boot'].items() if n.startswith('EFI/') and 'sha256' in r}
for p,h in efi.items():assert sha(p)==h,p
recovery={'payload_sha256':clean['keep_payload_sha256'],'module_files_links':kept,'entry':(PRUNE/'known-good-entry.txt').read_text(),'efi_sha256':efi,'prune_snapshot_manifest_sha256':result['snapshot_manifest_sha256']}
(OUT/'working-recovery.json').write_text(json.dumps(recovery,indent=2)+'\n');shutil.copy2(BASE/'attempt.json',OUT/'previous-active-attempt.json')
for p in ('/boot/grub/grub.cfg','/etc/grub.d/41_custom','/etc/default/grub'):shutil.copy2(p,OUT/Path(p).name)
report={'preboot_id':BID,'preboot_cmdline':Path('/proc/cmdline').read_text().strip(),'working_payloads_verified':3,'working_module_files_links_verified':5183,'build_files_verified':archive['build_files_verified'],'build_symlinks_verified':archive['build_symlinks_verified'],'working_recovery_sha256':sha(OUT/'working-recovery.json'),'strict_scope_preserved':list(same),'strict_negative_cases':6,'finalizer_reviewer_identity_only':True,'cmdline':cmdline,'authorization':parent['authorization'],'pruned_parent_live_paths_not_required':True,'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'boot_selected':False}
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');shutil.copy2(__file__,OUT/'prepare-am-deployment.py');h=files(OUT);(OUT/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(OUT)==h|{'sha256.json':sha(OUT/'sha256.json')};os.sync();print(json.dumps(report|{'manifest_sha256':sha(OUT/'sha256.json')},indent=2))
