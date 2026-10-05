#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""One late SSAM probe after the known SPX startup timeout; not a root-cause fix."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


LOCK = Path(__file__).with_name('spx-lock')
DRIVER = 'surface_serial_hub'


def compatible(path, value):
    try:
        return value.encode() in path.read_bytes().split(b'\0')
    except FileNotFoundError:
        return False


def bound(client):
    return (client / 'driver').is_symlink()


def run(root=Path('/'), lock_tool=LOCK):
    """The root argument exists for offline filesystem tests, not a CLI override."""
    result = {'workaround': 'one late SSAM probe', 'outcome': 'not_started'}
    if not compatible(root / 'sys/firmware/devicetree/base/compatible',
                      'microsoft,surface-pro-x'):
        return dict(result, outcome='wrong_board')
    result['boot_id'] = (root / 'proc/sys/kernel/random/boot_id').read_text().strip()
    result['kernel'] = (root / 'proc/sys/kernel/osrelease').read_text().strip()
    uptime = float((root / 'proc/uptime').read_text().split()[0])
    time.sleep(max(0, 30 - uptime))
    clients = [p for p in (root / 'sys/bus/serial/devices').glob('*')
               if compatible(p / 'of_node/compatible', 'microsoft,surface-sam')]
    if len(clients) != 1:
        return dict(result, outcome='missing_or_ambiguous_client')
    client, = clients
    result['client'] = client.name
    state = root / 'run/spx-ssam-startup'
    if (state / 'attempt').exists():
        return dict(result, outcome='already_attempted')
    if bound(client):
        return dict(result, outcome='already_bound')
    bind = root / f'sys/bus/serial/drivers/{DRIVER}/bind'
    if not bind.exists():
        return dict(result, outcome='driver_unavailable')
    journal = subprocess.run(
        ['journalctl', '--boot=' + result['boot_id'].replace('-', ''), '--dmesg', '--quiet',
         '--no-pager', '--output=cat', '--lines=50',
         '--grep=^' + re.escape(f'{DRIVER} {client.name}:')],
        capture_output=True, text=True, timeout=5)
    if journal.returncode:
        return dict(result, outcome='journal_unavailable', error=journal.stderr.strip())
    lines = journal.stdout.splitlines()
    expected = [
        f'{DRIVER} {client.name}: error -ETIMEDOUT: failed to get firmware version',
        f'{DRIVER} {client.name}: probe with driver {DRIVER} failed with error -110',
    ]
    if not all(line in lines for line in expected):
        return dict(result, outcome='no_matching_timeout')
    result['evidence'] = expected
    owner = f'ssam-startup-{os.getpid()}'
    acquired = subprocess.run(
        [str(lock_tool), 'acquire', 'device', owner, 'one late SSAM probe'],
        capture_output=True, text=True, timeout=5)
    if acquired.returncode:
        return dict(result, outcome='device_busy', error=acquired.stderr.strip())
    try:
        if bound(client):
            return dict(result, outcome='bound_before_retry')
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            with (state / 'attempt').open('x') as marker:
                marker.write(result['boot_id'] + '\n')
        except FileExistsError:
            return dict(result, outcome='already_attempted')
        # Persist intent before the single write, even if the service is killed.
        result['outcome'] = 'bind_started'
        (state / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
        started = time.monotonic()
        try:
            probe = subprocess.run(
                [sys.executable, '-c',
                 'import os,sys; fd=os.open(sys.argv[1],os.O_WRONLY); '
                 'os.write(fd,sys.argv[2].encode()); os.close(fd)',
                 str(bind), client.name], capture_output=True, text=True, timeout=20)
            result['outcome'] = ('bound' if probe.returncode == 0 and bound(client)
                                 else 'bind_failed')
            result['bind_returncode'] = probe.returncode
            if probe.stderr:
                result['error'] = probe.stderr.strip()
        except subprocess.TimeoutExpired:
            result['outcome'] = 'bind_timed_out'
        result['bind_seconds'] = round(time.monotonic() - started, 4)
        result['bound_after'] = bound(client)
    finally:
        released = subprocess.run(
            [str(lock_tool), 'release', 'device', owner],
            capture_output=True, text=True, timeout=5)
        if released.returncode:
            result['lock_release_error'] = released.stderr.strip()
    return result


def main():
    try:
        result = run()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {'outcome': 'error', 'error': str(exc)}
    print(json.dumps(result), flush=True)
    # Journal retains every outcome across reboot; /run keeps the last full attempt.
    state = Path('/run/spx-ssam-startup')
    if result['outcome'] not in ('wrong_board', 'already_attempted'):
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        (state / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return int(result['outcome'] in ('error', 'bind_failed', 'bind_timed_out'))


if __name__ == '__main__':
    sys.exit(main())
