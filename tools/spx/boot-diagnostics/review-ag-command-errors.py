#!/usr/bin/python3
"""Compare frozen AF/AG command errors without performing controller IO."""
import hashlib,json,os,re
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
OUT=BASE/'20260930ag/command-error-review.json'
assert os.geteuid()==0 and not OUT.exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
summary={}
for attempt in ('20260930af','20260930ag'):
 root=BASE/attempt/'final-result';h=json.loads((root/'sha256.json').read_text())
 actual={str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}
 assert actual==h|{'sha256.json':sha(root/'sha256.json')}
 result=json.loads((root/'result.json').read_text());raw=(root/'dmesg-raw.log').read_text()
 def records(fragment):
  return [{'kernel_seconds':float(re.search(r'\[\s*(\d+\.\d+)\]',line)[1]),'line':line} for line in raw.splitlines() if fragment in line]
 enum=records('SPX enum diag slot=1 status_snapshot=')
 init=records('wsa881x-codec sdw:0:0:0217:2110:00:4: SPX: initializing amplifier at SoundWire device 1')
 errors=records('SWR CMD error, fifo status')
 assert len(enum)==1 and 'rc=0/0 words=21170214/00000010' in enum[0]['line']
 assert len(errors)==sum('SWR CMD error' in line for line in result['native_bus_error_lines'])
 for e in errors:
  v=int(re.search(r'fifo status 0x([0-9a-f]+)',e['line'])[1],16)
  e['fifo_status_hex']=hex(v)
  e['driver_wr_count_field']=(v>>8)&31
  e['driver_rd_count_field']=(v>>16)&31
  e['after_enumeration_seconds']=round(e['kernel_seconds']-enum[0]['kernel_seconds'],6)
  e['after_right_init_marker_seconds']=round(e['kernel_seconds']-init[-1]['kernel_seconds'],6) if init else None
 summary[attempt]={'boot_id':result['boot_id'],'result_manifest_sha256':sha(root/'sha256.json'),
                   'raw_enumeration':enum,'right_init_markers':init,'command_errors':errors,
                   'soundwire_slaves':result['soundwire_slaves'],
                   'native_path_passed':result['native_force_off_path_passed'],
                   'strict_scope_passed':result['passed_scoped_baseline']}
report={'attempt':'20260930ag','comparison':summary,
        'limits':['FIFO field values follow existing driver masks; bridge freshness and actual queue occupancy are unverified.',
                  'An init marker records function entry, not completion or hardware acknowledgment.',
                  'FIFO flush is existing IRQ recovery; no agent flush, extra register read or live change occurred.',
                  'These asynchronous errors cannot be assigned to a specific command from the available logs.',
                  'Matching success does not establish the cause of the command error or validate acoustics.']}
OUT.write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
