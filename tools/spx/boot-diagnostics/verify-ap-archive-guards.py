#!/usr/bin/python3
"""Test actual AP freeze/source guards against incomplete or stale archives offline."""
import copy,hashlib,importlib.util,json,tempfile,types
from pathlib import Path
src=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('guard_under_test',src/'ap_boot_guard.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
def rejected(fn):
 try:fn()
 except (AssertionError,FileNotFoundError):return
 raise AssertionError('invalid archive accepted')
def write(p,obj):p.write_text(json.dumps(obj,sort_keys=True)+'\n')
with tempfile.TemporaryDirectory(prefix='spx-ap-freeze-test-') as tmp:
 x=Path(tmp);g.X=x;root=x/'prequeue-records';root.mkdir()
 a={key: 'value-'+key for key in ('attempt','entry','release','preboot_id','preboot_cmdline','cmdline','sha256','recovery_sha256','runtime_sha256','parent_manifests_sha256')}
 a['state']='prepared AP; no boot selection'
 realsha=g.sha
 g.sha=lambda p: 'installed-guard' if str(p)=='/usr/local/lib/spx-boot-diagnostics/ap_boot_guard.py' else realsha(p)
 def setup():
  for p in root.iterdir():p.unlink()
  write(root/'attempt.json',a)
  for name in ('installed-review.json','native-continuation-review.json','working-recovery.json','deployment-sources-sha256.json','entry.cfg'):
   (x/name).write_text('reviewed\n');(root/name).write_text('reviewed\n')
  service=dict(full_preboot_passed=True,sudo_uid_absent=True,guard_sha256='installed-guard',boot_id=a['preboot_id'],attempt=a['attempt'])
  write(root/'service-context-review.json',service);write(x/'service-context-review.json',service)
  for name in ('freeze-ap-prequeue.py','PREPARED-20261002ap.md','PORT-CHECKLIST.md'):(root/name).write_text('frozen\n')
  write(root/'freeze-complete.json',dict(boot_id=a['preboot_id'],attempt=a['attempt'],inputs_validated_before_creation=True,preboot_checked_after_copy=True))
  manifest()
 def manifest():
  (root/'sha256.json').unlink(missing_ok=True);write(root/'sha256.json',g.files(root))
 setup();g.frozen_prequeue(a);g.frozen_prequeue(a|{'state':'AP selected once; immediate guard pending'})
 cases=0
 for name in ('sha256.json','freeze-complete.json','PORT-CHECKLIST.md'):
  setup();(root/name).unlink();rejected(lambda:g.frozen_prequeue(a));cases+=1
 setup();(root/'freeze-complete.json').unlink();manifest();rejected(lambda:g.frozen_prequeue(a));cases+=1
 setup();(root/'extra').write_text('unmanifested');rejected(lambda:g.frozen_prequeue(a));cases+=1
 setup();rejected(lambda:g.frozen_prequeue(a|{'preboot_id':'changed'}));cases+=1
 setup();(x/'entry.cfg').write_text('different entry');rejected(lambda:g.frozen_prequeue(a));cases+=1
 setup();s=json.loads((root/'service-context-review.json').read_text());s['guard_sha256']='stale';write(root/'service-context-review.json',s);write(x/'service-context-review.json',s);manifest();rejected(lambda:g.frozen_prequeue(a));cases+=1
 setup();r=json.loads((root/'freeze-complete.json').read_text());r['preboot_checked_after_copy']=False;write(root/'freeze-complete.json',r);manifest();rejected(lambda:g.frozen_prequeue(a));cases+=1
 g.sha=realsha
with tempfile.TemporaryDirectory(prefix='spx-ap-source-test-') as tmp:
 x=Path(tmp);root=x/'provenance';root.mkdir();repo=x/'repo';repo.mkdir();built=x/'build';(built/'artifacts').mkdir(parents=True)
 before=b'diff --git a/driver.c b/driver.c\nold driver patch\n'
 after=before+b''.join(f'diff --git a/{n} b/{n}\nreviewed documentation\n'.encode() for n in ('AGENTS.md','tools/spx/boot-diagnostics/README.md','tools/spx/boot-diagnostics/COMPONENTS.md'))
 (root/'before-source.diff').write_bytes(before);(root/'after-source.diff').write_bytes(after);(built/'source.diff').write_bytes(before)
 (repo/'.config').write_text('CONFIG_TEST=y\n');(built/'artifacts/.config').write_text('CONFIG_TEST=y\n')
 write(root/'sha256.json',g.files(root));g.DOC_MANIFEST=g.sha(root/'sha256.json')
 current=after
 def output(args,**kw):
  assert args[:3]==['git','-c','safe.directory='+str(repo)] and args[3:]==['diff','--binary','HEAD']
  return current
 g.subprocess=types.SimpleNamespace(check_output=output)
 def check():g.source_provenance(root,built/'source.diff',repo)
 check();source_bad=0
 for changed in (after.replace(b'old driver patch',b'changed driver patch'),after+b'new data\n',before):
  current=changed;rejected(check);source_bad+=1
 current=after;(repo/'.config').write_text('CONFIG_TEST=n\n');rejected(check);source_bad+=1
 (repo/'.config').write_text('CONFIG_TEST=y\n');(built/'source.diff').write_bytes(b'wrong built source');rejected(check);source_bad+=1
print(json.dumps(dict(freeze_positive_cases=2,freeze_negative_cases=cases,source_positive_cases=1,source_negative_cases=source_bad,live_mutations=False),indent=2))
