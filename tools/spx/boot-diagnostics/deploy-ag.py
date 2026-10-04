#!/usr/bin/python3
"""Install AG DTB and silent matching collector, without selecting a boot."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics')
AA=BASE/'attempts/20260930af'; AB=BASE/'attempts/20260930ag'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
BOOT=Path('/boot/spx-trial-20260930ag')
BID='4fe7d83a-37fd-4eb7-800c-850d2aa0885b'
RELEASE='7.3.0-rc2-spx-mainline-20260930ae+'

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
assert command('uname','-r')=='6.18.3-1-surface+' and 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
assert not (AB/'attempt.json').exists()
prior=json.loads((AA/'attempt.json').read_text())
assert prior==json.loads((BASE/'attempt.json').read_text())
assert Path('/boot/grub/custom.cfg').read_text()==(AA/'entry.cfg').read_text()
review=json.loads((AA/'independent-result-review.json').read_text())
assert review['boot_id']=='10c7bf46-31c1-45aa-b087-b0dd74357fa8' and not review['scoped_passed'] and not review['fallback_stopped']
assert command('systemctl','show','spx-af-fallback.timer','-p','ActiveState','--value')!='active'
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
env=command('grub-editenv','/boot/grub/grubenv','list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
archive=json.loads((AB/'archive-review.json').read_text())
assert archive['preboot_id']==BID and not archive['boot_selected']
assert sha(AA/'independent-result-review.json')==archive['prior_result_review_sha256']
recovery=json.loads((AA/'recovery-return/report.json').read_text())
assert recovery['recovery_boot_id']==BID and recovery['userspace_fallback_return_verified']
assert sha(AA/'recovery-return/sha256.json')==archive['prior_recovery_manifest_sha256']
for n,h in json.loads((AA/'recovery-return/sha256.json').read_text()).items():assert sha(AA/'recovery-return'/n)==h,n
assert sha(AB/'build-sha256.json')==archive['build_manifest_sha256']
assert sha(AB/'dtb-sha256.json')==archive['dtb_manifest_sha256']
for root,mf in [('build','build-sha256.json'),('dtb-build','dtb-sha256.json')]:
 for n,h in json.loads((AB/mf).read_text()).items(): assert sha(AB/root/n)==h,n
for n,target in json.loads((AB/'build-symlinks.json').read_text()).items(): assert os.readlink(AB/'build'/n)==target,n
for n,h in json.loads((AB/'build/module-sha256.json').read_text()).items(): assert sha(Path('/usr/lib/modules')/RELEASE/n)==h,n
for n,h in (prior['sha256']|prior['recovery_sha256']|prior['runtime_sha256']).items(): assert sha(n)==h,n
assert sha(REPO/'.config')==archive['config_sha256']
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(AB/'dtb-build/source.diff').read_bytes()
cmdline=prior['cmdline'].replace('spx_attempt=20260930af','spx_attempt=20260930ag')
assert set(cmdline.split())-set(prior['cmdline'].split())=={'spx_attempt=20260930ag'}
assert set(prior['cmdline'].split())-set(cmdline.split())=={'spx_attempt=20260930af'}
entry=(AA/'entry.cfg').read_text()
assert entry.count(' '+prior['cmdline']+'; then')==1
entry=entry.replace(' '+prior['cmdline']+'; then',' '+cmdline+'; then')
entry=entry.replace('--id spx-trial-20260930af','--id spx-trial-20260930ag').replace('set spx_diag_attempt=20260930af','set spx_diag_attempt=20260930ag')
entry=entry.replace('SPX bounded boot diagnostic 20260930af','SPX bounded boot diagnostic 20260930ag').replace('Authorized one-shot AF silent alternate-pin native enumeration trial','Authorized one-shot AG silent right identity matching trial')
entry=entry.replace('devicetree /spx-trial-20260930ae/spx.dtb','devicetree /spx-trial-20260930ag/spx.dtb')
assert entry.count('linux /spx-trial-20260930ae/vmlinuz')==1 and entry.count('initrd /spx-trial-20260930ae/initramfs.img')==1
assert entry.count('--id spx-trial-20260930ag')==1 and entry.count('devicetree /spx-trial-20260930ag/spx.dtb')==1
preview=AB/'entry.preview.cfg'; write(preview,entry)
subprocess.run(['grub-script-check',str(preview)],check=True,timeout=30); preview.unlink()
runtime=Path('/usr/local/lib/spx-boot-diagnostics/ag-finalize.py')
exclude=Path('/etc/systemd/system/spx-diag-long-return.timer.d/105-ag-exclude.conf')
assert not runtime.exists() and not exclude.exists()
units={}
for action,delay in [('finalize',620),('fallback',900)]:
 exe=str(runtime) if action=='finalize' else '/usr/local/lib/spx-boot-diagnostics/return.sh'
 units[f'spx-ag-{action}.service']=(f'[Unit]\nDescription=AG silent identity matching {action}\nConditionKernelCommandLine=spx_attempt=20260930ag\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart={exe}\nTimeoutStartSec=180\n')
 units[f'spx-ag-{action}.timer']=(f'[Unit]\nDescription=AG {action} timer\nConditionKernelCommandLine=spx_attempt=20260930ag\n\n[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ag-{action}.service\n\n[Install]\nWantedBy=timers.target\n')
assert all(not (Path('/etc/systemd/system')/n).exists() for n in units)
write(AB/'deploy-started',BID+'\n')
BOOT.mkdir(mode=0o700)
shutil.copy2(AB/'dtb-build/spx.dtb',BOOT/'spx.dtb')
assert sha(BOOT/'spx.dtb')==archive['boot_payload_sha256']['spx.dtb']
shutil.copy2('/boot/grub/custom.cfg',AB/'custom-before-ag.cfg')
tmp=Path('/boot/grub/custom.cfg.ag-new'); write(tmp,entry,0o644); os.replace(tmp,'/boot/grub/custom.cfg')
write(AB/'entry.cfg',entry)
shutil.copy2(REPO/'tools/spx/boot-diagnostics/ag-reboot-check.py',AB/'reboot-check.py')
shutil.copy2(REPO/'tools/spx/boot-diagnostics/ag-finalize.py',runtime); runtime.chmod(0o755)
for n,s in units.items(): write(Path('/etc/systemd/system')/n,s,0o644)
write(exclude,'[Unit]\nConditionKernelCommandLine=!spx_attempt=20260930ag\n',0o644)
subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
subprocess.run(['systemctl','enable','spx-ag-finalize.timer','spx-ag-fallback.timer'],check=True,timeout=30)
for n in ('spx-ag-finalize.timer','spx-ag-fallback.timer'):
 assert command('systemctl','is-enabled',n)=='enabled'
 assert command('systemctl','show',n,'-p','ActiveState','--value')!='active'
paths=[runtime,exclude,AB/'reboot-check.py',Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
paths += [Path('/etc/systemd/system')/n for n in units]
payloads={p:h for p,h in prior['sha256'].items() if Path(p).name in ('vmlinuz','initramfs.img')}
payloads[str(BOOT/'spx.dtb')]=sha(BOOT/'spx.dtb')
a={'attempt':'20260930ag','entry':'spx-trial-20260930ag','release':RELEASE,'preboot_id':BID,
 'source_commit':prior['source_commit'],'source_diff':str(AB/'dtb-build/source.diff'),'build_archive':str(AB/'build'),
 'state':'prepared AG; no boot selection','sha256':payloads,'recovery_sha256':prior['recovery_sha256'],
 'authorization':prior['authorization'],'runtime_sha256':{str(p):sha(p) for p in paths},'cmdline':cmdline,
 'parent_attempt':'20260930af','return_window_seconds':600,'playback_requested':False,
 'comparison':'Exact AE kernel/modules/initramfs and selectors; only right DT compatible 2010 -> 2110',
 'archive_review_sha256':sha(AB/'archive-review.json')}
write(AB/'attempt.json',json.dumps(a,indent=2)+'\n')
tmp=BASE/'attempt-ag.new.json'; write(tmp,json.dumps(a,indent=2)+'\n'); os.replace(tmp,BASE/'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BID
assert 'next_entry=' in command('grub-editenv','/boot/grub/grubenv','list').splitlines()
os.sync(); print('AG installed; exact AE kernel/initramfs, new right-identity DTB, no selection or PCM scheduled')
