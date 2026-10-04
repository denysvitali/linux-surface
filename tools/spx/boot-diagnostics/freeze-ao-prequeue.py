#!/usr/bin/python3
"""Freeze reviewable outgoing AO preparation before its exclusive selection."""
import ast, json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ao_boot_guard import X, load, preboot, files, sha
os.umask(0o077)
a=load(); assert a['state']=='prepared AO; no boot selection'
preboot(a)
service=json.loads((X/'service-context-review.json').read_text())
assert service['boot_id']==a['preboot_id'] and service['attempt']==a['attempt']
assert service['full_preboot_passed'] and service['sudo_uid_absent'] and service['next_entry_empty'] and service['known_good_default']
assert service['guard_sha256']==sha('/usr/local/lib/spx-boot-diagnostics/ao_boot_guard.py')
assert service['source_diff_sha256']==sha(X/'build/source.diff')
assert subprocess.check_output(['systemctl','show','spx-ao-preboot-validation-record.service','-p','Result','--value'],text=True).strip()=='success'
src=Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
for n,h in json.loads((X/'deployment-sources-sha256.json').read_text()).items(): assert sha(src/n)==h,n
native=json.loads((X/'native-continuation-review.json').read_text())
assert native['boot_id']==a['preboot_id'] and native['startedBy']=='daemon' and native['startedFromDaemon']
assert native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage']=='continue' and native['lifecycleState']=='running'
assert native['legacy_resume_marker_absent'] and not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
os.kill(native['hostPid'],0)
out=X/'prequeue-records'; assert not out.exists(); out.mkdir(mode=0o700)
for n in ('attempt.json','archive-review.json','installed-review.json','native-continuation-review.json','working-recovery.json','deployment-sources-sha256.json','build-sha256.json','build-symlinks.json','dtb-sha256.json','boot-guards-test.log','units-verify.log','entry.cfg','service-context-review.json'):
    shutil.copy2(X/n,out/n)
for n in ('PREPARED-20261002ao.md','RESULT-20261001am.md','review-ao-handoff.py','freeze-ao-prequeue.py','AM-PLAN-20261001.md','RESULT-20261002an.md','check-ao-service-context.py','generate-ao.py','archive-an-abort.py'):
    if n.endswith('.py'): ast.parse((src/n).read_text())
    shutil.copy2(src/n,out/n)
shutil.copy2(src.parents[2]/'LOCAL-PROGRESS.md',out/'LOCAL-PROGRESS.md')
(out/'outgoing-snapshot-manifest-sha256').write_text(sha(X/'preboot-snapshot/sha256.json')+'\n')
h=files(out); (out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
assert files(out)==h|{'sha256.json':sha(out/'sha256.json')}
preboot(a); os.sync(); print(json.dumps(dict(files_verified=len(h),manifest_sha256=sha(out/'sha256.json'),actual_am_preboot_id=a['preboot_id'],boot_selected=False),indent=2))
