#!/usr/bin/python3
"""Select AG once after verified AF fallback return."""

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20260930ag'


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


assert os.geteuid() == 0 and not (X / 'reboot-requested').exists()
a = json.loads((X / 'attempt.json').read_text())
assert a == json.loads((BASE / 'attempt.json').read_text())
assert a['attempt'] == '20260930ag' and a['entry'] == 'spx-trial-20260930ag'
assert a['state'] == 'prepared AG; no boot selection'
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
assert command('uname', '-r') == '6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
review = json.loads((X / 'installed-review.json').read_text())
for name, digest in json.loads((X / 'deployment-sources-sha256.json').read_text()).items():
    assert sha(X / 'deployment-sources' / name) == digest, name
    assert sha(Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics') / name) == digest, name
assert review['preboot_id'] == a['preboot_id'] and not review['boot_selected']
assert review['modules_verified'] == 202
assert review['build_files_verified'] == len(json.loads((X / 'build-sha256.json').read_text()))
assert review['known_good_default'] and review['next_entry_empty']
assert review['efi_bootnext_absent'] and not review['boot_selected']
snap = json.loads((X / 'preboot-snapshot/sha256.json').read_text())
for name, digest in snap.items():
    assert sha(X / 'preboot-snapshot' / name) == digest, name
assert (X / 'preboot-snapshot/boot-id').read_text().strip() == a['preboot_id']
assert (X / 'entry.cfg').read_text() == Path('/boot/grub/custom.cfg').read_text()
assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
for path, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
    assert sha(path) == digest, path
for name, digest in json.loads((X / 'dtb-sha256.json').read_text()).items():
    assert sha(X / 'dtb-build' / name) == digest, name
modules = json.loads((X / 'build/module-sha256.json').read_text())
module_root = Path('/usr/lib/modules') / a['release']
assert len(modules) == 202
for name, digest in modules.items():
    assert sha(module_root / name) == digest, name
for unit in ('spx-ag-finalize.timer', 'spx-ag-fallback.timer'):
    assert command('systemctl', 'is-enabled', unit) == 'enabled'
    assert command('systemctl', 'show', unit, '-p', 'ActiveState', '--value') != 'active'
assert '!spx_attempt=20260930ag' in Path(
    '/etc/systemd/system/spx-diag-long-return.timer.d/105-ag-exclude.conf').read_text()
subprocess.run(['grub-script-check', '/boot/grub/grub.cfg'], check=True, timeout=30)
subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
when = datetime.datetime.now(datetime.timezone.utc).isoformat()
with (X / 'reboot-requested').open('x') as marker:
    marker.write(when + '\n' + a['preboot_id'] + '\n')
    marker.flush()
    os.fsync(marker.fileno())
try:
    subprocess.run(['grub-reboot', a['entry']], check=True, timeout=30)
    selected = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
    assert 'saved_entry=spx-known-good' in selected
    assert 'next_entry=' + a['entry'] in selected
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    (X / 'grubenv.queued.txt').write_text('\n'.join(selected) + '\n')
    a['state'] = 'AG selected once; scheduled reboot check will verify before reboot'
    a['reboot_requested_at'] = when
    save(X / 'attempt.json', a)
    save(BASE / 'attempt.json', a)
    os.sync()
    subprocess.run(['systemd-run', '--unit=spx-trial-20260930ag-reboot',
                    '--on-active=30s', '/usr/bin/python3',
                    str(X / 'reboot-check.py')], check=True, timeout=30)
    print('AG selected once; immediate guard will reboot in 30 seconds')
except BaseException:
    current = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
    if 'next_entry=' + a['entry'] in current:
        subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset',
                        'next_entry'], check=True, timeout=30)
    a['state'] = 'queue failed; request marker retained; inspect before retry'
    save(X / 'attempt.json', a)
    save(BASE / 'attempt.json', a)
    os.sync()
    raise
