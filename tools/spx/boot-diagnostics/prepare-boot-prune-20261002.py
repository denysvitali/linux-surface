#!/usr/bin/python3
"""Inventory and preserve exact working boot and all obsolete artifacts before pruning."""
import hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
ROOT=Path('/var/lib/spx-boot-diagnostics/boot-prune-20261002');BID='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5';RELEASE='6.18.3-1-surface+'
KEEP={'/boot/vmlinuz-6.18.3-1-surface+-slimfix':'c202330dbc6b4145b0629a057109745dc803621b94807ec2965ad705818049d9','/boot/initramfs-linux-surface.img':'c3f4c3cd843f45ded2ae79ac12114a5c5988edb2cb6ac9c32a352f2afff4a5a8','/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.wsa':'1ef46c32dde48d197f5683687c88ec3f2d2ecf33f20319b09d45127d49f16a3e'}
BASE={'00_header','09_spxtree','10_linux','20_linux_xen','25_bli','30_os-prober','30_uefi-firmware','40_custom','41_custom','README'}
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
 assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID and os.uname().release==RELEASE
 assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
 env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True);assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
 efi=subprocess.check_output(['efibootmgr'],text=True);assert 'BootNext:' not in efi
 for n,h in KEEP.items():assert sha(n)==h,n
 return env,efi
assert os.geteuid()==0 and not ROOT.exists();env,efi=state();ROOT.mkdir(mode=0o700)
config=Path('/boot/grub/grub.cfg').read_text();source=Path('/etc/grub.d/40_custom').read_text();known=entry(config);assert entry(source)==known
linux=next(s.strip() for s in known.splitlines() if s.strip().startswith('linux ')).split()
assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE='+linux[1]]+linux[2:]
prune=[]
for p in sorted(Path('/boot').iterdir()):
 if p.is_file() and p.name.startswith(('vmlinuz','initramfs')) and str(p) not in KEEP:prune.append(str(p))
 if p.is_dir() and p.name.startswith('spx-trial-'):prune.append(str(p))
for p in sorted(Path('/boot/dtb').iterdir()):
 if p.name!='qcom':prune.append(str(p))
for p in sorted(Path('/boot/dtb/qcom').iterdir()):
 if str(p) not in KEEP:prune.append(str(p))
for p in sorted(Path('/boot/grub').iterdir()):
 if p.is_file() and p.name not in ('grub.cfg','grubenv') and p.name.startswith(('grub.cfg','grubenv.','custom.cfg')):prune.append(str(p))
for name in ('spx-diagnostics','spx-mainline-logs','shutdown-dmesg.log'):
 p=Path('/boot')/name
 if p.exists():prune.append(str(p))
mods=[p for p in sorted(Path('/usr/lib/modules').iterdir()) if p.name!=RELEASE];assert len(mods)==30
assert all(p.is_dir() and not p.is_symlink() and p.name.startswith('7.') for p in mods)
prune.extend(str(p) for p in mods)
old_scripts=[p for p in sorted(Path('/etc/grub.d').iterdir()) if p.name not in BASE];assert all(p.is_file() for p in old_scripts);prune.extend(str(p) for p in old_scripts)
units=[p for p in sorted(Path('/etc/systemd/system').iterdir()) if re.fullmatch(r'spx-[a-z]{1,2}-(fallback|finalize)\.(timer|service)',p.name)];assert all('ConditionKernelCommandLine=spx_attempt=' in p.read_text() for p in units)
for p in units:
 status=subprocess.check_output(['systemctl','show',p.name,'-p','ActiveState','--value'],text=True).strip();assert status in ('inactive','failed'),(p.name,status)
prune.extend(str(p) for p in units)
new40='#!/bin/sh\nexec tail -n +3 $0\n# Only the preserved working SPX combination is installed.\n'+known
new09=Path('/etc/grub.d/09_spxtree').read_text().replace('devicetree /dtb/qcom/sc8180x-surface-pro-x.dtb\n','devicetree /dtb/qcom/sc8180x-surface-pro-x.dtb.wsa\n');assert new09!=Path('/etc/grub.d/09_spxtree').read_text()
preset=Path('/etc/mkinitcpio.d/linux-surface.preset').read_text();newpreset=preset.replace('ALL_kver="/boot/vmlinuz-linux-surface"','ALL_kver="/boot/vmlinuz-6.18.3-1-surface+-slimfix"').replace("PRESETS=('default' 'fallback')","PRESETS=('default')");assert newpreset!=preset
proposed=ROOT/'proposed';proposed.mkdir()
for name,text in [('40_custom',new40),('09_spxtree',new09),('linux-surface.preset',newpreset)]:
 (proposed/name).write_text(text)
 if name=='40_custom':
  emitted=subprocess.check_output(['sh',str(proposed/name)]);assert emitted.decode()==new40.split('\n',2)[2]
  (proposed/'custom-emitted.cfg').write_bytes(emitted);subprocess.run(['grub-script-check',str(proposed/'custom-emitted.cfg')],check=True)
 else:subprocess.run(['bash','-n',str(proposed/name)],check=True)
(ROOT/'known-good-entry.txt').write_text(known);(ROOT/'boot-id.txt').write_text(BID+'\n');(ROOT/'cmdline.txt').write_text(Path('/proc/cmdline').read_text());(ROOT/'grubenv.before.txt').write_text(env);(ROOT/'efibootmgr.before.txt').write_text(efi)
plan={'boot_id':BID,'release':RELEASE,'keep_payload_sha256':KEEP,'kept_module_tree':str(Path('/usr/lib/modules')/RELEASE),'obsolete_module_releases':[p.name for p in mods],'obsolete_grub_scripts':[p.name for p in old_scripts],'obsolete_units':[p.name for p in units],'remove_paths':prune,'boot_free_before':os.statvfs('/boot').f_bavail*os.statvfs('/boot').f_frsize,'working_entry_sha256':hashlib.sha256(known.encode()).hexdigest(),'working_grubenv_sha256':sha('/boot/grub/grubenv'),'source_diff_sha256':hashlib.sha256(subprocess.check_output(['git','diff','--binary','HEAD'],cwd='/home/dvitali/Documents/git/linux-surface-next')).hexdigest(),'user_authorization':'Continue. Keep the working boot combination intact and prune the rest','archives_retained':True,'am_remains_offline':True,'reboot_requested':False}
(ROOT/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
backup=ROOT/'snapshot';backup.mkdir();records={}
for source in ['/boot','/etc/grub.d','/etc/default/grub','/etc/mkinitcpio.d','/etc/systemd/system','/usr/lib/modules']:
 p=Path(source);dst=backup/source.lstrip('/');dst.parent.mkdir(parents=True,exist_ok=True)
 before=tree(p) if p.is_dir() else {p.name:{'sha256':sha(p),'bytes':p.stat().st_size}}
 if p.is_dir():shutil.copytree(p,dst,symlinks=True)
 else:shutil.copy2(p,dst)
 copied=tree(dst) if dst.is_dir() else {dst.name:{'sha256':sha(dst),'bytes':dst.stat().st_size}}
 assert copied==before,source
 after=tree(p) if p.is_dir() else {p.name:{'sha256':sha(p),'bytes':p.stat().st_size}}
 assert before==after,source
 records[source]=before
 print('Preserved and rehashed',source,len(before),'files/links',flush=True)
(ROOT/'snapshot-manifest.json').write_text(json.dumps(records,indent=2)+'\n');env2,efi2=state();assert env2==env and efi2==efi
shutil.copy2(__file__,ROOT/Path(__file__).name)
report={'snapshot_manifest_sha256':sha(ROOT/'snapshot-manifest.json'),'working_entry_exact':True,'working_payload_hashes_verified':3,'working_module_tree_files_links':len(records['/usr/lib/modules'])-sum(n.startswith(tuple(p.name+'/' for p in mods)) for n in records['/usr/lib/modules']),'obsolete_module_releases':len(mods),'obsolete_grub_scripts':len(old_scripts),'obsolete_units':len(units),'remove_paths':len(prune),'snapshot_bytes':sum(r.get('bytes',0) for entries in records.values() for r in entries.values()),'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'boot_id_unchanged':True,'pruning_started':False}
(ROOT/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2),flush=True)
