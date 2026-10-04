#!/usr/bin/python3
"""Archive one bounded, low-level left-channel signal after Y's baseline."""

import hashlib
import json
import math
import os
import struct
import subprocess
import time
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
Y = BASE / 'attempts/20260927y'
OUT = Y / 'low-level-tone-test'
BID = 'b5f0a540-3e81-4415-b08c-f869e01349a2'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=45)


assert os.geteuid() == 0 and not OUT.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
assert command('uname', '-r').strip() == RELEASE
assert 'spx_attempt=20260927y' in Path('/proc/cmdline').read_text().split()
result = json.loads((Y / 'final-result/result.json').read_text())
action = json.loads((Y / 'finalizer-action.json').read_text())
assert result['boot_id'] == BID and result['passed_scoped_baseline']
assert result['mixer_read_test_passed'] and result['silent_pcm_test_passed']
assert action['fallback_stopped']
assert command('systemctl', 'show', 'spx-y-fallback.timer', '-p',
               'ActiveState', '--value').strip() == 'inactive'
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
attempt = json.loads((Y / 'attempt.json').read_text())
for path, digest in (attempt['sha256'] | attempt['recovery_sha256']).items():
    assert sha(path) == digest, path
fuser = subprocess.run(['fuser', '/dev/snd/pcmC0D0p'],
                       capture_output=True, text=True, timeout=10)
assert fuser.returncode == 1 and not fuser.stdout.strip()
slaves = {p.name: {'status': (p / 'status').read_text().strip(),
                   'device_number': (p / 'device_number').read_text().strip()}
          for p in sorted(Path('/sys/bus/soundwire/devices').glob('sdw:*'))}
assert sum(v['status'] == 'Attached' and v['device_number'] == '1'
           for v in slaves.values()) == 1
assert sum(v['status'] == 'UNATTACHED' for v in slaves.values()) == 1

OUT.mkdir(mode=0o700)
(OUT / 'boot-id').write_text(BID + '\n')
(OUT / 'pre-uptime').write_text(Path('/proc/uptime').read_text())
(OUT / 'pre-soundwire.json').write_text(json.dumps(slaves, indent=2) + '\n')
pre = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
(OUT / 'pre-kernel.log').write_text(pre)
rate = 48000
frames = 48000
peak = 328  # approximately 1% of signed 16-bit full scale
fade = 960  # 20 ms at each edge
pcm = bytearray(frames * 4)
for i in range(frames):
    envelope = min(1.0, i / fade, (frames - 1 - i) / fade)
    left = round(peak * envelope * math.sin(2 * math.pi * 1000 * i / rate))
    struct.pack_into('<hh', pcm, i * 4, left, 0)
(OUT / 'signal.s16le').write_bytes(pcm)
cmd = ['/usr/bin/timeout', '-s', 'INT', '-k', '2s', '8s',
       '/usr/bin/aplay', '-D', 'hw:0,0', '-t', 'raw', '-f', 'S16_LE',
       '-c', '2', '-r', str(rate), '-s', str(frames),
       str(OUT / 'signal.s16le')]
(OUT / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n')
os.sync()
start = time.monotonic()
try:
    trial = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
    code, stdout, stderr = trial.returncode, trial.stdout, trial.stderr
except subprocess.TimeoutExpired as exc:
    code = 124
    stdout = (exc.stdout or b'').decode(errors='replace')
    stderr = (exc.stderr or b'').decode(errors='replace')
(OUT / 'aplay.stdout').write_text(stdout)
(OUT / 'aplay.stderr').write_text(stderr)
post = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
(OUT / 'post-kernel.log').write_text(post)
(OUT / 'post-uptime').write_text(Path('/proc/uptime').read_text())
assert post.startswith(pre)
delta = post[len(pre):]
(OUT / 'kernel-delta.log').write_text(delta)
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
markers = {token: delta.count(token) for token in (
    'swrm_wait_for_wr_fifo_avail err write overflow',
    'swrm_wait_for_rd_fifo_avail err read underflow',
    'Update Slave status failed', 'Slave 1 initialization failed',
    'Failed to change PA gain')}
report = {'attempt': '20260927y', 'boot_id': BID,
          'signal': '1000 Hz sine, left only, right zero, 1% peak, 20 ms fades',
          'pcm': 'hw:0,0', 'format': 'S16_LE', 'rate_hz': rate,
          'channels': 2, 'samples_per_channel': frames,
          'signal_sha256': sha(OUT / 'signal.s16le'),
          'aplay_exit_code': code,
          'aplay_elapsed_seconds': time.monotonic() - start,
          'kernel_delta_markers': markers,
          'physical_audio_verified': False}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
hashes = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
for name, digest in hashes.items():
    assert sha(OUT / name) == digest, name
os.sync()
print(json.dumps(report, indent=2))
