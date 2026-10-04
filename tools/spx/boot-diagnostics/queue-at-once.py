#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Select the reviewed AT exactly once, then schedule its immediate reboot guard."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from at_boot_guard import BASE, X, load, preboot, files, sha, command, frozen_prequeue

SRC = Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')


def main():
    os.umask(0o077)
    assert not (X / 'reboot-requested').exists()
    a = load()
    assert a['state'] == 'prepared AT; no boot selection'
    review = json.loads((X / 'installed-review.json').read_text())
    assert review['preboot_id'] == a['preboot_id'] and not review['boot_selected']
    assert review['modules_verified'] == 208 and review['working_module_files_links_verified'] == 5183
    assert review['strict_ap_scope_unchanged'] and review['known_good_default']
    assert review['next_entry_empty'] and review['efi_bootnext_absent']
    for name, digest in json.loads((X / 'deployment-sources-sha256.json').read_text()).items():
        assert sha(SRC / name) == digest, name
    snapshot = X / 'preboot-snapshot'
    assert files(snapshot) == json.loads((snapshot / 'sha256.json').read_text()) | {'sha256.json': sha(snapshot / 'sha256.json')}
    assert (snapshot / 'boot-id').read_text().strip() == a['preboot_id']
    native = json.loads((X / 'native-continuation-review.json').read_text())
    assert native['boot_id'] == a['preboot_id'] and native['resumeOnDaemonStart']
    assert native['resumeOnDaemonStartMessage'] == 'continue' and native['lifecycleState'] == 'running'
    assert native['startedBy'] == 'daemon' and native['startedFromDaemon']
    assert native['legacy_resume_marker_absent'] and not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
    assert 0 <= time.time() - native['checked_wall_time'] < 300
    os.kill(native['hostPid'], 0)
    for path in ('/boot/grub/grub.cfg', '/boot/grub/custom.cfg'):
        subprocess.run(['grub-script-check', path], check=True, timeout=30)
    frozen_prequeue(a)
    preboot(a)
    when = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (X / 'reboot-requested').open('x') as file:
        file.write(when + '\n' + a['preboot_id'] + '\n')
        file.flush()
        os.fsync(file.fileno())

    def save(path):
        temporary = path.with_name(path.name + '.at-queue-new')
        assert not temporary.exists()
        temporary.write_text(json.dumps(a, indent=2) + '\n')
        temporary.replace(path)

    try:
        subprocess.run(['grub-reboot', a['entry']], check=True, timeout=30)
        env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
        assert 'saved_entry=spx-known-good' in env and 'next_entry=' + a['entry'] in env
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
        (X / 'grubenv.queued.txt').write_text('\n'.join(env) + '\n')
        a['state'] = 'AT selected once; scheduled immediate guard will verify before reboot'
        a['reboot_requested_at'] = when
        save(X / 'attempt.json')
        save(BASE / 'attempt.json')
        os.sync()
        subprocess.run(['systemd-run', '--unit=spx-trial-20261003at-reboot', '--on-active=30s',
                        '/usr/bin/python3', str(X / 'reboot-check.py')], check=True, timeout=30)
        assert command('systemctl', 'is-active', 'spx-trial-20261003at-reboot.timer') == 'active'
        (X / 'queue-review.json').write_text(json.dumps({
            'preboot_id': a['preboot_id'], 'entry': a['entry'], 'selected_once': True,
            'guarded_reboot_timer_active': True, 'guard_delay_seconds': 30,
            'known_good_default': True, 'request_marker_exclusive': True}, indent=2) + '\n')
        os.sync()
        print('AT selected once; immediate guard scheduled in30s; known-good remains persistent default')
    except BaseException:
        env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
        if 'next_entry=' + a['entry'] in env:
            subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset', 'next_entry'], check=True, timeout=30)
        a['state'] = 'AT queue failed; exclusive request marker retained; inspect before any retry'
        save(X / 'attempt.json')
        save(BASE / 'attempt.json')
        os.sync()
        raise


if __name__ == '__main__':
    main()
