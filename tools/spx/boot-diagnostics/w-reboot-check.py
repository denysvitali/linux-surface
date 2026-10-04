#!/usr/bin/python3
"""Recheck W selection and artifact hashes immediately before reboot."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
W = BASE / 'attempts/20260927w'


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    assert os.geteuid() == 0
    a = json.loads((W / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20260927w' and a['entry'] == 'spx-trial-20260927w'
    assert a['state'].startswith('W selected once')
    assert (W / 'reboot-requested').exists()
    assert not (W / 'reboot-check-passed.json').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    assert command('uname', '-r') == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
    assert 'saved_entry=spx-known-good' in env
    assert 'next_entry=spx-trial-20260927w' in env
    assert 'BootNext:' not in command('efibootmgr')
    assert (W / 'entry.cfg').read_text() == Path('/boot/grub/custom.cfg').read_text()
    assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
    for path, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
        assert sha(path) == digest, path
    modules = json.loads((W / 'build/module-sha256.json').read_text())
    assert len(modules) == 202
    for name, digest in modules.items():
        assert sha(Path('/usr/lib/modules') / a['release'] / name) == digest, name
    review = json.loads((W / 'installed-review.json').read_text())
    assert review['preboot_id'] == a['preboot_id'] and not review['boot_selected']
    for unit in ('spx-w-finalize.timer', 'spx-w-fallback.timer'):
        assert command('systemctl', 'is-enabled', unit) == 'enabled'
    (W / 'reboot-check-passed.json').write_text(json.dumps({
        'boot_id': a['preboot_id'], 'queued_entry': a['entry'],
        'saved_entry': 'spx-known-good', 'payloads_verified': len(a['sha256']),
        'recovery_files_verified': len(a['recovery_sha256']),
        'module_files_verified': len(modules)}, indent=2) + '\n')
    (W / 'grubenv.immediate-preboot.txt').write_text('\n'.join(env) + '\n')
    os.sync()
    subprocess.run(['systemctl', '--no-block', 'reboot'], check=True, timeout=30)


try:
    main()
except BaseException:
    try:
        a = json.loads((W / 'attempt.json').read_text())
        same = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
        env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
        if same and 'next_entry=spx-trial-20260927w' in env:
            subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset',
                            'next_entry'], check=True, timeout=30)
            (W / 'reboot-check-failed-unqueued').write_text(a['preboot_id'] + '\n')
            os.sync()
    finally:
        raise
