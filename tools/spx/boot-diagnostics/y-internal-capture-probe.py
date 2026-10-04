#!/usr/bin/python3
"""Check whether Y's built-in capture path can measure speaker output."""

import hashlib
import json
import os
import struct
import subprocess
import time
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics/attempts/20260927y')
OUT = BASE / 'internal-capture-probe'
BOOT_ID = 'b5f0a540-3e81-4415-b08c-f869e01349a2'
RELEASE = '7.3.0-rc2-spx-mainline-20260927y+'


def command(*args):
    return subprocess.check_output(args, text=True, timeout=45)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


assert os.geteuid() == 0 and not OUT.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
assert command('uname', '-r').strip() == RELEASE
assert 'spx_attempt=20260927y' in Path('/proc/cmdline').read_text().split()
assert json.loads((BASE / 'final-result/result.json').read_text())['passed_scoped_baseline']
assert json.loads((BASE / 'finalizer-action.json').read_text())['fallback_stopped']
assert command('systemctl', 'show', 'spx-y-fallback.timer', '-p',
               'ActiveState', '--value').strip() == 'inactive'
env = command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()
assert 'saved_entry=spx-known-good' in env and 'next_entry=' in env
assert 'BootNext:' not in command('efibootmgr')
occupied = subprocess.run(['fuser', '/dev/snd/pcmC0D0c'], capture_output=True,
                          text=True, timeout=10)
assert occupied.returncode == 1 and not occupied.stdout.strip()

OUT.mkdir(mode=0o700)
(OUT / 'boot-id').write_text(BOOT_ID + '\n')
(OUT / 'pre-uptime').write_text(Path('/proc/uptime').read_text())
pre = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
(OUT / 'pre-kernel.log').write_text(pre)
args = ['/usr/bin/timeout', '-s', 'INT', '-k', '2s', '6s', '/usr/bin/arecord',
        '-D', 'hw:0,0', '-t', 'raw', '-f', 'S16_LE', '-c', '2', '-r', '48000',
        '-d', '1', str(OUT / 'capture.s16le')]
(OUT / 'command.json').write_text(json.dumps(args, indent=2) + '\n')
os.sync()
start = time.monotonic()
trial = subprocess.run(args, capture_output=True, text=True, timeout=10)
(OUT / 'arecord.stdout').write_text(trial.stdout)
(OUT / 'arecord.stderr').write_text(trial.stderr)
post = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
(OUT / 'post-kernel.log').write_text(post)
(OUT / 'post-uptime').write_text(Path('/proc/uptime').read_text())
assert post.startswith(pre)
delta = post[len(pre):]
(OUT / 'kernel-delta.log').write_text(delta)
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
data = (OUT / 'capture.s16le').read_bytes() if (OUT / 'capture.s16le').exists() else b''
samples = struct.unpack('<' + 'h' * (len(data) // 2), data[:len(data) // 2 * 2])
report = {'boot_id': BOOT_ID, 'arecord_exit_code': trial.returncode,
          'elapsed_seconds': time.monotonic() - start,
          'capture_bytes': len(data), 'nonzero_samples': sum(x != 0 for x in samples),
          'sample_peak': max((abs(x) for x in samples), default=0),
          'kernel_delta_lines': len(delta.splitlines()),
          'usable_acoustic_reference': False}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
hashes = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
for name, digest in hashes.items():
    assert sha(OUT / name) == digest
os.sync()
print(json.dumps(report, indent=2))
