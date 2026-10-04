#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze reviewed AQ failure before its separately guarded automatic return."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from aq_boot_guard import X, REPO, command, files, load, recovery, sha

os.umask(0o077)
a = load()
bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert bid == 'b289f7d6-7c6a-419c-957d-a60770b9fc3b'
assert os.uname().release == a['release']
assert Path('/proc/cmdline').read_text().split() == ['BOOT_IMAGE=/spx-trial-20261003aq/vmlinuz'] + a['cmdline'].split()
assert not recovery(a).get('next_entry', '')
assert command('systemctl', 'is-active', 'spx-aq-fallback.timer') == 'active'
for name in ('final-result', 'camera-provider-result', 'handoff-review', 'startup-discovery'):
    root = X / name
    h = json.loads((root / 'sha256.json').read_text())
    assert files(root) == h | {'sha256.json': sha(root / 'sha256.json')}
review = json.loads((X / 'independent-result-review.json').read_text())
assert review['boot_id'] == bid and not review['scoped_passed'] and not review['fallback_stopped']
provider = json.loads((X / 'camera-provider-review.json').read_text())
assert provider['boot_id'] == bid and provider['provider_registration_verified']
touch = json.loads((X / 'touch-startup-review.json').read_text())
assert touch['boot_id'] == bid and not touch['clean_touch_startup']
out = X / 'post-result-records'
assert not out.exists()
out.mkdir(mode=0o700)
for name in ('attempt.json', 'independent-result-review.json', 'camera-provider-review.json',
             'touch-startup-review.json', 'finalizer-action.json'):
    shutil.copy2(X / name, out / name)
for name in ('final-result', 'camera-provider-result', 'handoff-review', 'startup-discovery'):
    shutil.copy2(X / name / 'sha256.json', out / (name + '-sha256.json'))
for name in ('PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md'):
    shutil.copy2(REPO / name, out / name)
helpers = REPO / 'tools/spx/boot-diagnostics'
for name in ('RESULT-20261003aq.md', 'PREPARED-20261003aq.md', 'snapshot-aq-startup.py',
             'review-aq-touch.py', 'archive-aq-return.py', Path(__file__).name):
    shutil.copy2(helpers / name, out / name)
report = {'attempt': a['attempt'], 'boot_id': bid, 'uptime': Path('/proc/uptime').read_text().strip(),
          'baseline_passed': False, 'provider_registration_verified': True,
          'fallback_armed': True, 'actual_recovery_return_observed': False,
          'known_good_default_verified': True, 'next_entry_empty': True,
          'hardware_acceptance_checks_remaining': 47}
(out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
h = files(out)
(out / 'sha256.json').write_text(json.dumps(h, indent=2) + '\n')
assert files(out) == h | {'sha256.json': sha(out / 'sha256.json')}
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
assert not recovery(a).get('next_entry', '')
os.sync()
print(json.dumps(report | {'files_verified': len(h), 'manifest_sha256': sha(out / 'sha256.json')}, indent=2))
