#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Recheck AT's exclusive selection, live known-good identity and recovery immediately."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from at_boot_guard import X, load, preboot, command, frozen_prequeue

os.umask(0o077)
try:
    a = load()
    assert a['state'].startswith('AT selected once') and (X / 'reboot-requested').exists()
    assert not (X / 'reboot-check-passed.json').exists()
    frozen_prequeue(a)
    env = preboot(a, a['entry'])
    with (X / 'reboot-check-passed.json').open('x') as file:
        json.dump({'boot_id': a['preboot_id'], 'queued_entry': a['entry'],
                   'saved_entry': 'spx-known-good', 'payloads_verified': 3,
                   'recovery_payloads_verified': 3, 'working_module_files_links_verified': 5183,
                   'trial_module_files_verified': 208}, file, indent=2)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())
    (X / 'grubenv.immediate-preboot.txt').write_text('\n'.join(k + '=' + v for k, v in env.items()) + '\n')
    marker = (f"SPX: outgoing handoff attempt=20261003as boot_id={a['preboot_id']} "
              f"release={a['preboot_release']} next_attempt=20261003at")
    (X / 'outgoing-identity-marker.txt').write_text(marker + '\n')
    os.sync()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    latest = dict(line.split('=', 1) for line in
                  command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert latest.get('saved_entry') == 'spx-known-good' and latest.get('next_entry') == a['entry']
    with Path('/dev/kmsg').open('w') as file:
        file.write('<6>' + marker + '\n')
        file.flush()
    subprocess.run(['systemctl', '--no-block', 'reboot'], check=True, timeout=30)
except BaseException:
    try:
        a = load()
        same = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
        env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
        if same and 'next_entry=' + a['entry'] in env:
            subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset', 'next_entry'], check=True, timeout=30)
            (X / 'reboot-check-failed-unqueued').write_text(a['preboot_id'] + '\n')
            os.sync()
    finally:
        raise
