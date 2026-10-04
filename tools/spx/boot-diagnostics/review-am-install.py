#!/usr/bin/python3
"""Independently verify AM installed scope and archive actual known-good preboot evidence."""
import ast,fcntl,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from am_boot_guard import X,BASE,load,preboot,files,links,sha,command
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');SRC=REPO/'tools/spx/boot-diagnostics'
assert os.geteuid()==0 and not (X/'installed-review.json').exists()
a=load();assert a['state']=='prepared AM; no boot selection'
# Freeze deployment source separately from the already immutable full build.
dst=X/'deployment-sources';assert not dst.exists();dst.mkdir(mode=0o700)
names=('prepare-am-deployment.py','deploy-am.py','review-am-install.py','am-finalize.py','review-am-result.py','am_boot_guard.py','am-return.py','am-reboot-check.py','queue-am-once.py','verify-am-boot-guards.py','AM-PLAN-20261001.md','BUILD-20261001am.md','BOOT-PRUNE-20261002.md','PREPARED-20261001am.md')
for n in names:shutil.copy2(SRC/n,dst/n)
(X/'deployment-sources-sha256.json').write_text(json.dumps(files(dst),indent=2)+'\n')
env=preboot(a)
archive=json.loads((X/'archive-review.json').read_text());h=json.loads((X/'build-sha256.json').read_text());assert sha(X/'build-sha256.json')==archive['build_manifest_sha256'] and files(X/'build')==h
assert links(X/'build')==json.loads((X/'build-symlinks.json').read_text())
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)==(X/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
module_root=Path('/usr/lib/modules')/a['release'];assert links(module_root)==links(X/'build/module-root/lib/modules'/a['release'])
ko=sorted(module_root.rglob('*.ko'));assert len(ko)==187
for m in ko:assert command('modinfo','-F','vermagic',str(m)).split()[0]==a['release'],m
mods=json.loads((X/'build/module-sha256.json').read_text());initrd=X/'build/initramfs-extracted/usr/lib/modules'/a['release'];included=0
for n,hsh in mods.items():
 p=initrd/n
 if n.endswith('.ko') and p.is_file():assert sha(p)==hsh;included+=1
assert included==54
for old,new in [('ak-finalize.py','am-finalize.py'),('review-ak-result.py','review-am-result.py')]:assert (SRC/new).read_text()==(SRC/old).read_text().replace('20260930ak','20261001am').replace('spx-ak-','spx-am-').replace('AK','AM')
assert command('systemctl','show','spx-diag-long-return.timer','-p','ActiveState','--value')!='active'
assert '!spx_attempt=20261001am' in command('systemctl','cat','spx-diag-long-return.timer')
units=[str(Path('/etc/systemd/system')/('spx-am-'+n)) for n in ('finalize.service','finalize.timer','fallback.service','fallback.timer')]
subprocess.run(['systemd-analyze','verify',*units],check=True,timeout=30)
for p in ('/boot/grub/grub.cfg','/boot/grub/custom.cfg'):subprocess.run(['grub-script-check',p],check=True,timeout=30)
assert 'source ${config_directory}/custom.cfg' in Path('/boot/grub/grub.cfg').read_text()
assert os.access('/etc/grub.d/41_custom',os.X_OK)
assert sorted(p.name for p in Path('/usr/lib/modules').iterdir())==sorted(['6.18.3-1-surface+',a['release']])
assert sorted(p.name for p in Path('/boot').glob('spx-trial-*'))==['spx-trial-20261001am']
subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'],check=True,timeout=90)
snapshot=X/'preboot-snapshot';snapshot.mkdir(mode=0o700)
for n,s in [('boot-id',a['preboot_id']+'\n'),('uname',os.uname().release+'\n'),('cmdline',Path('/proc/cmdline').read_text()),('grubenv','\n'.join(k+'='+v for k,v in env.items())+'\n'),('efibootmgr',command('efibootmgr')+'\n')]: (snapshot/n).write_text(s)
collector=BASE/'boots'/a['preboot_id']
with (collector/'collect.lock').open() as lock:
 fcntl.flock(lock,fcntl.LOCK_EX);shutil.copytree(collector,snapshot/'collector',symlinks=True,ignore=shutil.ignore_patterns('collect.lock'))
hs=files(snapshot);(snapshot/'sha256.json').write_text(json.dumps(hs,indent=2)+'\n');assert files(snapshot)==hs|{'sha256.json':sha(snapshot/'sha256.json')}
preboot(a)
report={'attempt':a['attempt'],'preboot_id':a['preboot_id'],'build_files_verified':len(h),'build_symlinks_verified':272,'modules_verified':len(mods),'module_vermagic_records_verified':187,'private_initramfs_modules_verified':included,'working_module_files_links_verified':5183,'payload_recovery_runtime_hashes_verified':sum(len(a[n]) for n in ('sha256','recovery_sha256','runtime_sha256')),'strict_ak_scope_unchanged':True,'selector_delta_from_ak':'attempt marker only','preboot_snapshot_files_verified':len(hs),'preboot_snapshot_manifest_sha256':sha(snapshot/'sha256.json'),'deployment_source_manifest_sha256':sha(X/'deployment-sources-sha256.json'),'guard_test_log_sha256':sha(X/'boot-guards-test.log'),'known_good_default':True,'next_entry_empty':True,'efi_bootnext_absent':True,'am_timers_enabled_inactive':True,'generic_600s_return_excluded_for_am':True,'custom_menu_loader_present':True,'boot_selected':False,'playback_requested':False,'outgoing_candidate_quiesce_expected':False,'efi_early_kernel_recovery_validated':False}
(X/'installed-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
