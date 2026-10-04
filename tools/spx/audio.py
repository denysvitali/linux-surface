#!/usr/bin/env python3
"""Prepare and inspect SPX audio; explicitly test native amp enumeration.

Default: print an offline plan. ``initialize`` powers the amps sequentially
for at most five seconds each, checks hardware identities against the native
SoundWire devices, and parks both amps on every exit. It never opens a PCM,
loads a module, captures a microphone, or changes amplifier protection/gain.
The September 8 retained-stream late initialization is not yet a fresh-start
recipe. Successful enumeration alone therefore does not enable playback.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import sys
import time


MODULES = Path('/sys/module')
AUDIO_STATE = MODULES / 'soundwire_qcom/parameters/spx_audio_state'
UNITS = ('pipewire.service', 'pipewire.socket', 'pipewire-pulse.service',
         'pipewire-pulse.socket', 'wireplumber.service', 'pulseaudio.service',
         'pulseaudio.socket', 'spx-speaker-bridge.service',
         'spx-speaker-pcm-gate.service', 'spx-speaker-idle-mute.service',
         'spx-stereo-native.service', 'spx-stereo-desktop.service')
ID_TO_UNIT = {(0x21170213, 0x10): 3, (0x21170214, 0x10): 4}
UNMET = (
    'Fresh native dual-amp enumeration is not yet verified on mainline.',
    'Late initialization after the runtime clock switch must be ported from '
    'the retained-stream repair; do not replay its dead PIDs or force-attach paths.',
    'Fresh PCM routing, both companders bypassed, minimum PA gain and '
    'digital-silence settling must be verified before playback is enabled.',
)


def read_text(path):
    return Path(path).read_text().strip()


def parameter(module, name):
    return read_text(MODULES / module / 'parameters' / name)


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def state():
    values = dict(line.split('=', 1) for line in read_text(AUDIO_STATE).splitlines())
    parsed = {key: int(value, 0) for key, value in values.items()}
    required = {'COMP_PARAMS', 'SLV_STATUS', 'MCP_STATUS', 'GPIO_DIR', 'GPIO_VAL',
                'DEV1_ID1', 'DEV1_ID2', 'DEV2_ID1', 'DEV2_ID2', 'FRAME_B0',
                'FRAME_B1', 'FORCED_ATTACH'}
    need(required <= parsed.keys(), 'Incomplete driver audio-state interface')
    need(parsed['COMP_PARAMS'] == 0x016840c6, 'SoundWire bridge canary mismatch')
    need(parsed['FORCED_ATTACH'] == 0, 'Forced attachment is not native enumeration')
    return parsed


def devices():
    result = []
    for path in sorted(Path('/sys/bus/soundwire/devices').glob('sdw:*')):
        match = re.fullmatch(r'sdw:\d+:\d+:0217:2110:00:([34])', path.name)
        if not match:
            continue
        number = read_text(path / 'device_number')
        result.append({'name': path.name, 'unit': int(match[1]),
                       'status': read_text(path / 'status'),
                       'address': int(number) if number.isdigit() else None,
                       'driver': (path / 'driver').resolve().name
                       if (path / 'driver').exists() else None})
    return result


def identity_map(snapshot, slaves, expected):
    """Require physical presence, enumerator IDs and core binding to agree."""
    mapping = {}
    for address in (1, 2):
        status = (snapshot['SLV_STATUS'] >> (2 * address)) & 3
        if status == 0:
            continue
        need(status == 1, f'Address {address} is alert/reserved, not attached')
        identity = (snapshot[f'DEV{address}_ID1'], snapshot[f'DEV{address}_ID2'])
        need(identity in ID_TO_UNIT, f'Unknown physical identity at address {address}')
        unit = ID_TO_UNIT[identity]
        need(unit not in mapping, 'Duplicate physical amplifier identity')
        matches = [s for s in slaves if s['unit'] == unit and
                   s['address'] == address and s['status'] == 'Attached' and
                   s['driver'] == 'wsa881x-codec']
        need(len(matches) == 1, f'Physical unit {unit} lacks matching native codec binding')
        mapping[unit] = address
    need((snapshot['SLV_STATUS'] & ~0x3c) == 0,
         'Unexpected or unassigned physical device on SoundWire bus')
    need(set(mapping) == set(expected), f'Expected physical units {expected}, got {mapping}')
    return mapping


def assert_pcm_idle():
    for path in Path('/proc/asound').glob('card*/pcm*p/sub*/status'):
        need(read_text(path) == 'closed', f'Playback PCM is open: {path}')


def assert_desktop_paused(username):
    account = pwd.getpwnam(username)
    need(account.pw_uid != 0, 'Choose the desktop user, not root')
    runtime = f'/run/user/{account.pw_uid}'
    command = ['runuser', '-u', username, '--', 'env', f'XDG_RUNTIME_DIR={runtime}',
               f'DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus', 'systemctl',
               '--user', 'show', '--property=ActiveState', '--value', '--', *UNITS]
    result = subprocess.run(command, text=True, capture_output=True, timeout=5, check=True)
    states = result.stdout.splitlines()
    need(len(states) == len(UNITS) and all(s in ('inactive', 'failed') for s in states),
         'Caller must pause desktop audio services and sockets before initialization')
    for comm in Path('/proc').glob('[0-9]*/comm'):
        try:
            name = read_text(comm)
        except (FileNotFoundError, ProcessLookupError):
            continue
        need(name not in ('pipewire', 'pipewire-pulse', 'wireplumber', 'pulseaudio'),
             f'Desktop audio process still running: {name}')


def codec_writer():
    matches = []
    for path in Path('/sys/bus/slimbus/devices').iterdir():
        if (path / 'driver').exists() and (path / 'driver').resolve().name == 'wcd934x-slim':
            node = Path('/sys/kernel/debug') / path.name / 'write_reg'
            if node.exists():
                matches.append(node)
    need(len(matches) == 1, 'Need exactly one bound WCD codec debugfs write_reg node')
    return matches[0]


def inventory():
    cards = read_text('/proc/asound/cards')
    card_numbers = re.findall(r'^\s*(\d+)\s+\[[^\]]+\].*Surface Pro X', cards, re.M)
    return {'boot_id': read_text('/proc/sys/kernel/random/boot_id'),
            'release': os.uname().release, 'internal_cards': card_numbers,
            'devices': devices(), 'state': state()}


def save_initialize_result(directory, report):
    temporary = directory / f'.initialize-result.{os.getpid()}.json'
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(directory / 'initialize-result.json')


def initialize(args, report):
    need(os.geteuid() == 0, 'initialize requires root')
    need(args.allow_amp_power, 'initialize requires --allow-amp-power for this authorized run')
    need(args.owner and args.desktop_user, 'initialize requires --owner and --desktop-user')
    need(read_text('/tmp/spx-locks/spx-device.lock/owner') == args.owner,
         'Coordinator must own the device lock')
    need('microsoft,surface-pro-x' in
         Path('/sys/firmware/devicetree/base/compatible').read_bytes().decode().split('\0'),
         'This test is only for the Surface Pro X')
    for name, expected in (('spx_wsa_gpio_mask', 0x1e), ('spx_wsa_gpio_dir', 0x1e),
                           ('spx_wsa_gpio_val', 0x18), ('spx_wsa_en_pin', -1)):
        need(int(parameter('wcd934x', name), 0) == expected,
             f'Parked startup requires wcd934x.{name}={expected:#x}')
    for name in ('spx_force_attach', 'spx_blind_attach', 'spx_core_enum', 'spx_watchdog'):
        need(parameter('soundwire_qcom', name) == '0', f'{name} must be zero')
    for module, name, expected in (
            ('soundwire_qcom', 'spx_exact_windows_init', 'N'),
            ('soundwire_qcom', 'spx_broadcast_audio', 'N'),
            ('snd_soc_wsa881x', 'spx_enumerated_mode', 'Y'),
            ('snd_soc_wsa881x', 'spx_write_only', 'N')):
        need(parameter(module, name) == expected, f'{module}.{name} must be {expected}')
    assert_desktop_paused(args.desktop_user)
    assert_pcm_idle()
    writer = codec_writer()
    initial = inventory()
    need(len(initial['internal_cards']) == 1, 'Cannot identify one internal ALSA card')
    need(initial['state']['GPIO_DIR'] & 0x1e == 0x1e and
         initial['state']['GPIO_VAL'] & 0x1e == 0x18,
         'Physical GPIO state is not parked 0x1e/0x18')
    need(initial['state']['SLV_STATUS'] == 0, 'Amps must be detached before the test')
    report['before'] = initial
    report['stages'] = []
    report['parked'] = True
    parked = initial['state']['GPIO_VAL'] & ~0x06
    signals = {}

    def interrupted(signum, frame):
        raise InterruptedError(f'Interrupted by signal {signum}')

    # Signals arriving during cleanup must not bypass the park operation.
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signals[signum] = signal.signal(signum, interrupted)
    try:
        for bits, expected in ((0x02, {3}), (0x06, {3, 4})):
            assert_desktop_paused(args.desktop_user)
            assert_pcm_idle()
            report['parked'] = False
            writer.write_text(f'43 {parked | bits:02x}\n')
            stage = {'powered_pins': bits, 'samples': []}
            report['stages'].append(stage)
            deadline = time.monotonic() + 5
            last_error = 'No identity sample'
            stable = None
            while time.monotonic() < deadline:
                assert_pcm_idle()
                sample = {'state': state(), 'devices': devices()}
                stage['samples'].append(sample)
                need(sample['state']['GPIO_VAL'] & 0x1e == (0x18 | bits),
                     'GPIO changed unexpectedly during enumeration')
                try:
                    mapping = identity_map(sample['state'], sample['devices'], expected)
                except RuntimeError as error:
                    last_error, stable = str(error), None
                else:
                    if mapping == stable:
                        stage['physical_units_to_addresses'] = mapping
                        break
                    stable = mapping
                time.sleep(0.25)
            else:
                raise RuntimeError(f'Native enumeration did not settle: {last_error}')
        report['enumeration_passed'] = True
    finally:
        for signum in signals:
            signal.signal(signum, signal.SIG_IGN)
        try:
            writer.write_text(f'43 {parked:02x}\n')
            report['parked_state'] = state()
            need(report['parked_state']['GPIO_VAL'] & 0x1e == 0x18,
                 'Amplifier powerdown could not be confirmed')
            report['parked'] = True
        finally:
            for signum, handler in signals.items():
                signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('plan', 'inspect', 'initialize'), default='plan')
    parser.add_argument('--output', type=Path, help='directory for result JSON')
    parser.add_argument('--owner', help='coordinator device-lock owner (initialize)')
    parser.add_argument('--desktop-user', help='user whose audio units the caller has paused')
    parser.add_argument('--allow-amp-power', action='store_true',
                        help='explicitly authorize this bounded initialization run')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    report = {'action': args.action, 'utc': stamp, 'playback_ready': False,
              'microphone_capture': False, 'success': False, 'parked': False,
              'remaining_prerequisites': list(UNMET)}
    result = 0
    try:
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            if args.action == 'initialize':
                # A killed run must never leave an earlier "parked" verdict.
                save_initialize_result(args.output, report)
        if args.action == 'plan':
            report['initialization'] = (
                'Pause desktop audio services/sockets. Require parked GPIO 0x1e/0x18 '
                'and no playback PCM. Power pin1 and require native unit3, then power '
                'pin2 and require both native units3/4 at distinct addresses1/2. '
                'Allow five seconds per stage and require two agreeing samples. '
                'Always park both amps and verify physical GPIO readback afterwards. '
                'No PCM, tone, microphone capture, or amplifier gain/protection changes.')
        elif args.action == 'inspect':
            report['inventory'] = inventory()
        else:
            with open('/run/spx-audio-initialize.lock', 'w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                initialize(args, report)
        report['success'] = True
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        result = 1
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        (args.output / f'audio-{args.action}-{stamp}.json').write_text(text)
        if args.action == 'initialize':
            save_initialize_result(args.output, report)
    print(text, end='')
    return result


if __name__ == '__main__':
    sys.exit(main())
