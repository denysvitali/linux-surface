#!/usr/bin/env python3
"""Boot coordination for the installed native SPX desktop speaker service."""
import json
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import audio

OWNER = 'spx-desktop'
OUTPUT = Path('/var/lib/spx-desktop-playback')
LOCK_OWNER = Path('/tmp/spx-locks/spx-device.lock/owner')
LOCK_TOOL = Path(__file__).with_name('spx-lock')
GAIN = Path('/etc/spx/speaker-gain-step')


def release():
    if LOCK_OWNER.exists() and LOCK_OWNER.read_text().strip() == OWNER:
        subprocess.run([str(LOCK_TOOL), 'release', 'device', OWNER], check=True)


def prepare():
    subprocess.run([str(LOCK_TOOL), 'acquire', 'device', OWNER], check=True)
    try:
        audio.need(GAIN.read_text().strip() in ('0', '1', '2'), 'Invalid saved gain')
        deadline = time.monotonic() + 60
        while True:
            try:
                writer, _ = audio.codec_paths()
                cards = Path('/proc/asound/cards').read_text()
                usable = (writer.exists() and len(audio.devices()) == 2 and
                          len(re.findall(r'^\s*\d+\s+\[[^\]]+\].*Surface Pro X', cards, re.M)) == 1 and
                          Path('/run/user/1000/bus').exists())
                if usable:
                    break
            except (OSError, RuntimeError):
                pass
            audio.need(time.monotonic() < deadline, 'Native audio or user bus did not become ready')
            time.sleep(0.5)
        audio.assert_pcm_idle()
        # A previous failed stop can leave user daemons or runtime overrides.
        # Confirm no native initializer is alive before removing its leftovers.
        with open('/run/spx-audio-initialize.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            command = ['runuser', '-u', 'dvitali', '--', 'env',
                       'XDG_RUNTIME_DIR=/run/user/1000',
                       'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus',
                       'systemctl', '--user']
            for units in (('pipewire.socket', 'pipewire-pulse.socket'),
                          ('wireplumber.service', 'pipewire-pulse.service', 'pipewire.service')):
                # Socket-triggered stop transactions may cancel a job; the
                # exact paused-state check below is authoritative.
                subprocess.run(command + ['stop', *units], timeout=15, check=False)
            audio.assert_desktop_paused('dvitali')
            runtime = Path('/run/user/1000/systemd/user')
            for unit in audio.DesktopGraph.units:
                for stale in (runtime / (unit + '.d')).glob('zz-spx-desktop-*.conf'):
                    stale.unlink()
            subprocess.run(command + ['daemon-reload'], timeout=10, check=True)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / 'serve-ready.json').unlink(missing_ok=True)
    except BaseException:
        release()
        raise


def ready():
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            status = json.loads((OUTPUT / 'serve-ready.json').read_text())
            target = int(GAIN.read_text().strip())
            main_pid = os.environ.get('MAINPID')
            if (status['boot_id'] == boot and not status.get('stopped') and
                    status['pa_gain'] == target and
                    (not main_pid or status['owner_pid'] == int(main_pid)) and
                    Path(f"/proc/{status['owner_pid']}").exists() and
                    Path(f"/proc/{status['pcm_pid']}").exists()):
                release()
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.5)
    raise RuntimeError('Desktop speaker startup did not reach the saved gain')


if __name__ == '__main__':
    actions = {'prepare': prepare, 'ready': ready, 'release': release}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit('usage: desktop_audio_service.py prepare|ready|release')
    actions[sys.argv[1]]()
