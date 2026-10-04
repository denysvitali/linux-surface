#!/usr/bin/python3
"""Query both Y Smart Boost controls once with a bounded, archived read."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
Y = BASE / 'attempts/20260927y'
OUT = Y / 'mixer-read-test'
PARENT_BID = 'f5039e57-1a71-4833-9193-6da333d4d4f9'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def query(name, *args):
    try:
        trial = subprocess.run(args, capture_output=True, text=True, timeout=20)
        code, stdout, stderr = trial.returncode, trial.stdout, trial.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = (exc.stdout or b'').decode(errors='replace')
        stderr = (exc.stderr or b'').decode(errors='replace')
    (OUT / f'{name}.stdout').write_text(stdout)
    (OUT / f'{name}.stderr').write_text(stderr)
    return code, stdout


assert os.geteuid() == 0 and not OUT.exists()
BID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert BID != PARENT_BID and command('uname', '-r') == RELEASE
assert 'spx_attempt=20260927y' in Path('/proc/cmdline').read_text().split()
assert (Y / 'reboot-check-passed.json').is_file()
review = json.loads((Y / 'installed-review.json').read_text())
assert review['preboot_id'] == PARENT_BID and not review['boot_selected']
uptime = float(Path('/proc/uptime').read_text().split()[0])
assert 120 <= uptime < 500, uptime
assert command('systemctl', 'is-active', 'spx-y-fallback.timer') == 'active'
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
attempt = json.loads((Y / 'attempt.json').read_text())
for path, digest in (attempt['sha256'] | attempt['recovery_sha256']).items():
    assert sha(path) == digest, path

OUT.mkdir(mode=0o700)
pre = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager') + '\n'
(OUT / 'pre-kernel.log').write_text(pre)
(OUT / 'boot-id').write_text(BID + '\n')
(OUT / 'uptime').write_text(str(uptime) + '\n')
(OUT / 'grubenv').write_text('\n'.join(env) + '\n')
statuses = {}
statuses['controls'], controls = query('controls', 'amixer', '-c', '0', 'controls')
numids = sorted({int(m.group(1)) for line in controls.splitlines()
                 if 'Smart Boost Level' in line
                 for m in [re.match(r'numid=(\d+),', line)] if m})
statuses['scontrols'], _ = query('scontrols', 'amixer', '-c', '0', 'scontrols')
for numid in numids:
    statuses[f'cget-{numid}'], _ = query(f'cget-{numid}', 'amixer', '-c', '0',
                                         'cget', f'numid={numid}')
post = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager') + '\n'
(OUT / 'post-kernel.log').write_text(post)
assert post.startswith(pre)
delta = post[len(pre):]
(OUT / 'kernel-delta.log').write_text(delta)
(OUT / 'soundwire-slaves.json').write_text(json.dumps({
    p.name: {'status': (p / 'status').read_text().strip(),
             'device_number': (p / 'device_number').read_text().strip()}
    for p in sorted(Path('/sys/bus/soundwire/devices').glob('sdw:*'))},
    indent=2) + '\n')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
markers = {token: delta.count(token) for token in (
    'swrm_wait_for_rd_fifo_avail err read underflow',
    'swrm_wait_for_wr_fifo_avail err write overflow',
    'soc_component_read_no_lock() on sdw:0:0:0217:2010:00:4',
    'Update Slave status failed', 'Slave 1 initialization failed')}
passed = (len(numids) == 2 and all(value == 0 for value in statuses.values())
          and all(value == 0 for value in markers.values()))
report = {'attempt': '20260927y', 'boot_id': BID,
          'smart_boost_control_numids': numids,
          'command_exit_codes': statuses, 'kernel_delta_markers': markers,
          'kernel_delta_lines': len(delta.splitlines()), 'passed': passed}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
hashes = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
for name, digest in hashes.items():
    assert sha(OUT / name) == digest, name
os.sync()
print(json.dumps(report, indent=2))
