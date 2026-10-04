#!/usr/bin/python3
"""Freeze verified AO outcome, persistence audit and source for the next decision."""
import json,os,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ao_boot_guard import X,load,recovery,artifacts,files,sha
os.umask(0o077)
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');a=load()
r=json.loads((X/'independent-result-review.json').read_text())
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==r['boot_id']
assert os.uname().release==a['release'] and r['scoped_passed'] and r['fallback_stopped']
assert not recovery(a).get('next_entry','');artifacts(a)
assert subprocess.check_output(['git','-c','safe.directory='+str(REPO),'diff','--binary','HEAD'],cwd=REPO,env=os.environ|{'GIT_OPTIONAL_LOCKS':'0'})==(X/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(X/'build/artifacts/.config')
refs={}
for n in ('final-result','handoff-review','startup-discovery','persistence-review','prequeue-records'):
 root=X/n;h=json.loads((root/'sha256.json').read_text());digest=sha(root/'sha256.json')
 assert files(root)==h|{'sha256.json':digest};refs[n]=digest
out=X/'post-result-records';assert not out.exists();out.mkdir(mode=0o700)
for n in ('independent-result-review.json','touch-startup-review.json','am-ao-comparison.json','finalizer-action.json','actual-native-continuation-review.json','attempt.json','working-recovery.json'):
 shutil.copy2(X/n,out/n)
for n in ('RESULT-20261002ao.md','PERSISTENCE-AFTER-AO-20261002.md','review-ao-touch.py','compare-ao-startup.py','snapshot-ao-post-result.py','review-ao-handoff.py','snapshot-ao-startup.py','review-ao-persistence.py'):
 shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n,out/n)
for n in ('LOCAL-PROGRESS.md','.config','drivers/hid/spi-hid/spi-hid-core.c','drivers/hid/spi-hid/spi-hid-core.h','fs/pstore/ram.c','fs/pstore/ram_core.c','lib/dynamic_debug.c'):
 dst=out/'source'/n;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(REPO/n,dst)
shutil.copy2(X/'build/source.diff',out/'source.diff')
(out/'referenced-manifests.json').write_text(json.dumps(refs,indent=2)+'\n')
h=files(out);(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(out)==h|{'sha256.json':sha(out/'sha256.json')}
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==r['boot_id'];os.sync()
print(json.dumps(dict(files_verified=len(h),manifest_sha256=sha(out/'sha256.json'),scoped_passed=True,known_good_default=True,next_entry_empty=True),indent=2))
