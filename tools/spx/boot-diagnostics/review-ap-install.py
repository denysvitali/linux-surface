#!/usr/bin/python3
"""Independently rehash AP reuse, strict scope, inactive units and outgoing baseline."""
import ast, fcntl, json, re, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ap_boot_guard import BASE, X, load, preboot, files, links, sha, command
os.umask(0o077)
SRC = Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
a = load()
assert not (X/'installed-review.json').exists()
archive = json.loads((X/'archive-review.json').read_text())
assert archive['parent_result_manifest_sha256'] == a['parent_manifests_sha256']['final-result']
assert archive['parent_post_result_manifest_sha256'] == a['parent_manifests_sha256']['post-result-records']
assert sha(X/'build-sha256.json') == archive['build_manifest_sha256']
assert files(X/'build') == json.loads((X/'build-sha256.json').read_text())
assert links(X/'build') == json.loads((X/'build-symlinks.json').read_text())
assert files(X/'dtb-build') == json.loads((X/'dtb-sha256.json').read_text())
assert sorted(p.name for p in Path('/usr/lib/modules').iterdir()) == sorted(['6.18.3-1-surface+', a['release']])
assert sorted(p.name for p in Path('/boot').glob('spx-trial-*')) == ['spx-trial-20261001am']
for old,new in (('ao-finalize.py','ap-finalize.py'),('review-ao-result.py','review-ap-result.py')):
    expected=re.sub(r'\bAO\b','AP',(SRC/old).read_text().replace('20261002ao','20261002ap').replace('spx-ao-','spx-ap-'))
    assert (SRC/new).read_text()==expected

def assignment(t,n):
    return next(x.value for x in ast.walk(t) if isinstance(x,ast.Assign) and any(isinstance(y,ast.Name) and y.id==n for y in x.targets))
old=ast.parse((SRC/'ao-finalize.py').read_text()); new=ast.parse((SRC/'ap-finalize.py').read_text())
same=('passed','native_path_passed','touch_diag_passed','healthy','power_path_passed','pin_state_passed','pin2_diagnostic','topology_preserved','declared_names','firmware_identity_match','identity_diag_passed','right_init')
for n in same: assert ast.dump(assignment(old,n))==ast.dump(assignment(new,n)),n
passed=assignment(new,'passed'); scope={n.id:True for n in ast.walk(passed) if isinstance(n,ast.Name) and n.id!='len'}
scope.update(right_init=1,slim_devices=['a','b'],no_cards=False,force_start=0,force_done=0,force_slaves=0,attached=1,wsa_mode='Y',wsa_init=1,wsa_init_fail=0,wsa_status_fail=0,wsa_write_overflows=0,wsa_read_underflows=0,taint='0')
judge=compile(ast.Expression(passed),'AP-scope','eval'); assert eval(judge,{},scope)
for patch in ({'cmd_diag_passed':False},{'native_path_passed':False},{'right_init':0},{'topology_preserved':False},{'pin_state_passed':False},{'touch':False}): assert not eval(judge,{},scope|patch)
for action,delay in (('finalize',620),('fallback',900)):
    unit=Path('/etc/systemd/system')/f'spx-ap-{action}.timer'
    assert f'OnBootSec={delay}\n' in unit.read_text()
    for p in (unit,unit.with_suffix('.service')): assert 'ConditionKernelCommandLine=spx_attempt=20261002ap\n' in p.read_text()
    assert command('systemctl','is-enabled',unit.name)=='enabled'
    assert command('systemctl','show',unit.name,'-p','ActiveState','--value')!='active'
with (X/'units-verify.log').open('wb') as f:
    subprocess.run(['systemd-analyze','verify']+[str(Path('/etc/systemd/system')/f'spx-ap-{a}.{t}') for a in ('finalize','fallback') for t in ('timer','service')],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=30)
for p in ('/boot/grub/grub.cfg','/boot/grub/custom.cfg'): subprocess.run(['grub-script-check',p],check=True,timeout=30)
names=('prepare-ap.py','deploy-ap.py','ap_boot_guard.py','ap-return.py','ap-reboot-check.py','ap-finalize.py','review-ap-result.py','review-ap-install.py','verify-ap-boot-guards.py','queue-ap-once.py','verify-ap-archive-guards.py')
dst=X/'deployment-sources'; assert not dst.exists(); dst.mkdir(mode=0o700)
for n in names: shutil.copy2(SRC/n,dst/n)
(X/'deployment-sources-sha256.json').write_text(json.dumps(files(dst),indent=2)+'\n')
with (X/'boot-guards-test.log').open('wb') as f:
    subprocess.run(['/usr/bin/python3',str(SRC/'verify-ap-boot-guards.py')],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=30)
with (X/'archive-guards-test.log').open('wb') as f:
    subprocess.run(['/usr/bin/python3',str(SRC/'verify-ap-archive-guards.py')],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=30)
env=preboot(a)
# No touch/audio test: capture existing kernel and userspace observations only.
subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'],check=True,timeout=90)
snapshot=X/'preboot-snapshot'; assert not snapshot.exists(); snapshot.mkdir(mode=0o700)
collector=BASE/'boots'/a['preboot_id']
with (collector/'collect.lock').open('a') as f:
    fcntl.flock(f,fcntl.LOCK_EX)
    shutil.copytree(collector,snapshot/'collector',symlinks=True)
for n,p in (('boot-id','/proc/sys/kernel/random/boot_id'),('cmdline','/proc/cmdline'),('uptime','/proc/uptime')): (snapshot/n).write_text(Path(p).read_text())
(snapshot/'dmesg-raw.log').write_text(command('dmesg','--raw')+'\n')
(snapshot/'kernel.log').write_text(command('journalctl','-b','-k','-o','short-monotonic','--no-pager')+'\n')
(snapshot/'grubenv').write_text(command('grub-editenv','/boot/grub/grubenv','list')+'\n')
(snapshot/'pstore-baseline-sha256.json').write_text(json.dumps({n:files(snapshot/'collector'/n) for n in ('pstore','pstore-archive')},indent=2)+'\n')
h=files(snapshot); (snapshot/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
assert files(snapshot)==h|{'sha256.json':sha(snapshot/'sha256.json')}
preboot(a)
r=dict(preboot_id=a['preboot_id'], exact_am_artifacts=True, release=a['release'], modules_verified=202, working_module_files_links_verified=5183, build_files_verified=len(json.loads((X/'build-sha256.json').read_text())), build_symlinks_verified=len(json.loads((X/'build-symlinks.json').read_text())), strict_am_scope_unchanged=True, strict_scope_expressions=len(same), strict_negative_cases=6, guard_preboot_positive_cases=2, guard_preboot_negative_cases=11, guard_fallback_positive_cases=1, guard_fallback_negative_cases=8, payload_recovery_runtime_files_verified=17, outgoing_snapshot_files_verified=len(h), outgoing_snapshot_manifest_sha256=sha(snapshot/'sha256.json'), deployment_sources_manifest_sha256=sha(X/'deployment-sources-sha256.json'), known_good_default=True, next_entry_empty=True, efi_bootnext_absent=True, boot_selected=False, callback_execution_verified=False, physical_rail_off_verified=False, efi_early_recovery_validated=False, playback_requested=False)
(X/'installed-review.json').write_text(json.dumps(r,indent=2)+'\n'); os.sync(); print(json.dumps(r,indent=2))
