#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Capture the functional test journal and return to the persistent default."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    os.umask(0o077)
    words = Path('/proc/cmdline').read_text().split()
    attempts = [w.split('=', 1)[1] for w in words if w.startswith('spx_attempt=')]
    assert attempts == ['20261004bg'] and 'spx_boot=mainline-functional' in words
    out = Path('/var/lib/spx-boot-diagnostics/functional') / attempts[0]
    prepared = json.loads((out / 'prepared.json').read_text())
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot != prepared['preboot_id'] and os.uname().release == prepared['release']
    recovery = json.loads((out / 'working-recovery.json').read_text())
    cfg = Path('/boot/grub/grub.cfg').read_text()
    assert recovery['entry'] in cfg and 'set default="spx-known-good"' in cfg
    for path, expected in recovery['payload_sha256'].items():
        h = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for data in iter(lambda: stream.read(1048576), b''):
                h.update(data)
        assert h.hexdigest() == expected
    env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert not any(l.startswith('next_entry=') and l != 'next_entry=' for l in env.splitlines())
    assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
    for label, args in [('kernel.log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic']),
                        ('journal.log', ['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'])]:
        with (out / label).open('wb') as stream:
            subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=30)
    (out / 'return.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(),
        boot_id=boot, release=os.uname().release, uptime=Path('/proc/uptime').read_text().strip(),
        known_good_payloads_intact=True, persistent_default='spx-known-good', next_entry_empty=True), indent=2) + '\n')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    env = dict(line.split('=', 1) for line in subprocess.check_output(
        ['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines())
    assert env['saved_entry'] == 'spx-known-good' and not env.get('next_entry')
    os.sync()
    subprocess.run(['systemctl', 'reboot'], check=True)


if __name__ == '__main__':
    main()
