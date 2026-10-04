#!/usr/bin/python3
"""Prune reviewed archived boot artifacts while preserving the exact known-good entry."""
import hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
ROOT=Path('/var/lib/spx-boot-diagnostics/boot-prune-20261002');SNAP=ROOT/'snapshot';plan=json.loads((ROOT/'plan.json').read_text());archive=json.loads((ROOT/'archive-review.json').read_text());manifest=json.loads((ROOT/'snapshot-manifest.json').read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def tree(p):
 out={}
 for q in sorted(p.rglob('*')):
  n=str(q.relative_to(p))
  if q.is_symlink():out[n]={'symlink':os.readlink(q)}
  elif q.is_file():out[n]={'sha256':sha(q),'bytes':q.stat().st_size}
 return out
def entry(text):
 m=re.search(r'^menuentry [^\n]*--id spx-known-good \{\n(?:[^\n]*\n)*?^\}\n',text,re.M);assert m
 return m.group()
def state():
 assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==plan['boot_id'] and os.uname().release==plan['release']
 assert Path('/proc/cmdline').read_text()==(ROOT/'cmdline.txt').read_text()
 for n,h in plan['keep_payload_sha256'].items():assert sha(n)==h,n
 env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True);assert env==(ROOT/'grubenv.before.txt').read_text() and sha('/boot/grub/grubenv')==plan['working_grubenv_sha256']
 assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
 efi=subprocess.check_output(['efibootmgr'],text=True);assert efi==(ROOT/'efibootmgr.before.txt').read_text() and 'BootNext:' not in efi
 return env,efi
assert os.geteuid()==0 and not (ROOT/'prune-started.json').exists()
assert sha(ROOT/'snapshot-manifest.json')==archive['snapshot_manifest_sha256'];state()
# Recheck every archived source; nothing is removed unless its full private copy matches.
for root,expected in manifest.items():
 p=Path(root);copy=SNAP/root.lstrip('/')
 if p.is_dir():assert tree(p)==tree(copy)==expected,root
 else:assert sha(p)==sha(copy)==expected[p.name]['sha256'],root
 print('Archive/source exact',root,flush=True)
known=(ROOT/'known-good-entry.txt').read_text();assert entry(Path('/boot/grub/grub.cfg').read_text())==known
keep_module=Path(plan['kept_module_tree']);prefix=keep_module.name+'/';kept={n[len(prefix):]:v for n,v in manifest['/usr/lib/modules'].items() if n.startswith(prefix)};assert tree(keep_module)==kept
for n in plan['remove_paths']:
 p=Path(n)
 assert str(p)==n and p.is_absolute() and not p.is_symlink()
 assert all(p!=Path(k) and p not in Path(k).parents for k in plan['keep_payload_sha256'])
 assert p!=keep_module and p not in keep_module.parents
 assert not (p==Path('/boot/EFI') or Path('/boot/EFI') in p.parents or p==Path('/boot/grub'))
 assert p.exists()
for unit in plan['obsolete_units']:
 status=subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','--value'],text=True).strip();assert status in ('inactive','failed'),(unit,status)
(ROOT/'prune-started.json').write_text(json.dumps({'boot_id':plan['boot_id'],'time':time.time(),'archive_verified':True},indent=2)+'\n');shutil.copy2(__file__,ROOT/Path(__file__).name)
records=[]
def run(args,name):
 with (ROOT/name).open('wb') as f:r=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT)
 records.append({'args':args,'log':name,'exit_code':r.returncode});(ROOT/'commands.json').write_text(json.dumps(records,indent=2)+'\n');assert r.returncode==0,(name,(ROOT/name).read_text())
def install(src,dst):
 dst=Path(dst);mode=dst.stat().st_mode & 0o777;tmp=dst.with_name(dst.name+'.spx-prune-new');assert not tmp.exists();shutil.copyfile(src,tmp);os.chmod(tmp,mode);os.replace(tmp,dst)
# Sources are staged and reviewed. Old live menu/payloads remain until generation validates.
install(ROOT/'proposed/40_custom','/etc/grub.d/40_custom');install(ROOT/'proposed/09_spxtree','/etc/grub.d/09_spxtree')
try:
 run(['grub-mkconfig','-o',str(ROOT/'grub.cfg.new')],'grub-mkconfig.log');run(['grub-script-check',str(ROOT/'grub.cfg.new')],'grub-script-check.log')
 cfg=(ROOT/'grub.cfg.new').read_text();assert entry(cfg)==known
 boots=[s for s in cfg.splitlines() if re.match(r'\s*(linux|linuxefi|initrd|initrdefi|devicetree)\s',s)]
 targets={str(Path('/boot')/s.split()[1].lstrip('/')) for s in boots};assert targets==set(plan['keep_payload_sha256']),targets
 assert len(re.findall(r'^menuentry ',cfg,re.M))==1
 assert 'set default="spx-known-good"' in cfg and 'spx-trial-' not in cfg and 'next-test' not in cfg
 state();install(ROOT/'grub.cfg.new','/boot/grub/grub.cfg')
except BaseException:
 for name in ('40_custom','09_spxtree'):install(SNAP/'etc/grub.d'/name,Path('/etc/grub.d')/name)
 raise
install(ROOT/'proposed/linux-surface.preset','/etc/mkinitcpio.d/linux-surface.preset')
timers=[n for n in plan['obsolete_units'] if n.endswith('.timer')]
if timers:run(['systemctl','disable','--now',*timers],'disable-obsolete-timers.log')
removed=[]
for n in plan['remove_paths']:
 p=Path(n)
 if p.is_dir():shutil.rmtree(p)
 else:p.unlink()
 removed.append(n);(ROOT/'removed-paths.json').write_text(json.dumps(removed,indent=2)+'\n')
run(['systemctl','daemon-reload'],'daemon-reload.log');run(['grub-script-check','/boot/grub/grub.cfg'],'final-grub-script-check.log')
env,efi=state();assert entry(Path('/boot/grub/grub.cfg').read_text())==known and tree(keep_module)==kept
assert sorted(p.name for p in Path('/usr/lib/modules').iterdir())==[plan['release']]
assert tree(Path('/boot/EFI'))=={n[len('EFI/'):]:v for n,v in manifest['/boot'].items() if n.startswith('EFI/')}
assert list(Path('/boot/dtb/qcom').iterdir())==[Path('/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.wsa')]
assert sorted(p.name for p in Path('/boot/dtb').iterdir())==['qcom']
assert not list(Path('/boot').glob('spx-trial-*')) and not Path('/boot/grub/custom.cfg').exists()
assert all(not Path(n).exists() for n in removed)
# Apart from the compiled menu and retired artifacts, every surviving boot file is byte-exact.
remaining=tree(Path('/boot'))
for n,v in remaining.items():
 if n!='grub/grub.cfg':assert v==manifest['/boot'][n],n
for p in Path('/etc/systemd/system').rglob('*'):
 if p.is_symlink():assert p.name not in set(plan['obsolete_units']),p
boot_free=os.statvfs('/boot').f_bavail*os.statvfs('/boot').f_frsize
report={'boot_id':plan['boot_id'],'release':plan['release'],'kept_payload_sha256':plan['keep_payload_sha256'],'known_good_entry_byte_exact':True,'known_good_module_files_links_verified':len(kept),'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'efi_loader_files_unchanged':True,'grubenv_byte_exact':True,'all_surviving_boot_files_unchanged_except_menu':True,'removed_paths':len(removed),'obsolete_module_trees_removed':len(plan['obsolete_module_releases']),'obsolete_grub_scripts_removed':len(plan['obsolete_grub_scripts']),'obsolete_trial_units_removed':len(plan['obsolete_units']),'boot_free_before':plan['boot_free_before'],'boot_free_after':boot_free,'boot_bytes_reclaimed':boot_free-plan['boot_free_before'],'new_grub_config_sha256':sha('/boot/grub/grub.cfg'),'snapshot_manifest_sha256':archive['snapshot_manifest_sha256'],'archive_root':str(ROOT),'am_preserved_offline':True,'reboot_performed':False,'trial_selected':False,'pruning_complete':True}
(ROOT/'result.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2),flush=True)
