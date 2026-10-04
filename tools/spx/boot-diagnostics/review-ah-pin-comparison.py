#!/usr/bin/python3
"""Compare frozen corrected-topology AG/AH results; no hardware operations."""
import hashlib,json,os,re
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
OUT=BASE/'20260930ah/pin-comparison-review.json'
assert os.geteuid()==0 and not OUT.exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
comparison={}
for attempt,unique,pin in [('20260930ag',4,2),('20260930ah',3,1)]:
 x=BASE/attempt;root=x/'final-result';h=json.loads((root/'sha256.json').read_text())
 actual={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
 assert actual==h|{'sha256.json':sha(root/'sha256.json')}
 a=json.loads((x/'attempt.json').read_text());r=json.loads((root/'result.json').read_text());raw=(root/'dmesg-raw.log').read_text()
 def records(fragment):
  return [{'kernel_seconds':float(re.search(r'\[\s*(\d+\.\d+)\]',line)[1]),'line':line} for line in raw.splitlines() if fragment in line]
 enum=records('SPX enum diag slot=1 status_snapshot=')
 assert len(enum)==1 and f'rc=0/0 words=2117021{unique}/00000010' in enum[0]['line']
 init=records(f'wsa881x-codec sdw:0:0:0217:2110:00:{unique}: SPX: initializing amplifier at SoundWire device 1')
 assert len(init)==1
 assert len(r['soundwire_slaves'])==2 and all(s['driver']=='wsa881x-codec' and s['of_node'] for s in r['soundwire_slaves'].values())
 selected=r['soundwire_slaves'][f'sdw:0:0:0217:2110:00:{unique}']
 assert selected['status'].casefold()=='attached' and selected['device_number']=='1'
 comparison[attempt]={'boot_id':r['boot_id'],'kernel_pin_selector':pin,'collected_uptime_seconds':r['uptime_seconds'],'result_manifest_sha256':sha(root/'sha256.json'),'payload_sha256':a['sha256'],'source_diff_sha256':sha(x/'dtb-build/source.diff'),'config_sha256':sha(x/'build/artifacts/.config'),'module_manifest_sha256':sha(x/'build/module-sha256.json'),'raw_enum':enum,'init_entry_markers':init,'raw_command_errors':records('SWR CMD error'),'selected_native_error_lines':r['native_bus_error_lines'],'soundwire_slaves':r['soundwire_slaves'],'strict_passed':r['passed_scoped_baseline'],'native_path_passed':r['native_force_off_path_passed'],'touch_ready':r['spi_hid_ready'],'touch_startup_clean':r['touch_startup_clean'],'touch_diagnostic_records':r['touch_startup_diagnostic_lines']}
ag,ah=comparison.values()
for field in ('payload_sha256','source_diff_sha256','config_sha256','module_manifest_sha256'):assert ag[field]==ah[field],field
a=json.loads((BASE/'20260930ag/attempt.json').read_text());b=json.loads((BASE/'20260930ah/attempt.json').read_text())
assert b['cmdline']==a['cmdline'].replace('spx_attempt=20260930ag','spx_attempt=20260930ah').replace('wcd934x.spx_wsa_en_pin=2','wcd934x.spx_wsa_en_pin=1')
report={'attempt':'20260930ah','comparison':comparison,'exact_artifact_source_config_module_comparison_verified':True,'limits':['These are different boots; selector, timing, firmware state and the physical responding slave are not independent causal variables.','Init markers record function entry, not completion or acknowledged hardware commands.','AH success cannot identify which asynchronous command failed in AG or validate acoustics.','No new reads, writes, GPIO operation, audio, PCM or live restart/rebind were performed.']}
OUT.write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
