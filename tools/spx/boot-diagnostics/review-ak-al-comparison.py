#!/usr/bin/python3
"""Compare frozen exact-artifact pin controls; perform no hardware operations."""
import ast, hashlib, json, os
from pathlib import Path
os.umask(0o077)
base=Path('/var/lib/spx-boot-diagnostics/attempts')
out=base/'20260930al/ak-al-comparison.json'
assert os.geteuid()==0 and not out.exists()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def assignment(t,name):
 return next(n.value for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(q,ast.Name) and q.id==name for q in n.targets))
records=[]; states=[]
for suffix in ('ak','al'):
 run=base/('20260930'+suffix);root=run/'final-result'
 h=json.loads((root/'sha256.json').read_text())
 assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}==h|{'sha256.json':sha(root/'sha256.json')}
 a=json.loads((run/'attempt.json').read_text());r=json.loads((root/'result.json').read_text());v=json.loads((run/'independent-result-review.json').read_text())
 assert v['boot_id']==r['boot_id'] and v['result_manifest_sha256']==sha(root/'sha256.json')
 assert r['attempt']==a['attempt']=='20260930'+suffix
 scope=(run/'deployment-sources'/f'{suffix}-finalize.py').read_text()
 if suffix=='al':scope=scope.replace('left_init','right_init')
 states.append({'a':a,'source':sha(run/'build/source.diff'),'config':sha(run/'build/artifacts/.config'),'build':sha(run/'build-sha256.json'),'modules':sha(run/'build/module-sha256.json'),'scope':ast.dump(assignment(ast.parse(scope),'passed'))})
 records.append({'attempt':r['attempt'],'boot_id':r['boot_id'],'release':r['release'],'uptime_seconds':r['uptime_seconds'],'scoped_passed':v['scoped_passed'],'failure_reasons':v['scoped_failure_reasons'],'native_path_passed':v['native_force_off_path_passed'],'firmware_match_passed':v['firmware_identity_match_passed'],'codec_mechanism_passed':v['codec_mechanism_passed'],'gpio_view':v['gpio_register_view'],'native_error_lines':r['native_bus_error_lines'],'touch_ready':r['spi_hid_ready'],'touch_startup_clean':r['touch_startup_clean'],'touch_windows':len(r['touch_startup_windows']),'touch_records':r['touch_startup_diagnostic_lines'],'history_dumps':len(r['command_history']['dumps']),'manifest_sha256':sha(root/'sha256.json')})
p,q=states
for key in ('source','config','build','modules','scope'):assert p[key]==q[key],key
for key in ('release','sha256','recovery_sha256'):assert p['a'][key]==q['a'][key],key
old=p['a']['cmdline'].split();new=q['a']['cmdline'].split()
assert len(old)==len(new)
deltas=[(a,b) for a,b in zip(old,new) if a!=b]
assert deltas==[('spx_attempt=20260930ak','spx_attempt=20260930al'),('wcd934x.spx_wsa_en_pin=2','wcd934x.spx_wsa_en_pin=1')],deltas
assert records[0]['boot_id']!=records[1]['boot_id']
report={'trials':records,'cmdline_deltas':deltas,'kernel_modules_DTB_initramfs_source_config_identical':True,'strict_scope_equivalent_after_init_role_substitution':True,'limits':['Different boots have different firmware state, timing and system service activity; no causal pin-to-touch claim follows.','No error-triggered history does not prove absence of all device-zero requests or hardware acknowledgment.','Neither acoustic output, both-speaker operation nor startup reliability is established.']}
out.write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report|{'comparison_sha256':sha(out)},indent=2))
