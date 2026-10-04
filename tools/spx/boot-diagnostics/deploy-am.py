#!/usr/bin/python3
"""Install distinct AM beside exact working recovery, without selection or live driver actions."""
import ast,hashlib,json,os,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');SRC=REPO/'tools/spx/boot-diagnostics';BASE=Path('/var/lib/spx-boot-diagnostics');X=BASE/'attempts/20261001am';PREP=X/'deployment-preparation';BOOT=Path('/boot/spx-trial-20261001am');R='7.3.0-rc2-spx-mainline-20261001am+'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def write(p,s,mode=0o600):
 with Path(p).open('x') as f:f.write(s);f.flush();os.fsync(f.fileno())
 Path(p).chmod(mode)
def run(args,name):
 with (X/name).open('wb') as f:r=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,timeout=180)
 assert r.returncode==0,(name,(X/name).read_text())
assert os.geteuid()==0 and not (X/'deploy-started').exists() and not BOOT.exists() and not (Path('/usr/lib/modules')/R).exists()
p=json.loads((PREP/'report.json').read_text());h=json.loads((PREP/'sha256.json').read_text());assert files(PREP)==h|{'sha256.json':sha(PREP/'sha256.json')}
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==p['preboot_id'] and Path('/proc/cmdline').read_text().strip()==p['preboot_cmdline']
assert os.uname().release=='6.18.3-1-surface+'
assert not Path('/boot/grub/custom.cfg').exists() and not (X/'attempt.json').exists()
env=subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in subprocess.check_output(['efibootmgr'],text=True)
r=json.loads((PREP/'working-recovery.json').read_text());assert sha(PREP/'working-recovery.json')==p['working_recovery_sha256']
for n,d in r['payload_sha256'].items():assert sha(n)==d,n
assert (PREP/'grub.cfg').read_bytes()==Path('/boot/grub/grub.cfg').read_bytes()
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(X/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
archive=json.loads((X/'archive-review.json').read_text());assert sha(X/'build-sha256.json')==archive['build_manifest_sha256']
mods=json.loads((X/'build/module-sha256.json').read_text());mroot=X/'build/module-root/lib/modules'/R;assert len(mods)==202 and files(mroot)==mods
entry=(PREP/'entry.cfg').read_text();run(['grub-script-check',str(PREP/'entry.cfg')],'entry-preinstall-check.log')
required=sum((X/'build'/n).stat().st_size for n in ('vmlinuz','initramfs.img'))+1048576;space=os.statvfs('/boot');assert space.f_bavail*space.f_frsize>required
runtime=Path('/usr/local/lib/spx-boot-diagnostics');exclude=Path('/etc/systemd/system/spx-diag-long-return.timer.d/111-am-exclude.conf');assert not exclude.exists()
helpers={'am-finalize.py':runtime/'am-finalize.py','am_boot_guard.py':runtime/'am_boot_guard.py','am-return.py':runtime/'am-return.py','am-reboot-check.py':X/'reboot-check.py'}
for name,dst in helpers.items():assert not dst.exists();ast.parse((SRC/name).read_text())
units={}
for action,delay in (('finalize',620),('fallback',900)):
 executable=str(runtime/('am-finalize.py' if action=='finalize' else 'am-return.py'))
 units[f'spx-am-{action}.service']=f'[Unit]\nDescription=AM SPI-HID lifecycle trial {action}\nConditionKernelCommandLine=spx_attempt=20261001am\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart={executable}\nTimeoutStartSec=180\n'
 units[f'spx-am-{action}.timer']=f'[Unit]\nDescription=AM {action} timer\nConditionKernelCommandLine=spx_attempt=20261001am\n\n[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-am-{action}.service\n\n[Install]\nWantedBy=timers.target\n'
for name in units:assert not (Path('/etc/systemd/system')/name).exists()
write(X/'deploy-started',p['preboot_id']+'\n');shutil.copy2(PREP/'working-recovery.json',X/'working-recovery.json');shutil.copytree(mroot,Path('/usr/lib/modules')/R,symlinks=True);assert files(Path('/usr/lib/modules')/R)==mods
BOOT.mkdir(mode=0o700);sources={'vmlinuz':X/'build/vmlinuz','initramfs.img':X/'build/initramfs.img','spx.dtb':X/'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'}
for name,src in sources.items():shutil.copy2(src,BOOT/name);assert sha(BOOT/name)==sha(src),name
write(X/'entry.cfg',entry);tmp=Path('/boot/grub/custom.cfg.am-new');write(tmp,entry,0o644);os.replace(tmp,'/boot/grub/custom.cfg')
# Restore the standard custom-menu loader's execution bit; exact recovery entry stays in40_custom.
assert Path('/etc/grub.d/41_custom').read_bytes()==(PREP/'41_custom').read_bytes();os.chmod('/etc/grub.d/41_custom',0o755)
run(['grub-mkconfig','-o',str(X/'grub.cfg.installed-preview')],'grub-mkconfig-install.log');run(['grub-script-check',str(X/'grub.cfg.installed-preview')],'grub-preview-check.log')
assert r['entry'] in (X/'grub.cfg.installed-preview').read_text() and 'source ${config_directory}/custom.cfg' in (X/'grub.cfg.installed-preview').read_text()
tmp=Path('/boot/grub/grub.cfg.am-new');assert not tmp.exists();shutil.copyfile(X/'grub.cfg.installed-preview',tmp);os.chmod(tmp,0o644);os.replace(tmp,'/boot/grub/grub.cfg')
for name,dst in helpers.items():shutil.copy2(SRC/name,dst);dst.chmod(0o755)
for name,content in units.items():write(Path('/etc/systemd/system')/name,content,0o644)
write(exclude,'[Unit]\nConditionKernelCommandLine=!spx_attempt=20261001am\n',0o644)
run(['systemctl','daemon-reload'],'am-daemon-reload.log');run(['systemctl','enable','spx-am-finalize.timer','spx-am-fallback.timer'],'am-enable-timers.log')
for name in ('spx-am-finalize.timer','spx-am-fallback.timer'):
 assert subprocess.check_output(['systemctl','is-enabled',name],text=True).strip()=='enabled'
 assert subprocess.check_output(['systemctl','show',name,'-p','ActiveState','--value'],text=True).strip()!='active'
paths=list(helpers.values())+[exclude,Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]+[Path('/etc/systemd/system')/n for n in units]
a={'attempt':'20261001am','entry':'spx-trial-20261001am','release':R,'preboot_id':p['preboot_id'],'preboot_cmdline':p['preboot_cmdline'],'source_commit':(X/'build/source-commit.txt').read_text().strip(),'source_diff':str(X/'build/source.diff'),'build_archive':str(X/'build'),'state':'prepared AM; no boot selection','sha256':{str(BOOT/n):sha(BOOT/n) for n in sources},'recovery_sha256':r['payload_sha256'],'recovery_definition_sha256':sha(X/'working-recovery.json'),'authorization':p['authorization'],'runtime_sha256':{str(n):sha(n) for n in paths},'cmdline':p['cmdline'],'parent_attempt':'20260930al','reference_selectors_attempt':'20260930ak','return_window_seconds':600,'comparison':'SPI-HID lifecycle source plus LOCALVERSION; exact AK pin2/native0/cmd_diag1 selectors and strict620/900; no playback','archive_review_sha256':sha(X/'archive-review.json'),'playback_requested':False,'early_recovery_validated':False,'outgoing_candidate_quiesce_expected':False}
write(X/'attempt.json',json.dumps(a,indent=2)+'\n');tmp=BASE/'attempt-am.new.json';write(tmp,json.dumps(a,indent=2)+'\n');os.replace(tmp,BASE/'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==p['preboot_id'];assert 'next_entry=' in subprocess.check_output(['grub-editenv','/boot/grub/grubenv','list'],text=True).splitlines();os.sync();print('AM installed alongside exact known-good; timers enabled/inactive, no boot selected')
