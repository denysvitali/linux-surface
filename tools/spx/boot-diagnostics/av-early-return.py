#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve terminal AV GPU failure and return once to its verified default."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from av_boot_guard import X, RUNTIME, load, trial_identity, recovery, artifacts, files, sha

os.umask(0o077)
a = load()
bid = trial_identity(a)
assert (X / 'early-return-requested').is_file()
assert not (X / 'early-return-check-passed.json').exists()
root = X / 'gpu-failure-result'
h = json.loads((root / 'sha256.json').read_text())
assert files(root) == h | {'sha256.json': sha(root / 'sha256.json')}
r = json.loads((root / 'result.json').read_text())
assert r['boot_id'] == bid and r['GPU_collection_passed'] is False
assert r['sustained_render_seconds'] == 0 and r['hardware_acceptance_closed'] is False
state = subprocess.check_output(['systemctl', 'show', 'spx-av-gpu.service',
                                '-p', 'ActiveState', '--value'], text=True).strip()
assert state == 'failed'
artifacts(a)
assert not recovery(a).get('next_entry', '')
subprocess.run([str(RUNTIME / 'collect.sh')], check=True, timeout=120)
assert trial_identity(a) == bid
env = recovery(a)
assert not env.get('next_entry', '')
report = {'boot_id': bid, 'release': a['release'],
          'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
          'GPU_collection_terminal_failed': True,
          'failure_manifest_sha256': sha(root / 'sha256.json'),
          'recovery_payloads_modules_entry_efi_verified': True,
          'persistent_default': 'spx-known-good', 'next_entry_empty': True,
          'helper_sha256': sha(Path(__file__)), 'hardware_acceptance_closed': False}
with (X / 'early-return-check-passed.json').open('x') as file:
    file.write(json.dumps(report, indent=2) + '\n')
    file.flush()
    os.fsync(file.fileno())
os.sync()
subprocess.run([str(RUNTIME / 'return.sh')], check=True, timeout=120)
