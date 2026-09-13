#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Validate this SPX attempt; reboot only with explicit --reboot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reboot', action='store_true')
args = parser.parse_args()
base = Path('/var/lib/spx-boot-diagnostics')
attempt = json.loads((base / 'attempt.json').read_text())
run = base / 'attempts' / attempt['attempt']

def command(*argv):
    return subprocess.check_output(argv, text=True).strip()

def require(ok, message):
    if not ok:
        raise SystemExit(message)

def boot_check():
    start = command('uptime', '-s')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    cmdline = Path('/proc/cmdline').read_text()
    age = float(Path('/proc/uptime').read_text().split()[0])
    require(boot == attempt['preboot_id'], 'Boot has changed; collect evidence, do not retry reboot')
    require('spx_diag=' not in cmdline, 'Already in diagnostic boot; collect evidence instead')
    require('spx_boot=known-good' in cmdline.split(), 'Expected recovery boot is not running')
    require(age >= 120, 'Boot is less than two minutes old; wait and recheck')
    return {'boot_id': boot, 'boot_start': start, 'uptime_seconds': age, 'cmdline': cmdline.strip()}

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
for field in ['ramoops.console_size=0x20000', 'ramoops.pmsg_size=0', 'ramoops.ftrace_size=0']:
    require(field in entry.group(), 'Recovery log layout mismatch: ' + field)
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
print('PASS: artifact hashes, GRUB syntax/default, log layout, evidence service and reboot guards', flush=True)
if args.reboot:
    # Recheck immediately before altering boot selection. Persist the request
    # before issuing it: interruptions never justify a duplicate reboot.
    state = boot_check()
    with (run / 'reboot-requested').open('x') as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'set', 'next_entry=' + attempt['entry']], check=True)
    env = command('grub-editenv', '/boot/grub/grubenv', 'list')
    require('next_entry=' + attempt['entry'] in env.splitlines(), 'Failed to queue test entry')
    boot_check()
    os.sync()
    print('Requesting single diagnostic reboot from ' + state['boot_id'], flush=True)
    subprocess.run(['systemctl', '--no-block', 'reboot'], check=True)
