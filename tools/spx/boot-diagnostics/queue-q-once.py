#!/usr/bin/python3
"""Select Q exactly once after final read-only verification."""

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
RUN = BASE / 'attempts/20260927q'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')


def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=90)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    assert os.geteuid() == 0
    assert not (RUN / 'reboot-requested').exists(), 'Q was already selected'
    a = json.loads((RUN / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20260927q' and a['entry'] == 'spx-trial-20260927q'
    assert a['state'].startswith('prepared Q')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    assert cmd('uname', '-r').strip() == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    assert 'READ-ONLY PASS' in (RUN / 'preflight.log').read_text()
    assert json.loads((RUN / 'independent-preparation-review/report.json').read_text())['result'] == \
           'passed independent read-only Q preparation review'
    assert sha(RUN / 'build-sha256.json') == '84df0c3afb1e75bf374f8f5027285f412539d948c860648ee40541c8cb96447e'
    assert sha(RUN / 'origin-result-sha256.json') == \
           'f8c877eca2f9ed6c83eda59e38096fadce8823f36813488fa409da2814f37550'
    for name, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
        assert sha(Path(name)) == digest, name
    assert (RUN / 'entry.cfg').read_text().strip() in Path('/boot/grub/custom.cfg').read_text()
    assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
    for unit in ['spx-q-finalize.timer', 'spx-q-fallback.timer']:
        assert cmd('systemctl', 'is-enabled', unit).strip() == 'enabled'
    assert 'OnBootSec=620' in Path('/etc/systemd/system/spx-q-finalize.timer').read_text()
    assert 'OnBootSec=900' in Path('/etc/systemd/system/spx-q-fallback.timer').read_text()
    assert 'ConditionKernelCommandLine=!spx_attempt=20260927q' in \
           Path('/etc/systemd/system/spx-diag-long-return.timer.d/90-q-exclude.conf').read_text()
    with (RUN / 'preflight-final.log').open('w') as log:
        subprocess.run(['python3', str(REPO / 'tools/spx/boot-diagnostics/preflight.py')],
                       check=True, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    assert 'READ-ONLY PASS' in (RUN / 'preflight-final.log').read_text()
    env = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert 'next_entry=' in env.splitlines()
    assert 'BootNext:' not in cmd('efibootmgr')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    (RUN / 'grubenv.before-queue.txt').write_text(env)
    when = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (RUN / 'reboot-requested').open('x') as marker:
        marker.write(when + '\n' + a['preboot_id'] + '\n')
        marker.flush()
        os.fsync(marker.fileno())
    try:
        subprocess.run(['grub-reboot', a['entry']], check=True, timeout=30)
        selected = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
        assert 'saved_entry=spx-known-good' in selected.splitlines()
        assert 'next_entry=' + a['entry'] in selected.splitlines()
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
        (RUN / 'grubenv.queued.txt').write_text(selected)
        a['state'] = 'Q selected once; scheduled reboot check will verify before reboot'
        a['reboot_requested_at'] = when
        save(RUN / 'attempt.json', a)
        save(BASE / 'attempt.json', a)
        os.sync()
        subprocess.run(['systemd-run', '--unit=spx-trial-20260927q-reboot',
                        '--on-active=30s', '/usr/bin/python3',
                        str(RUN / 'reboot-check.py')],
                       check=True, timeout=30)
        print('Q queued once; checked reboot scheduled in 30 seconds', flush=True)
    except BaseException:
        current = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
        if 'next_entry=' + a['entry'] in current.splitlines():
            subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset',
                            'next_entry'], check=True, timeout=30)
        a['state'] = 'queue failed; request marker retained; inspect before retry'
        save(RUN / 'attempt.json', a)
        save(BASE / 'attempt.json', a)
        os.sync()
        raise


if __name__ == '__main__':
    main()
