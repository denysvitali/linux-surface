#!/usr/bin/python3
"""Select the reviewed V readless-codec trial once from U."""

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
V = BASE / 'attempts/20260927v'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


assert os.geteuid() == 0 and not (V / 'reboot-requested').exists()
a = json.loads((V / 'attempt.json').read_text())
assert a == json.loads((BASE / 'attempt.json').read_text())
assert a['attempt'] == '20260927v' and a['entry'] == 'spx-trial-20260927v'
assert a['state'] == 'prepared V; no boot selection'
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260927r+'
assert 'spx_attempt=20260927u' in Path('/proc/cmdline').read_text().split()
review = json.loads((V / 'installed-review.json').read_text())
assert review['preboot_id'] == a['preboot_id'] and not review['boot_selected']
assert review['modules_verified'] == 202
assert review['payloads_exactly_u'] is True
snap = json.loads((V / 'preboot-snapshot/sha256.json').read_text())
for name, digest in snap.items():
    assert sha(V / 'preboot-snapshot' / name) == digest, name
assert (V / 'preboot-snapshot/boot-id').read_text().strip() == a['preboot_id']
assert (V / 'entry.cfg').read_text() == Path('/boot/grub/custom.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
for path, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
    assert sha(path) == digest, path
modules = json.loads((V / 'reused-build/module-sha256.json').read_text())
module_root = Path('/usr/lib/modules') / a['release']
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(module_root / name) == digest, name
for unit in ('spx-v-finalize.timer', 'spx-v-fallback.timer'):
    assert command('systemctl', 'is-enabled', unit) == 'enabled'
    assert command('systemctl', 'show', unit, '-p', 'ActiveState', '--value') != 'active'
assert '!spx_attempt=20260927v' in Path(
    '/etc/systemd/system/spx-diag-long-return.timer.d/95-v-exclude.conf').read_text()
subprocess.run(['grub-script-check', '/boot/grub/grub.cfg'], check=True, timeout=30)
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
when = datetime.datetime.now(datetime.timezone.utc).isoformat()
with (V / 'reboot-requested').open('x') as marker:
    marker.write(when + '\n' + a['preboot_id'] + '\n')
    marker.flush()
    os.fsync(marker.fileno())
try:
    subprocess.run(['grub-reboot', a['entry']], check=True, timeout=30)
    selected = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
    assert 'saved_entry=spx-known-good' in selected
    assert 'next_entry=' + a['entry'] in selected
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    (V / 'grubenv.queued.txt').write_text('\n'.join(selected) + '\n')
    a['state'] = 'V selected once; scheduled reboot check will verify before reboot'
    a['reboot_requested_at'] = when
    save(V / 'attempt.json', a)
    save(BASE / 'attempt.json', a)
    os.sync()
    subprocess.run(['systemd-run', '--unit=spx-trial-20260927v-reboot',
                    '--on-active=30s', '/usr/bin/python3',
                    str(V / 'reboot-check.py')], check=True, timeout=30)
    print('V selected once; immediate guard will reboot in 30 seconds')
except BaseException:
    current = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
    if 'next_entry=' + a['entry'] in current:
        subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset',
                        'next_entry'], check=True, timeout=30)
    a['state'] = 'queue failed; request marker retained; inspect before retry'
    save(V / 'attempt.json', a)
    save(BASE / 'attempt.json', a)
    os.sync()
    raise
