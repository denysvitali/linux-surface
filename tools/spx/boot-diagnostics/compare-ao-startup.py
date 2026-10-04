#!/usr/bin/python3
"""Compare archived AM/AO startup without treating sequences as separate trials."""
import hashlib,json,os
from pathlib import Path
os.umask(0o077)
BASE=Path('/var/lib/spx-boot-diagnostics/attempts')
OUT=BASE/'20261002ao/am-ao-comparison.json'
assert os.geteuid()==0 and not OUT.exists()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
report={}
for attempt in ('20261001am','20261002ao'):
 x=BASE/attempt;root=x/'final-result';h=json.loads((root/'sha256.json').read_text())
 assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}==h|{'sha256.json':sha(root/'sha256.json')}
 r=json.loads((root/'result.json').read_text());rev=json.loads((x/'independent-result-review.json').read_text());touch=json.loads((x/'touch-startup-review.json').read_text())
 assert r['boot_id']==rev['boot_id']==touch['boot_id']
 assert r['passed_scoped_baseline']==rev['scoped_passed']
 assert rev['result_manifest_sha256']==sha(root/'sha256.json')==touch['final_result_manifest_sha256']
 a=json.loads((x/'attempt.json').read_text())
 report[attempt]=dict(boot_id=r['boot_id'],result_manifest_sha256=sha(root/'sha256.json'),
    release=a['release'],payload_sha256=a['sha256'],source_diff_sha256=sha(x/'build/source.diff'),
    scoped_passed=rev['scoped_passed'],failures=rev['scoped_failure_reasons'],
    touch_ready=r['spi_hid_ready'],clean_startup=r['touch_startup_clean'],
    startup_records=r['touch_startup_diagnostic_lines'],startup_windows=len(r['touch_startup_windows']),
    open_timeouts=r['touch_startup_open_timeouts'],invalid_headers=r['touch_startup_invalid_headers'],
    touch_state=touch['final_touch_state'],windows=touch['windows'])
for key in ('release','payload_sha256','source_diff_sha256'):
 assert report['20261001am'][key]==report['20261002ao'][key]
report['limits']=['Same payloads and selectors, but separate boot timing and predecessor states.',
    'AM came from known-good; AO came from AM. No retained late console proves outgoing callback execution.',
    'Final baseline can pass after automatic iptsd recovery; clean startup is reported separately and not waived.',
    'Two boots do not establish reliability or attribute the transient timeout to shutdown behavior.']
OUT.write_text(json.dumps(report,indent=2)+'\n');os.sync()
print(json.dumps({a:{k:v for k,v in s.items() if k not in ('windows','touch_state','payload_sha256')} for a,s in report.items() if isinstance(s,dict)},indent=2))
