#!/usr/bin/python3
"""Run the complete read-only AO preboot guard under the system manager."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ao_boot_guard import X, load, preboot, sha
assert not os.environ.get('SUDO_UID')
a=load()
assert a['state']=='prepared AO; no boot selection'
assert not (X/'reboot-requested').exists()
env=preboot(a)
report=dict(boot_id=a['preboot_id'],attempt=a['attempt'],full_preboot_passed=True,
    sudo_uid_absent=True,next_entry_empty=not env.get('next_entry',''),
    known_good_default=env.get('saved_entry')=='spx-known-good',
    guard_sha256=sha('/usr/local/lib/spx-boot-diagnostics/ao_boot_guard.py'),
    source_diff_sha256=sha(X/'build/source.diff'),boot_selected=False)
os.umask(0o077)
with (X/'service-context-review.json').open('x') as f: f.write(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
