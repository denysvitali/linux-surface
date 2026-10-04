#!/usr/bin/python3
"""Install the reviewed AO-to-AP ramoops handoff; select no boot."""
import ast, re, json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ao_boot_guard import BASE,X as P,load,recovery,artifacts,files,links,sha,command
from ap_boot_guard import source_provenance
os.umask(0o077)
SRC=Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
X=BASE/'attempts/20261002ap'
prior=load()
source_provenance(X/'source-provenance',X/'build/source.diff',SRC.parents[2])
artifacts(prior)
r = json.loads((X/'archive-review.json').read_text())
assert not (X/'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == r['preboot_id']
assert Path('/proc/cmdline').read_text().strip() == r['preboot_cmdline']
assert os.uname().release == r['release'] == prior['release']
assert not recovery(prior).get('next_entry', '')
for path,digest in (prior['sha256'] | prior['recovery_sha256'] | prior['runtime_sha256']).items(): assert sha(path) == digest, path
rev = json.loads((P/'independent-result-review.json').read_text())
assert rev['boot_id'] == r['preboot_id'] and rev['scoped_passed'] and rev['fallback_stopped']
assert command('systemctl','show','spx-ao-fallback.timer','-p','ActiveState','--value') != 'active'
assert sha(P/'independent-result-review.json') == r['parent_result_review_sha256']
assert sha(P/'attempt.json') == r['parent_attempt_definition_sha256']
for n,h in r['parent_manifests_sha256'].items():
    root = P/n
    assert sha(root/'sha256.json') == h and files(root) == json.loads((root/'sha256.json').read_text()) | {'sha256.json':h}
assert files(X/'build') == json.loads((X/'build-sha256.json').read_text())
assert links(X/'build') == json.loads((X/'build-symlinks.json').read_text())
assert files(X/'dtb-build') == json.loads((X/'dtb-sha256.json').read_text())
cmdline = prior['cmdline'].replace('spx_attempt=20261002ao','spx_attempt=20261002ap')+' ramoops.dyndbg=+p'
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20261002ap','ramoops.dyndbg=+p'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20261002ao'}
entry = (P/'entry.cfg').read_text().replace(' '+prior['cmdline']+'; then',' '+cmdline+'; then').replace('--id spx-trial-20261002ao','--id spx-trial-20261002ap').replace('set spx_diag_attempt=20261002ao','set spx_diag_attempt=20261002ap').replace('boot diagnostic 20261002ao','boot diagnostic 20261002ap').replace('one-shot AO exact-AM handoff trial','one-shot AP ramoops persistence trial')
assert all(entry.count('/spx-trial-20261001am/'+n) == 1 for n in ('vmlinuz','initramfs.img','spx.dtb'))
assert entry.count('--id spx-trial-20261002ap') == 1 and entry.count('spx_attempt=20261002ap') == 1
(X/'entry.cfg').write_text(entry)
subprocess.run(['grub-script-check', str(X/'entry.cfg')],check=True,timeout=30)
# Collector/reviewer preserve release and BOOT_IMAGE; every other delta is identity.
for old,new in (('ao-finalize.py','ap-finalize.py'),('review-ao-result.py','review-ap-result.py')):
    expected=re.sub(r'\bAO\b','AP',(SRC/old).read_text().replace('20261002ao','20261002ap').replace('spx-ao-','spx-ap-'))
    assert (SRC/new).read_text()==expected
runtime = Path('/usr/local/lib/spx-boot-diagnostics')
helpers = {'ap-finalize.py':runtime/'ap-finalize.py','ap_boot_guard.py':runtime/'ap_boot_guard.py','ap-return.py':runtime/'ap-return.py','ap-reboot-check.py':X/'reboot-check.py'}
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/114-ap-exclude.conf')
assert not exclude.exists()
for n,p in helpers.items(): assert not p.exists(); ast.parse((SRC/n).read_text())
units = {}
for action,delay in (('finalize',620),('fallback',900)):
    exe = runtime/('ap-finalize.py' if action=='finalize' else 'ap-return.py')
    units[f'spx-ap-{action}.service'] = f'[Unit]\nDescription=AP ramoops persistence {action}\nConditionKernelCommandLine=spx_attempt=20261002ap\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart={exe}\nTimeoutStartSec=180\n'
    units[f'spx-ap-{action}.timer'] = f'[Unit]\nDescription=AP {action} timer\nConditionKernelCommandLine=spx_attempt=20261002ap\n\n[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ap-{action}.service\n\n[Install]\nWantedBy=timers.target\n'
for n in units: assert not (Path('/etc/systemd/system')/n).exists()
(X/'deploy-started').write_text(r['preboot_id']+'\n')
shutil.copy2('/boot/grub/custom.cfg', X/'custom-before-ap.cfg')
tmp = Path('/boot/grub/custom.cfg.ap-new'); assert not tmp.exists()
tmp.write_text(entry); tmp.chmod(0o644); os.replace(tmp, '/boot/grub/custom.cfg')
for n,p in helpers.items(): shutil.copy2(SRC/n,p); p.chmod(0o755)
for n,text in units.items(): p=Path('/etc/systemd/system')/n; p.write_text(text); p.chmod(0o644)
exclude.write_text('[Unit]\nConditionKernelCommandLine=!spx_attempt=20261002ap\n'); exclude.chmod(0o644)
subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
subprocess.run(['systemctl','enable','spx-ap-finalize.timer','spx-ap-fallback.timer'],check=True,timeout=30)
for n in ('spx-ap-finalize.timer','spx-ap-fallback.timer'):
    assert command('systemctl','is-enabled',n)=='enabled'
    assert command('systemctl','show',n,'-p','ActiveState','--value')!='active'
paths = list(helpers.values()) + [exclude, runtime/'return.sh', runtime/'collect.sh'] + [Path('/etc/systemd/system')/n for n in units]
a = dict(attempt='20261002ap', entry='spx-trial-20261002ap', release=prior['release'], preboot_id=r['preboot_id'], preboot_cmdline=r['preboot_cmdline'], source_commit=prior['source_commit'], source_diff=str(X/'build/source.diff'), build_archive=str(X/'build'), state='prepared AP; no boot selection', sha256=prior['sha256'], recovery_sha256=prior['recovery_sha256'], recovery_definition_sha256=sha(X/'working-recovery.json'), authorization=prior['authorization'], runtime_sha256={str(p):sha(p) for p in paths}, cmdline=cmdline, parent_attempt='20261002ao', parent_attempt_definition_sha256=r['parent_attempt_definition_sha256'], parent_result_review_sha256=r['parent_result_review_sha256'], parent_manifests_sha256=r['parent_manifests_sha256'], return_window_seconds=600, comparison=r['comparison'], archive_review_sha256=sha(X/'archive-review.json'), playback_requested=False, early_recovery_validated=False, outgoing_candidate_quiesce_expected=True, checklist_ids=['R01','I01'], source_provenance_manifest_sha256=r['source_provenance_manifest_sha256'])
(X/'attempt.json').write_text(json.dumps(a,indent=2)+'\n')
tmp=BASE/'attempt-ap.new.json'; assert not tmp.exists(); tmp.write_text(json.dumps(a,indent=2)+'\n'); os.replace(tmp,BASE/'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==a['preboot_id']
assert not dict(line.split('=',1) for line in command('grub-editenv','/boot/grub/grubenv','list').splitlines() if '=' in line).get('next_entry','')
os.sync()
print('AP installed unselected; exact AM payload/module reuse; timers620/900 enabled/inactive.')
