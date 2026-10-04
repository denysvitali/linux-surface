#!/usr/bin/python3
"""Install AB DTB and silent matching collector, without selecting a boot."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics')
AA=BASE/'attempts/20260930aa'; AB=BASE/'attempts/20260930ab'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT=Path('/boot/spx-trial-20260930ab')
BID='4c68904a-46a5-4eb8-a9ee-3991fbb3c243'
RELEASE='7.3.0-rc2-spx-mainline-20260930aa+'

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()

def command(*args):
 return subprocess.check_output(args,text=True,timeout=90).strip()

def write(p,s,mode=0o600):
 with Path(p).open('x') as f:
  f.write(s); f.flush(); os.fsync(f.fileno())
 Path(p).chmod(mode)

assert os.geteuid()==0 and not (AB/'deploy-started').exists() and not BOOT.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert command('uname','-r')==RELEASE and 'spx_attempt=20260930aa' in Path('/proc/cmdline').read_text().split()
assert not (AB/'attempt.json').exists()
prior=json.loads((AA/'attempt.json').read_text())
assert prior==json.loads((BASE/'attempt.json').read_text())
assert Path('/boot/grub/custom.cfg').read_text()==(AA/'entry.cfg').read_text()
review=json.loads((AA/'independent-result-review.json').read_text())
assert review['boot_id']==BID and review['scoped_passed'] and review['fallback_stopped']
assert command('systemctl','show','spx-aa-fallback.timer','-p','ActiveState','--value')!='active'
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env=command('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
archive=json.loads((AB/'archive-review.json').read_text())
assert archive['preboot_id']==BID and not archive['boot_selected']
assert sha(AB/'build-sha256.json')==archive['build_manifest_sha256']
assert sha(AB/'dtb-sha256.json')==archive['dtb_manifest_sha256']
for root,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:
 for n,h in json.loads((AB/mf).read_text()).items(): assert sha(AB/root/n)==h,n
for n,target in json.loads((AB/'build-symlinks.json').read_text()).items(): assert os.readlink(AB/'build'/n)==target,n
for n,h in json.loads((AB/'build/module-sha256.json').read_text()).items(): assert sha(Path('/usr/lib/modules')/RELEASE/n)==h,n
for n,h in (prior['sha256']|prior['recovery_sha256']|prior['runtime_sha256']).items(): assert sha(n)==h,n
assert sha(REPO/'.config')==archive['config_sha256']
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(AB/'dtb-build/source.diff').read_bytes()
cmdline=prior['cmdline'].replace('spx_attempt=20260930aa','spx_attempt=20260930ab')
assert set(cmdline.split())-set(prior['cmdline'].split())=={'spx_attempt=20260930ab'}
assert set(prior['cmdline'].split())-set(cmdline.split())=={'spx_attempt=20260930aa'}
entry=(AA/'entry.cfg').read_text()
assert entry.count(' '+prior['cmdline']+'; then')==1
entry=entry.replace(' '+prior['cmdline']+'; then',' '+cmdline+'; then')
entry=entry.replace('--id spx-trial-20260930aa','--id spx-trial-20260930ab').replace('set spx_diag_attempt=20260930aa','set spx_diag_attempt=20260930ab')
entry=entry.replace('SPX bounded boot diagnostic 20260930aa','SPX bounded boot diagnostic 20260930ab').replace('Authorized one-shot AA silent enumerator identity trial','Authorized one-shot AB silent left identity matching trial')
entry=entry.replace('devicetree /spx-trial-20260930aa/spx.dtb','devicetree /spx-trial-20260930ab/spx.dtb')
assert entry.count('linux /spx-trial-20260930aa/vmlinuz')==1 and entry.count('initrd /spx-trial-20260930aa/initramfs.img')==1
assert entry.count('--id spx-trial-20260930ab')==1 and entry.count('devicetree /spx-trial-20260930ab/spx.dtb')==1
preview=AB/'entry.preview.cfg'; write(preview,entry)
subprocess.run(['grub-script-check',str(preview)],check=True,timeout=30); preview.unlink()
runtime=Path('/usr/local/lib/spx-boot-diagnostics/ab-finalize.py')
exclude=Path('/etc/systemd/system/spx-diag-long-return.timer.d/100-ab-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units={}
for action,delay in [('finalize',620),('fallback',900)]:
 exe=str(runtime) if action=='finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
 units[f'spx-ab-{action}.service']=(f'[Unit]\nDescription=AB silent identity matching {action}\nConditionKernelCommandLine=spx_attempt=20260930ab\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart={exe}\nTimeoutStartSec=180\n')
 units[f'spx-ab-{action}.timer']=(f'[Unit]\nDescription=AB {action} timer\nConditionKernelCommandLine=spx_attempt=20260930ab\n\n[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ab-{action}.service\n\n[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system')/n).exists() for n in units)
write(AB/'deploy-started',BID+'\n')
BOOT.mkdir(mode=0o700)
shutil.copy2(AB/'dtb-build/spx.dtb',BOOT/'spx.dtb')
assert sha(BOOT/'spx.dtb')==archive['boot_payload_sha256']['spx.dtb']
shutil.copy2('/boot/grub/custom.cfg',AB/'custom-before-ab.cfg')
tmp=Path('/boot/grub/custom.cfg.ab-new'); write(tmp,entry,0o644); os.replace(tmp,'/boot/grub/custom.cfg')
write(AB/'entry.cfg',entry)
shutil.copy2(REPO/'tools/spx/boot-diagnostics/ab-reboot-check.py',AB/'reboot-check.py')
shutil.copy2(REPO/'tools/spx/boot-diagnostics/ab-finalize.py',runtime); runtime.chmod(0o755)
for n,s in units.items(): write(Path('/etc/systemd/system')/n,s,0o644)
write(exclude,'[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930ab\n',0o644)
subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
subprocess.run(['systemctl','enable','spx-ab-finalize.timer','spx-ab-fallback.timer'],check=True,timeout=30)
for n in ('spx-ab-finalize.timer','spx-ab-fallback.timer'):
 assert command('systemctl','is-enabled',n)=='enabled'
 assert command('systemctl','show',n,'-p','ActiveState','--value')!='active'
paths=[runtime,exclude,AB/'reboot-check.py',Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
paths += [Path('/etc/systemd/system')/n for n in units]
payloads={p:h for p,h in prior['sha256'].items() if Path(p).name in ('vmlinuz','initramfs.img')}
payloads[str(BOOT/'spx.dtb')]=sha(BOOT/'spx.dtb')
a={'attempt':'20260930ab','entry':'spx-trial-20260930ab','release':RELEASE,'preboot_id':BID,
 'source_commit':prior['source_commit'],'source_diff':str(AB/'dtb-build/source.diff'),'build_archive':str(AB/'build'),
 'state':'prepared AB; no boot selection','sha256':payloads,'recovery_sha256':prior['recovery_sha256'],
 'authorization':prior['authorization'],'runtime_sha256':{str(p):sha(p) for p in paths},'cmdline':cmdline,
 'parent_attempt':'20260930aa','return_window_seconds':600,'playback_requested':False,
 'comparison':'Exact AA kernel/modules/initramfs and selectors; only left DT compatible 2010 -> 2110',
 'archive_review_sha256':sha(AB/'archive-review.json')}
write(AB/'attempt.json',json.dumps(a,indent=2)+'\n')
tmp=BASE/'attempt-ab.new.json'; write(tmp,json.dumps(a,indent=2)+'\n'); os.replace(tmp,BASE/'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert 'next_entry=' in command('grub-editenv','/boot/grub/grubenv','list').splitlines()
os.sync(); print('AB installed; exact AA kernel/initramfs, new left-identity DTB, no selection or PCM scheduled')
