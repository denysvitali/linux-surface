#!/usr/bin/python3
"""Recheck the single queued Q boot immediately before requesting reboot."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20260927q')
BASE = Path('/var/lib/spx-boot-diagnostics')


def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=30)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def main():
    assert os.geteuid() == 0
    a = json.loads((RUN / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20260927q' and a['entry'] == 'spx-trial-20260927q'
    assert (RUN / 'reboot-requested').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    assert cmd('uname', '-r').strip() == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    env = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert 'next_entry=spx-trial-20260927q' in env.splitlines()
    assert 'BootNext:' not in cmd('efibootmgr')
    for name, digest in (a['sha256'] | a['recovery_sha256']).items():
        assert sha(Path(name)) == digest, name
    for unit in ['spx-q-finalize.timer', 'spx-q-fallback.timer']:
        assert cmd('systemctl', 'is-enabled', unit).strip() == 'enabled'
    assert sha(Path('/usr/local/lib/spx-boot-diagnostics/q-finalize.py')) == \
           a['runtime_sha256']['/usr/local/lib/spx-boot-diagnostics/q-finalize.py']
    assert (RUN / 'entry.cfg').read_text().strip() in Path('/boot/grub/custom.cfg').read_text()
    assert not (RUN / 'reboot-check-passed.json').exists()
    (RUN / 'reboot-check-passed.json').write_text(json.dumps({
        'boot_id': a['preboot_id'], 'queued_entry': a['entry'],
        'saved_entry': 'spx-known-good', 'payloads_verified': len(a['sha256']),
        'recovery_files_verified': len(a['recovery_sha256'])}, indent=2) + '\n')
    (RUN / 'grubenv.immediate-preboot.txt').write_text(env)
    os.sync()
    subprocess.run(['systemctl', '--no-block', 'reboot'], check=True, timeout=30)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        try:
            a = json.loads((RUN / 'attempt.json').read_text())
            same_boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
            env = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
            if same_boot and 'next_entry=spx-trial-20260927q' in env.splitlines():
                subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset',
                                'next_entry'], check=True, timeout=30)
                (RUN / 'reboot-check-failed-unqueued').write_text(a['preboot_id'] + '\n')
                os.sync()
        finally:
            raise
