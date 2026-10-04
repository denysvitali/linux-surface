#!/usr/bin/python3
"""Compare verified frozen results; never consult retired installed trial paths."""
import json, os
from pathlib import Path
from hashlib import sha256
os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
OUT = BASE/'20261001am/ak-al-am-comparison.json'
assert os.geteuid() == 0 and not OUT.exists()
def sha(p): return sha256(p.read_bytes()).hexdigest()
report = {}
for attempt in ('20260930ak', '20260930al', '20261001am'):
    x = BASE/attempt
    root = x/'final-result'
    h = json.loads((root/'sha256.json').read_text())
    actual = {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
    assert actual == h | {'sha256.json':sha(root/'sha256.json')}
    r = json.loads((root/'result.json').read_text())
    rev = json.loads((x/'independent-result-review.json').read_text())
    assert r['boot_id'] == rev['boot_id'] and r['passed_scoped_baseline'] == rev['scoped_passed']
    assert rev['result_manifest_sha256'] == sha(root/'sha256.json')
    touch = json.loads((x/'touch-startup-review.json').read_text())
    assert touch['boot_id'] == r['boot_id']
    report[attempt] = dict(boot_id=r['boot_id'], result_manifest_sha256=sha(root/'sha256.json'), scoped_passed=rev['scoped_passed'], failures=rev['scoped_failure_reasons'], touch_ready=r['spi_hid_ready'], clean_startup=r['touch_startup_clean'], startup_records=r['touch_startup_diagnostic_lines'], startup_windows=len(r['touch_startup_windows']), open_timeouts=r['touch_startup_open_timeouts'], invalid_headers=r['touch_startup_invalid_headers'], touch_state=touch['final_touch_state'], windows=touch['windows'], firmware_identity_match=rev['firmware_identity_match_passed'])
report['limits'] = ['AM arrived from known-good without the candidate shutdown callback; clean startup cannot establish outgoing candidate execution.', 'Different lifecycle code and boot timing confound attribution; one boot does not establish a startup fix or reliability.', 'AK/AL frozen archives are verified directly; their retired installed payload/module paths are not required.', 'No manual input events, audio, reset, restart or rebind performed.']
OUT.write_text(json.dumps(report, indent=2)+'\n')
os.sync()
print(json.dumps({a:{k:v for k,v in s.items() if k not in ('windows', 'touch_state')} for a,s in report.items() if isinstance(s,dict)}, indent=2))
