#!/usr/bin/python3
"""Archive the verified AO payload unchanged for AP's single ramoops selector."""
import json,os,shutil,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from ao_boot_guard import BASE,X as P,load,recovery,artifacts,files,links,sha,command
from ap_boot_guard import source_provenance
os.umask(0o077)
REPO=Path('/home/dvitali/Documents/git/linux-surface-next');X=BASE/'attempts/20261002ap'
a=load();bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
review=json.loads((P/'independent-result-review.json').read_text())
assert bid==review['boot_id']=='24d683f1-1493-44e1-a5b4-b7d7ed6e46ce'
assert review['scoped_passed'] and review['fallback_stopped'] and not review['scoped_failure_reasons']
assert os.uname().release==a['release']
assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20261001am/vmlinuz']+a['cmdline'].split()
assert not recovery(a).get('next_entry','');artifacts(a)
assert command('systemctl','show','spx-ao-fallback.timer','-p','ActiveState','--value')!='active'
assert not X.exists()
manifest_names=('final-result','post-result-records','startup-discovery','handoff-review','persistence-review','checklist-documentation-20261002')
manifests={}
for name in manifest_names:
 root=P/name;h=json.loads((root/'sha256.json').read_text())
 assert files(root)==h|{'sha256.json':sha(root/'sha256.json')};manifests[name]=sha(root/'sha256.json')
source_provenance(P/'checklist-documentation-20261002',P/'build/source.diff',REPO)
for name,manifest in (('build','build-sha256.json'),('dtb-build','dtb-sha256.json')):
 assert files(P/name)==json.loads((P/manifest).read_text())
assert links(P/'build')==json.loads((P/'build-symlinks.json').read_text())
X.mkdir(mode=0o700)
for name in ('build','dtb-build'):shutil.copytree(P/name,X/name,symlinks=True)
shutil.copytree(P/'checklist-documentation-20261002',X/'source-provenance',symlinks=True)
for name in ('build-sha256.json','build-symlinks.json','dtb-sha256.json','working-recovery.json'):shutil.copy2(P/name,X/name)
assert files(X/'build')==json.loads((X/'build-sha256.json').read_text())
assert links(X/'build')==json.loads((X/'build-symlinks.json').read_text())
assert files(X/'dtb-build')==json.loads((X/'dtb-sha256.json').read_text())
source_provenance(X/'source-provenance',X/'build/source.diff',REPO)
r=json.loads((P/'archive-review.json').read_text())
r.update(attempt='20261002ap',preboot_id=bid,preboot_cmdline=Path('/proc/cmdline').read_text().strip(),parent_attempt='20261002ao',parent_attempt_definition_sha256=sha(P/'attempt.json'),parent_result_review_sha256=sha(P/'independent-result-review.json'),parent_manifests_sha256=manifests,parent_archive_review_sha256=sha(P/'archive-review.json'),parent_touch_review_sha256=sha(P/'touch-startup-review.json'),parent_result_manifest_sha256=manifests['final-result'],parent_post_result_manifest_sha256=manifests['post-result-records'],functional_delta='ramoops.dyndbg=+p; same AM/AO kernel, config and artifacts; new attempt marker',comparison='AO -> AP persistence diagnostic; unchanged I01 baseline',checklist_ids=['R01','I01'],source_provenance_manifest_sha256=manifests['checklist-documentation-20261002'],boot_selected=False,deployed=False,playback_requested=False,callback_executed_on_hardware=False)
(X/'archive-review.json').write_text(json.dumps(r,indent=2)+'\n');shutil.copy2(__file__,X/'prepare-ap.py')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid;os.sync()
print(json.dumps({k:r[k] for k in ('attempt','preboot_id','build_files_verified','build_symlinks_verified','module_files_verified','functional_delta','source_provenance_manifest_sha256')},indent=2))
