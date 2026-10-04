#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Select the verified BE trial once and recheck identity immediately before reboot."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from be_boot_guard import BASE, X, command, load, preboot, sha


def replace_json(path, value):
    temporary = path.with_name(path.name + '.be-new')
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    os.umask(0o077)
    a = load()
    assert a['state'] == 'prepared BE; no boot selection'
    assert not (X / 'reboot-requested').exists()
    assert not (X / 'reboot-check-passed.json').exists()
    preboot(a)
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert sha(firmware) == sha(X / 'preparation/installed-00042.mbn') == \
        '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    with (X / 'reboot-requested').open('x') as stream:
        json.dump(dict(preboot_id=a['preboot_id'], entry=a['entry'],
                       checker_sha256=sha(Path(__file__))), stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    try:
        subprocess.run(['grub-reboot', a['entry']], check=True, timeout=30)
        a['state'] = 'BE selected once; startup trial pending'
        replace_json(X / 'attempt.json', a)
        replace_json(BASE / 'attempt.json', a)
        checked = preboot(a, a['entry'])
        assert sha(firmware) == sha(X / 'preparation/installed-00042.mbn')
        with (X / 'reboot-check-passed.json').open('x') as stream:
            json.dump(dict(preboot=checked, entry=a['entry'], persistent_default='spx-known-good',
                           checker_sha256=sha(Path(__file__))), stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        marker = (f"SPX: outgoing handoff spx_boot=known-good boot_id={a['preboot_id']} "
                  f"release={a['preboot_release']} next_attempt=20261004be")
        (X / 'outgoing-identity-marker.txt').write_text(marker + '\n')
        os.sync()
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
        latest = dict(line.split('=', 1) for line in
                      command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
        assert latest.get('saved_entry') == 'spx-known-good' and latest.get('next_entry') == a['entry']
        assert 'BootNext:' not in command('efibootmgr')
        with Path('/dev/kmsg').open('w') as stream:
            stream.write('<6>' + marker + '\n')
            stream.flush()
        subprocess.run(['systemctl', '--no-block', 'reboot'], check=True, timeout=30)
    except BaseException:
        same = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
        env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
        if same and 'next_entry=' + a['entry'] in env:
            subprocess.run(['grub-editenv', '/boot/grub/grubenv', 'unset', 'next_entry'], check=True, timeout=30)
            (X / 'reboot-check-failed-unqueued').write_text(a['preboot_id'] + '\n')
            os.sync()
        raise


if __name__ == '__main__':
    main()
