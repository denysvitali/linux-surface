#!/usr/bin/python3
"""Run one bounded, silent PCM transport probe on the verified W boot."""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
W = BASE / 'attempts/20260927w'
OUT = W / 'silent-pcm-test'
BID = 'e6989b7a-9ee5-4138-939d-84f8f73f53d5'
RELEASE = '7.3.0-rc2-spx-mainline-20260927w+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def run(*args):
    return subprocess.check_output(args, text=True, timeout=45)


def slaves():
    root = Path('/sys/bus/soundwire/devices')
    return {p.name: {'status': (p / 'status').read_text().strip(),
                     'device_number': (p / 'device_number').read_text().strip()}
            for p in sorted(root.glob('sdw:*'))}


assert os.geteuid() == 0 and not OUT.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert run('uname', '-r').strip() == RELEASE
assert 'spx_attempt=20260927w' in Path('/proc/cmdline').read_text().split()
assert (W / 'final-result').is_dir()
review = json.loads((W / 'independent-result-review.json').read_text())
assert review['boot_id'] == BID and review['scoped_passed']
assert review['fallback_stopped']
assert run('systemctl', 'show', 'spx-w-fallback.timer', '-p',
           'ActiveState', '--value').strip() != 'active'
env = run('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in run('efibootmgr')
a = json.loads((W / 'attempt.json').read_text())
for path, digest in (a['sha256'] | a['recovery_sha256']).items():
    assert sha(path) == digest, path
fuser = subprocess.run(['fuser', '/dev/snd/pcmC0D0p'],
                       capture_output=True, text=True, timeout=10)
assert fuser.returncode == 1 and not fuser.stdout.strip(), fuser.stdout
pre_slaves = slaves()
assert sum(v['status'].casefold() == 'attached' and v['device_number'] == '1'
           for v in pre_slaves.values()) == 1
OUT.mkdir(mode=0o700)
(OUT / 'pre-kernel.log').write_text(run('journalctl', '-b', '-k',
                                      '-o', 'short-monotonic', '--no-pager'))
(OUT / 'pre-boot-id').write_text(BID + '\n')
(OUT / 'pre-uptime').write_text(Path('/proc/uptime').read_text())
(OUT / 'pre-soundwire.json').write_text(json.dumps(pre_slaves, indent=2) + '\n')
(OUT / 'pre-grubenv').write_text('\n'.join(env) + '\n')
cmd = ['/usr/bin/timeout', '-s', 'INT', '-k', '2s', '8s',
       '/usr/bin/aplay', '-D', 'hw:0,0', '-t', 'raw', '-f', 'S16_LE',
       '-c', '2', '-r', '48000', '-s', '48000', '/dev/zero']
(OUT / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n')
os.sync()
start = time.monotonic()
try:
    trial = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
    status = trial.returncode
    stdout, stderr = trial.stdout, trial.stderr
except subprocess.TimeoutExpired as exc:
    status = 124
    stdout = (exc.stdout or b'').decode(errors='replace')
    stderr = (exc.stderr or b'').decode(errors='replace')
duration = time.monotonic() - start
(OUT / 'aplay.stdout').write_text(stdout)
(OUT / 'aplay.stderr').write_text(stderr)
(OUT / 'post-kernel.log').write_text(run('journalctl', '-b', '-k',
                                       '-o', 'short-monotonic', '--no-pager'))
(OUT / 'post-uptime').write_text(Path('/proc/uptime').read_text())
(OUT / 'post-soundwire.json').write_text(json.dumps(slaves(), indent=2) + '\n')
(OUT / 'post-asound-cards').write_text(Path('/proc/asound/cards').read_text())
(OUT / 'post-taint').write_text(Path('/proc/sys/kernel/tainted').read_text())
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
pre = (OUT / 'pre-kernel.log').read_text()
post = (OUT / 'post-kernel.log').read_text()
assert post.startswith(pre)
delta = post[len(pre):]
(OUT / 'kernel-delta.log').write_text(delta)
markers = {token: delta.count(token) for token in
           ('swrm_wait_for_wr_fifo_avail err write overflow',
            'swrm_wait_for_rd_fifo_avail err read underflow',
            'Update Slave status failed', 'Slave 1 initialization failed',
            'SPX: device=1 hw_params active_ports=',
            'SPX: device=1 excluded from this stream',
            'Failed to change PA gain')}
report = {'attempt': '20260927w', 'boot_id': BID,
          'pcm': 'hw:0,0', 'format': 'S16_LE', 'rate_hz': 48000,
          'channels': 2, 'samples_per_channel': 48000,
          'signal': 'digital zero', 'aplay_exit_code': status,
          'aplay_elapsed_seconds': duration,
          'pre_soundwire': pre_slaves, 'post_soundwire': slaves(),
          'kernel_delta_markers': markers,
          'kernel_delta_lines': len(delta.splitlines()),
          'physical_audio_verified': False}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
hashes = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
for name, digest in hashes.items():
    assert sha(OUT / name) == digest, name
os.sync()
print(json.dumps(report, indent=2))
