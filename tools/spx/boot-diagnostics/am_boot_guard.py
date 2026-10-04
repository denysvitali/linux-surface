#!/usr/bin/python3
"""Shared AM guards for exact working recovery and distinct trial artifacts."""
import hashlib,json,os,re,subprocess
from pathlib import Path
BASE=Path('/var/lib/spx-boot-diagnostics');X=BASE/'attempts/20261001am';RELEASE='7.3.0-rc2-spx-mainline-20261001am+'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def command(*args):return subprocess.check_output(args,text=True,timeout=90).strip()
def files(p):return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
def links(p):return {str(q.relative_to(p)):os.readlink(q) for q in sorted(p.rglob('*')) if q.is_symlink()}
def entry(text):
 m=re.search(r'^menuentry [^\n]*--id spx-known-good \{\n(?:[^\n]*\n)*?^\}\n',text,re.M);assert m
 return m.group()
def load():
 assert os.geteuid()==0
 a=json.loads((X/'attempt.json').read_text());assert a==json.loads((BASE/'attempt.json').read_text())
 assert a['attempt']=='20261001am' and a['entry']=='spx-trial-20261001am' and a['release']==RELEASE
 return a
def recovery(a):
 assert sha(X/'working-recovery.json')==a['recovery_definition_sha256']
 r=json.loads((X/'working-recovery.json').read_text());assert r['payload_sha256']==a['recovery_sha256']
 for p,h in r['payload_sha256'].items():assert sha(p)==h,p
 root=Path('/usr/lib/modules/6.18.3-1-surface+');actual={}
 for p in root.rglob('*'):
  n=str(p.relative_to(root))
  if p.is_symlink():actual[n]={'symlink':os.readlink(p)}
  elif p.is_file():actual[n]={'sha256':sha(p),'bytes':p.stat().st_size}
 assert actual==r['module_files_links'] and len(actual)==5183
 assert entry(Path('/boot/grub/grub.cfg').read_text())==r['entry']
 assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
 for p,h in r['efi_sha256'].items():assert sha(p)==h,p
 env=dict(s.split('=',1) for s in command('grub-editenv','/boot/grub/grubenv','list').splitlines() if '=' in s)
 assert env.get('saved_entry')=='spx-known-good' and 'BootNext:' not in command('efibootmgr')
 return env
def artifacts(a):
 for p,h in (a['sha256']|a['recovery_sha256']|a['runtime_sha256']).items():assert sha(p)==h,p
 mods=json.loads((X/'build/module-sha256.json').read_text());assert len(mods)==202 and files(Path('/usr/lib/modules')/RELEASE)==mods
 assert files(X/'deployment-sources')==json.loads((X/'deployment-sources-sha256.json').read_text())
 for n,h in json.loads((X/'dtb-sha256.json').read_text()).items():assert sha(X/'dtb-build'/n)==h,n
 assert Path('/boot/grub/custom.cfg').read_text()==(X/'entry.cfg').read_text()
 for timer in ('spx-am-finalize.timer','spx-am-fallback.timer'):assert command('systemctl','is-enabled',timer)=='enabled'
def preboot(a,pending=''):
 assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==a['preboot_id']
 assert os.uname().release=='6.18.3-1-surface+' and Path('/proc/cmdline').read_text().strip()==a['preboot_cmdline']
 assert float(Path('/proc/uptime').read_text().split()[0])>=120
 env=recovery(a);assert env.get('next_entry','')==pending
 artifacts(a)
 for timer in ('spx-am-finalize.timer','spx-am-fallback.timer'):assert command('systemctl','show',timer,'-p','ActiveState','--value')!='active'
 assert '!spx_attempt=20261001am' in Path('/etc/systemd/system/spx-diag-long-return.timer.d/111-am-exclude.conf').read_text()
 return env
