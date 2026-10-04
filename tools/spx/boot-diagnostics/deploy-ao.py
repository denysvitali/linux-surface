#!/usr/bin/python3
"""Install the reviewed AM-to-AO marker-only handoff; select no boot."""
import ast, json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from an_boot_guard import BASE, X as ABORTED, load, recovery, artifacts, files, links, sha, command
P = BASE/'attempts/20261001am'
os.umask(0o077)
SRC = Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
X = BASE/'attempts/20261002ao'
aborted = load()
assert (ABORTED/'reboot-check-failed-unqueued').read_text().strip() == aborted['preboot_id']
assert not (ABORTED/'reboot-check-passed.json').exists()
abort_root = ABORTED/'preboot-abort'
assert files(abort_root) == json.loads((abort_root/'sha256.json').read_text()) | {'sha256.json':sha(abort_root/'sha256.json')}
assert json.loads((abort_root/'report.json').read_text())['boot_occurred'] is False
assert not recovery(aborted).get('next_entry', '')
artifacts(aborted)
prior = json.loads((P/'attempt.json').read_text())
r = json.loads((X/'archive-review.json').read_text())
assert not (X/'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == r['preboot_id']
assert Path('/proc/cmdline').read_text().strip() == r['preboot_cmdline']
assert os.uname().release == r['release'] == prior['release']
assert not recovery(prior).get('next_entry', '')
for path,digest in (prior['sha256'] | prior['recovery_sha256'] | prior['runtime_sha256']).items(): assert sha(path) == digest, path
rev = json.loads((P/'independent-result-review.json').read_text())
assert rev['boot_id'] == r['preboot_id'] and rev['scoped_passed'] and rev['fallback_stopped']
assert command('systemctl','show','spx-am-fallback.timer','-p','ActiveState','--value') != 'active'
assert sha(P/'independent-result-review.json') == r['parent_result_review_sha256']
assert sha(P/'attempt.json') == r['parent_attempt_definition_sha256']
for n,h in r['parent_manifests_sha256'].items():
    root = P/n
    assert sha(root/'sha256.json') == h and files(root) == json.loads((root/'sha256.json').read_text()) | {'sha256.json':h}
assert files(X/'build') == json.loads((X/'build-sha256.json').read_text())
assert links(X/'build') == json.loads((X/'build-symlinks.json').read_text())
assert files(X/'dtb-build') == json.loads((X/'dtb-sha256.json').read_text())
cmdline = prior['cmdline'].replace('spx_attempt=20261001am','spx_attempt=20261002ao')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20261002ao'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20261001am'}
entry = (P/'entry.cfg').read_text().replace(' '+prior['cmdline']+'; then',' '+cmdline+'; then').replace('--id spx-trial-20261001am','--id spx-trial-20261002ao').replace('set spx_diag_attempt=20261001am','set spx_diag_attempt=20261002ao').replace('boot diagnostic 20261001am','boot diagnostic 20261002ao').replace('one-shot AM SPI-HID lifecycle trial','one-shot AO exact-AM handoff trial')
assert all(entry.count('/spx-trial-20261001am/'+n) == 1 for n in ('vmlinuz','initramfs.img','spx.dtb'))
assert entry.count('--id spx-trial-20261002ao') == 1 and entry.count('spx_attempt=20261002ao') == 1
(X/'entry.cfg').write_text(entry)
subprocess.run(['grub-script-check', str(X/'entry.cfg')],check=True,timeout=30)
# Collector/reviewer preserve release and BOOT_IMAGE; every other delta is identity.
for old,new in (('am-finalize.py','ao-finalize.py'),('review-am-result.py','review-ao-result.py')):
    expected = (SRC/old).read_text().replace('20261001am','20261002ao').replace('spx-am-','spx-ao-').replace('AM','AO').replace('7.3.0-rc2-spx-mainline-20261002ao+','7.3.0-rc2-spx-mainline-20261001am+').replace('BOOT_IMAGE=/spx-trial-20261002ao/vmlinuz','BOOT_IMAGE=/spx-trial-20261001am/vmlinuz')
    assert (SRC/new).read_text() == expected
runtime = Path('/usr/local/lib/spx-boot-diagnostics')
helpers = {'ao-finalize.py':runtime/'ao-finalize.py','ao_boot_guard.py':runtime/'ao_boot_guard.py','ao-return.py':runtime/'ao-return.py','ao-reboot-check.py':X/'reboot-check.py'}
exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/113-ao-exclude.conf')
assert not exclude.exists()
for n,p in helpers.items(): assert not p.exists(); ast.parse((SRC/n).read_text())
units = {}
for action,delay in (('finalize',620),('fallback',900)):
    exe = runtime/('ao-finalize.py' if action=='finalize' else 'ao-return.py')
    units[f'spx-ao-{action}.service'] = f'[Unit]\nDescription=AO exact-AM handoff {action}\nConditionKernelCommandLine=spx_attempt=20261002ao\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart={exe}\nTimeoutStartSec=180\n'
    units[f'spx-ao-{action}.timer'] = f'[Unit]\nDescription=AO {action} timer\nConditionKernelCommandLine=spx_attempt=20261002ao\n\n[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ao-{action}.service\n\n[Install]\nWantedBy=timers.target\n'
for n in units: assert not (Path('/etc/systemd/system')/n).exists()
(X/'deploy-started').write_text(r['preboot_id']+'\n')
shutil.copy2('/boot/grub/custom.cfg', X/'custom-before-ao.cfg')
tmp = Path('/boot/grub/custom.cfg.ao-new'); assert not tmp.exists()
tmp.write_text(entry); tmp.chmod(0o644); os.replace(tmp, '/boot/grub/custom.cfg')
for n,p in helpers.items(): shutil.copy2(SRC/n,p); p.chmod(0o755)
for n,text in units.items(): p=Path('/etc/systemd/system')/n; p.write_text(text); p.chmod(0o644)
exclude.write_text('[Unit]\nConditionKernelCommandLine=!spx_attempt=20261002ao\n'); exclude.chmod(0o644)
subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
subprocess.run(['systemctl','enable','spx-ao-finalize.timer','spx-ao-fallback.timer'],check=True,timeout=30)
for n in ('spx-ao-finalize.timer','spx-ao-fallback.timer'):
    assert command('systemctl','is-enabled',n)=='enabled'
    assert command('systemctl','show',n,'-p','ActiveState','--value')!='active'
paths = list(helpers.values()) + [exclude, runtime/'return.sh', runtime/'collect.sh'] + [Path('/etc/systemd/system')/n for n in units]
a = dict(attempt='20261002ao', entry='spx-trial-20261002ao', release=prior['release'], preboot_id=r['preboot_id'], preboot_cmdline=r['preboot_cmdline'], source_commit=prior['source_commit'], source_diff=str(X/'build/source.diff'), build_archive=str(X/'build'), state='prepared AO; no boot selection', sha256=prior['sha256'], recovery_sha256=prior['recovery_sha256'], recovery_definition_sha256=sha(X/'working-recovery.json'), authorization=prior['authorization'], runtime_sha256={str(p):sha(p) for p in paths}, cmdline=cmdline, parent_attempt='20261001am', parent_attempt_definition_sha256=r['parent_attempt_definition_sha256'], parent_result_review_sha256=r['parent_result_review_sha256'], parent_manifests_sha256=r['parent_manifests_sha256'], return_window_seconds=600, comparison=r['comparison'], archive_review_sha256=sha(X/'archive-review.json'), playback_requested=False, early_recovery_validated=False, outgoing_candidate_quiesce_expected=True)
(X/'attempt.json').write_text(json.dumps(a,indent=2)+'\n')
tmp=BASE/'attempt-ao.new.json'; assert not tmp.exists(); tmp.write_text(json.dumps(a,indent=2)+'\n'); os.replace(tmp,BASE/'attempt.json')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==a['preboot_id']
assert not dict(line.split('=',1) for line in command('grub-editenv','/boot/grub/grubenv','list').splitlines() if '=' in line).get('next_entry','')
os.sync()
print('AO installed unselected; exact AM payload/module reuse; timers620/900 enabled/inactive.')
