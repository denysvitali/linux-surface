#!/usr/bin/python3
"""Validate every input, then atomically publish the complete AP prequeue archive."""
import ast,json,os,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ap_boot_guard import X,load,preboot,files,sha,frozen_prequeue
os.umask(0o077)
a=load();assert a['state']=='prepared AP; no boot selection';preboot(a)
service=json.loads((X/'service-context-review.json').read_text())
assert service['boot_id']==a['preboot_id'] and service['attempt']==a['attempt']
assert service['full_preboot_passed'] and service['sudo_uid_absent'] and service['next_entry_empty'] and service['known_good_default']
assert service['guard_sha256']==sha('/usr/local/lib/spx-boot-diagnostics/ap_boot_guard.py')
assert service['source_diff_sha256']==sha(X/'build/source.diff')
assert subprocess.check_output(['systemctl','show','spx-ap-preboot-validation-record.service','-p','Result','--value'],text=True).strip()=='success'
src=Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
for name,h in json.loads((X/'deployment-sources-sha256.json').read_text()).items():assert sha(src/name)==h,name
native=json.loads((X/'native-continuation-review.json').read_text())
assert native['boot_id']==a['preboot_id'] and native['startedBy']=='daemon' and native['startedFromDaemon']
assert native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage']=='continue' and native['lifecycleState']=='running'
assert native['legacy_resume_marker_absent'] and not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
os.kill(native['hostPid'],0)
local_names=('attempt.json','archive-review.json','installed-review.json','native-continuation-review.json','working-recovery.json','deployment-sources-sha256.json','build-sha256.json','build-symlinks.json','dtb-sha256.json','boot-guards-test.log','archive-guards-test.log','units-verify.log','entry.cfg','service-context-review.json')
source_names=('PREPARED-20261002ap.md','RESULT-20261002ao.md','review-ap-handoff.py','freeze-ap-prequeue.py','PERSISTENCE-AFTER-AO-20261002.md','check-ap-service-context.py','generate-ap.py','review-ap-persistence.py','test-ap-persistence.py')
inputs={name:X/name for name in local_names}|{name:src/name for name in source_names}|{name:src.parents[2]/name for name in ('LOCAL-PROGRESS.md','PORT-CHECKLIST.md')}
# Fail before creating any output if a filename, helper or manifest is incomplete.
for name,p in inputs.items():
 assert p.is_file() and not p.is_symlink(),str(p)
 if name.endswith('.py'):ast.parse(p.read_text())
input_hashes={name:sha(p) for name,p in inputs.items()}
out=X/'prequeue-records';tmp=X/'prequeue-records.new'
assert not out.exists() and not tmp.exists();tmp.mkdir(mode=0o700)
for name,p in inputs.items():shutil.copy2(p,tmp/name)
assert files(tmp)==input_hashes
(tmp/'outgoing-snapshot-manifest-sha256').write_text(sha(X/'preboot-snapshot/sha256.json')+'\n')
preboot(a)
(tmp/'freeze-complete.json').write_text(json.dumps(dict(boot_id=a['preboot_id'],attempt=a['attempt'],inputs_validated_before_creation=True,preboot_checked_after_copy=True),indent=2)+'\n')
h=files(tmp);(tmp/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(tmp)==h|{'sha256.json':sha(tmp/'sha256.json')}
os.sync();os.rename(tmp,out);frozen_prequeue(a);os.sync()
print(json.dumps(dict(files_verified=len(h),manifest_sha256=sha(out/'sha256.json'),actual_ao_preboot_id=a['preboot_id'],boot_selected=False),indent=2))
