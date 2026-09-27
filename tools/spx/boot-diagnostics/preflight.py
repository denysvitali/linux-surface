#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Inspect SPX boot artifacts without modifying boot selection."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reboot', action='store_true')
args = parser.parse_args()
if args.reboot:
    raise SystemExit(
        'BLOCKED: experimental reboots have no validated pre-kernel recovery. '
        'The userspace timer and an unloaded/unbound watchdog are insufficient.'
    )
base = Path('/var/lib/spx-boot-diagnostics')
attempt = json.loads((base / 'attempt.json').read_text())
run = base / 'attempts' / attempt['attempt']

def command(*argv):
    return subprocess.check_output(argv, text=True).strip()

def require(ok, message):
    if not ok:
        raise SystemExit(message)

def validated_mainline_check(boot, cmdline, age):
    """Accept only a retained boot whose archived baseline was explicitly pinned."""
    proof = attempt['validated_preboot']
    fields = {'boot_id', 'release', 'attempt', 'result_path', 'result_sha256'}
    require(isinstance(proof, dict) and set(proof) == fields,
            'Invalid validated_preboot schema')
    require(all(isinstance(proof[key], str) and proof[key] for key in fields),
            'Invalid validated_preboot field')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', proof['attempt']) is not None,
            'Invalid validated preboot attempt ID')
    require(proof['attempt'] != attempt['attempt'],
            'Validated preboot must belong to a distinct prior attempt')
    require(proof['boot_id'] == boot, 'Validated preboot ID does not match current boot')
    require(command('uname', '-r') == proof['release'],
            'Validated preboot release does not match running kernel')
    tokens = cmdline.split()
    require([t for t in tokens if t.startswith('spx_boot=')] == ['spx_boot=mainline-trial'],
            'Validated preboot requires exactly one mainline-trial marker')
    require([t for t in tokens if t.startswith('spx_attempt=')] ==
            ['spx_attempt=' + proof['attempt']], 'Validated preboot attempt marker mismatch')
    result_path = base / 'attempts' / proof['attempt'] / 'live-baseline-result' / 'result.json'
    require(proof['result_path'] == str(result_path),
            'Validated preboot result must be its archived live baseline')
    require(re.fullmatch(r'[0-9a-f]{64}', proof['result_sha256']) is not None,
            'Invalid validated preboot result hash')
    try:
        payload = result_path.read_bytes()
    except OSError as exc:
        raise SystemExit('Cannot read validated preboot result: ' + str(exc)) from exc
    require(hashlib.sha256(payload).hexdigest() == proof['result_sha256'],
            'Validated preboot result hash mismatch')
    try:
        result = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise SystemExit('Invalid validated preboot result JSON') from exc
    require(isinstance(result, dict), 'Validated preboot result must be an object')
    for key in ('boot_id', 'release', 'attempt'):
        require(result.get(key) == proof[key], 'Validated preboot result mismatch: ' + key)
    require(result.get('result') ==
            'passed extended graphical baseline; intentionally retained live mainline session',
            'Validated preboot result does not record a successful retained baseline')
    require(result.get('recovery_return_performed') is False,
            'Validated preboot result must record no recovery return')
    duration = result.get('uptime_seconds')
    require(type(duration) in (int, float) and 600 <= duration <= age and
            math.isfinite(duration),
            'Validated preboot baseline must cover at least 600 seconds of this boot')
    return dict(proof)

def boot_check():
    start = command('uptime', '-s')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    cmdline = Path('/proc/cmdline').read_text()
    age = float(Path('/proc/uptime').read_text().split()[0])
    require(boot == attempt['preboot_id'], 'Boot has changed; collect evidence, do not retry reboot')
    proof = None
    if 'validated_preboot' in attempt:
        proof = validated_mainline_check(boot, cmdline, age)
    else:
        require('spx_diag=' not in cmdline, 'Already in diagnostic boot; collect evidence instead')
        require('spx_boot=known-good' in cmdline.split(), 'Expected recovery boot is not running')
    require(age >= 120, 'Boot is less than two minutes old; wait and recheck')
    state = {'boot_id': boot, 'boot_start': start, 'uptime_seconds': age, 'cmdline': cmdline.strip()}
    if proof is not None:
        state['validated_preboot'] = proof
    return state

state = boot_check()
require(not (run / 'reboot-requested').exists(), 'Reboot was already requested; assume it executed')
for name, expected in attempt['sha256'].items():
    require(hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, 'Artifact mismatch: ' + name)
for name in ['/boot/grub/grub.cfg', '/boot/grub/custom.cfg']:
    subprocess.run(['grub-script-check', name], check=True)
grub = Path('/boot/grub/grub.cfg').read_text()
require('set default="spx-known-good"' in grub, 'Recovery is not the persistent default')
entry = re.search(r'menuentry "Surface Pro X known-good .*?\n}', grub, re.S)
require(entry is not None, 'Recovery entry is missing')
for field in ['ramoops.mem_address=0x9a480000', 'ramoops.mem_size=0x100000',
              'ramoops.record_size=0x40000', 'ramoops.console_size=0x20000',
              'ramoops.pmsg_size=0', 'ramoops.ftrace_size=0']:
    require(field in entry.group().split(), 'Recovery log layout mismatch: ' + field)
custom = Path('/boot/grub/custom.cfg').read_text()
expected_entry = (run / 'entry.cfg').read_text().strip()
require(expected_entry in custom, 'Test entry differs from archived attempt')
require('--id ' + attempt['entry'] + ' {' in expected_entry, 'Attempt entry ID mismatch')
for name in attempt['sha256']:
    require(name.removeprefix('/boot') in expected_entry, 'Test entry does not reference artifact: ' + name)
env = command('grub-editenv', '/boot/grub/grubenv', 'list')
require(not re.search(r'^next_entry=.+$', env, re.M), 'Another boot is queued')
require('BootNext:' not in command('efibootmgr'), 'EFI BootNext overrides recovery')
for unit in ['spx-boot-evidence.service', 'spx-diag-return.timer']:
    require(command('systemctl', 'is-enabled', unit) == 'enabled', 'Missing enabled unit: ' + unit)
require(command('systemctl', 'show', 'spx-boot-evidence.service', '-p', 'ExecMainStatus', '--value') == '0', 'Collector failed')
(run / 'preflight.json').write_text(json.dumps(state, indent=2) + '\n')
# Detect a concurrent boot change even for an inspection-only pass.
boot_check()
print('READ-ONLY PASS: artifact/configuration checks; no boot queued', flush=True)
