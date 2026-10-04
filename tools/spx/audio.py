#!/usr/bin/env python3
"""Prepare, inspect and explicitly test native SPX speaker audio.

Default: print an offline plan. ``initialize`` powers the amps sequentially,
allows five seconds of polling per stage, checks hardware identities against
the native SoundWire devices, and attempts to park both amps on every exit
after power-up. ``listen`` additionally requires explicit playback permission;
it owns one fresh PCM, checks stereo routing and late initialization on digital
silence, then plays a bounded left/right/both sequence at minimum PA gain.
``recover`` flushes only the command FIFO, requiring amps already off and no
streams. None of these actions captures a microphone or loads modules.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import pwd
import re
import queue
import select
import signal
import struct
import subprocess
import sys
import tempfile
import threading
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
    'Verify fresh native dual-amp enumeration in this run.',
    'Verify both codecs late-initialize after the fresh PCM runtime clock switch.',
    'Verify stereo ports, companders bypassed, minimum PA gain and silence settling.',
    'A person must confirm left/right sound, clarity and the absence of static.',
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
        codec_state = playback_state(path) if (path / 'spx_playback_state').exists() else {}
        result.append({'name': path.name, 'unit': int(match[1]),
                       'status': read_text(path / 'status'),
                       'address': int(number) if number.isdigit() else None,
                       'initialized': bool(codec_state['HW_INIT']) if 'HW_INIT' in codec_state else None,
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
                   s['driver'] == 'wsa881x-codec' and s.get('initialized') is True]
        need(len(matches) == 1, f'Physical unit {unit} lacks matching initialized native codec')
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
    # systemctl separates multiple unit records with blank lines.
    states = [line for line in result.stdout.splitlines() if line]
    need(len(states) == len(UNITS) and all(s in ('inactive', 'failed') for s in states),
         'Caller must pause desktop audio services and sockets before initialization')
    for comm in Path('/proc').glob('[0-9]*/comm'):
        try:
            name = read_text(comm)
        except (FileNotFoundError, ProcessLookupError):
            continue
        need(name not in ('pipewire', 'pipewire-pulse', 'wireplumber', 'pulseaudio'),
             f'Desktop audio process still running: {name}')


def codec_paths():
    codecs = []
    for path in Path('/sys/bus/slimbus/devices').iterdir():
        if (path / 'driver').exists() and (path / 'driver').resolve().name == 'wcd934x-slim':
            codecs.append(path)
    need(len(codecs) == 1, 'Need exactly one bound WCD codec')
    codec = codecs[0]
    masters = [path.resolve() for path in
               Path('/sys/bus/platform/drivers/qcom-soundwire').iterdir()
               if path.is_symlink() and path.resolve().is_relative_to(codec.resolve())]
    need(len(masters) == 1, 'Need exactly one bound SoundWire master below the WCD codec')
    return Path('/sys/kernel/debug') / codec.name / 'write_reg', masters[0]


def inventory(master=None):
    if master is None:
        _, master = codec_paths()
    power = {'device': str(master), 'control': read_text(master / 'power/control'),
             'status': read_text(master / 'power/runtime_status')}
    cards = read_text('/proc/asound/cards')
    card_numbers = re.findall(r'^\s*(\d+)\s+\[[^\]]+\].*Surface Pro X', cards, re.M)
    result = {'boot_id': read_text('/proc/sys/kernel/random/boot_id'),
              'release': os.uname().release, 'internal_cards': card_numbers,
              'devices': devices(), 'runtime_power': power, 'state': None}
    if power['status'] == 'active' and power['control'] == 'on':
        result['state'] = state()
    else:
        result['state_deferred'] = 'Hardware reads require an active master held on; initialize establishes that hold'
    return result


def save_run_result(directory, report):
    name = report['action'] + '-result.json'
    temporary = directory / f'.{name}.{os.getpid()}'
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(directory / name)


def configure_stereo(card, report):
    """Use discovered control IDs, including ALSA's DAPM name variants."""
    base = ['amixer', '-c', str(card)]
    result = subprocess.run(base + ['controls'], text=True, capture_output=True,
                            check=True, timeout=5)
    controls = {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"numid=(\d+),iface=MIXER,name='(.+)'", line)
        if match:
            controls.setdefault(match[2], []).append(match[1])
    settings = []
    for side in ('Left', 'Right'):
        for name, value in (('PA Volume', '0'), ('COMP Switch', '0'),
                            ('VISENSE Switch', '0'), ('BOOST Switch', '1'),
                            ('DAC Switch', '1')):
            settings.append((f'Spkr{side} {name}', value))
    settings += [('COMP7 Switch', '0'), ('COMP8 Switch', '0'),
                 ('RX7 Digital Volume', '84'), ('RX8 Digital Volume', '84'),
                 ('SLIM RX0 MUX', 'AIF1_PB'), ('SLIM RX1 MUX', 'AIF1_PB')]
    for chain, channel in ((7, 0), (8, 1)):
        for input_number in range(3):
            settings.append((f'RX INT{chain}_1 MIX1 INP{input_number}',
                             f'RX{channel}' if input_number == 0 else 'ZERO'))
    settings.append(('SLIMBUS_2_RX Audio Mixer MultiMedia1', '1'))
    report['mixer'] = []
    for name, value in settings:
        variants = [name]
        if name.endswith(' Switch'):
            variants.append(name.removesuffix(' Switch'))
        elif 'MIX1 INP' in name:
            variants.append(name + ' Mux')
        matches = [(n, ident) for n in variants for ident in controls.get(n, [])]
        need(len(matches) == 1, f'Expected one ALSA control for {name}, got {matches}')
        actual, ident = matches[0]
        result = subprocess.run(base + ['cset', 'numid=' + ident, value],
                                text=True, capture_output=True, timeout=5)
        report['mixer'].append({'name': actual, 'requested': value,
                                'returncode': result.returncode,
                                'readback': result.stdout.strip(),
                                'stderr': result.stderr.strip()})
        need(result.returncode == 0,
             f'Mixer {actual} failed ({result.returncode}): {result.stderr.strip()}')


def tone(channels, seconds=2, amplitude=1433):
    """48 kHz S16_LE stereo, <= -27 dBFS peak, 20 ms fades."""
    samples = bytearray()
    frames = int(seconds * 48000)
    for frame in range(frames):
        envelope = min(1, frame / 960, (frames - 1 - frame) / 960)
        values = [round(amplitude * envelope * math.sin(2 * math.pi * hz * frame / 48000))
                  if channel in channels else 0 for channel, hz in ((0, 440), (1, 660))]
        samples.extend(struct.pack('<hh', *values))
    return bytes(samples)


class OwnedPCM:
    """One fresh aplay, continuously fed silence unless a finite tone is queued."""

    def __init__(self, card):
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            ['aplay', '-D', f'hw:{card},0', '-t', 'raw', '-f', 'S16_LE',
             '-r', '48000', '-c', '2', '--period-size=2400', '--buffer-size=12000'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        self.status = Path(f'/proc/asound/card{card}/pcm0p/sub0/status')
        self.stop = threading.Event()
        self.pending = queue.Queue()
        self.error = None
        self.thread = threading.Thread(target=self.feed, daemon=True)
        self.thread.start()

    def feed(self):
        try:
            fd = self.process.stdin.fileno()
            while not self.stop.is_set():
                try:
                    data, done = self.pending.get_nowait()
                except queue.Empty:
                    data, done = bytes(2400 * 4), None
                remaining = memoryview(data)
                while remaining and not self.stop.is_set():
                    if not select.select([], [fd], [], 0.1)[1]:
                        continue
                    try:
                        count = os.write(fd, remaining[:9600])
                        remaining = remaining[count:]
                    except BlockingIOError:
                        continue
                if done is not None and not remaining:
                    done.set()
        except OSError as error:
            self.error = str(error)

    def healthy(self):
        need(self.error is None, f'PCM feeder failed: {self.error}')
        need(self.process.poll() is None, 'Owned PCM exited unexpectedly')
        status = read_text(self.status)
        need(re.search(r'^state:\s+RUNNING$', status, re.M) is not None,
             f'Owned PCM is not running: {status}')
        need(re.search(r'^owner_pid\s*:\s*' + str(self.process.pid) + r'$', status, re.M),
             'PCM ownership changed')
        return status

    def settle(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.healthy()
            time.sleep(0.05)

    def play(self, data):
        done = threading.Event()
        self.pending.put((data, done))
        deadline = time.monotonic() + len(data) / (48000 * 4) + 3
        while not done.wait(0.05):
            self.healthy()
            need(time.monotonic() < deadline, 'Timed out feeding finite playback')
        self.settle(0.6)  # Drain the 250 ms ALSA buffer and pipe into silence.

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
        self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.log.seek(0)
        log = self.log.read().decode(errors='replace')
        self.log.close()
        return log


def playback_state(path):
    return {key: int(value, 0) for key, value in
            (line.split('=', 1) for line in read_text(path / 'spx_playback_state').splitlines())}


def check_stereo(mapping, paths, initialized=False, observations=None):
    snapshot = state()
    codecs = {unit: playback_state(path) for unit, path in paths.items()}
    observation = {'master': snapshot, 'codec_shadows': codecs, 'passed': False}
    if observations is not None:
        observations.append(observation)
    need(identity_map(snapshot, devices(), {3, 4}) == mapping, 'Amplifier identity changed')
    need(snapshot['GPIO_VAL'] & 0x1e == 0x1e, 'Amplifier power state changed')
    need(snapshot['MCP_STATUS'] & 1 == 0 and snapshot['FRAME_B0'] == 7,
         'Unexpected runtime frame or active bank')
    for key, expected in (('DP1_B0', 0x01000107), ('DP4_B0', 0x01000607),
                          ('RX7_PATH_CFG0', 0), ('RX8_PATH_CFG0', 0),
                          ('RX7_VOLUME', 0), ('RX8_VOLUME', 0)):
        need(snapshot[key] == expected, f'{key}={snapshot[key]:#x}, expected {expected:#x}')
    for unit, codec in codecs.items():
        for key, expected in (('UNIT', unit), ('DEV_NUM', mapping[unit]), ('ATTACHED', 1),
                              ('STREAM_CONFIGURED', 1), ('STREAM_ENABLED', 1),
                              ('DAC_PREPARED', 1), ('DAC_MASTER_PORT', 1 if unit == 3 else 4),
                              ('SHADOW_PA_GAIN', 0xc9), ('SHADOW_COMP_ENABLE', 0),
                              ('SHADOW_VISENSE_ENABLE', 0)):
            need(codec[key] == expected, f'Unit {unit}: {key}={codec[key]}, expected {expected}')
        if initialized:
            need(codec['LATE_INIT_RESULT'] == 0 and codec['LATE_INIT_COUNT'] > 0,
                 f'Unit {unit}: late initialization did not complete')
            need(codec['SHADOW_PA_ENABLE'] & 0x80, f'Unit {unit}: PA enable absent from shadow')
            need(codec['SHADOW_OCP'] == 0xb4 and codec['SHADOW_BOOST'] == 0x98,
                 f'Unit {unit}: unexpected protection/boost shadow')
    observation['passed'] = True
    return observation


def listen(args, report, pcm_holder):
    need(args.allow_playback, 'listen requires --allow-playback for this requested run')
    mapping = report['stages'][-1]['physical_units_to_addresses']
    paths = {s['unit']: Path('/sys/bus/soundwire/devices') / s['name'] for s in devices()}
    need(set(paths) == {3, 4}, 'Need exactly the two native speakers')
    for path in paths.values():
        need((path / 'spx_late_init').exists() and (path / 'spx_playback_state').exists(),
             'Per-codec late initialization interface is missing')
    card = report['before']['internal_cards'][0]
    configure_stereo(card, report)
    assert_pcm_idle()
    pcm = OwnedPCM(card)
    pcm_holder.append(pcm)  # Outer cleanup parks amplifiers before closing PCM.
    report['pcm'] = {'pid': pcm.process.pid, 'card': card, 'format': 'S16_LE/48000/stereo'}
    deadline = time.monotonic() + 8
    while True:
        try:
            report['pcm']['running_status'] = pcm.healthy()
            break
        except RuntimeError:
            need(pcm.process.poll() is None and time.monotonic() < deadline,
                 'Fresh PCM did not start on silence')
            time.sleep(0.1)
    hw_params = read_text(pcm.status.with_name('hw_params'))
    for expression in (r'^format: S16_LE$', r'^channels: 2$', r'^rate: 48000(?: |$)'):
        need(re.search(expression, hw_params, re.M), 'Unexpected PCM hardware parameters')
    report['pcm']['hw_params'] = hw_params
    checks = report.setdefault('playback_checks', [])
    report['before_late_init'] = check_stereo(mapping, paths, observations=checks)
    for unit, path in paths.items():
        before = playback_state(path)['LATE_INIT_COUNT']
        (path / 'spx_late_init').write_text('1\n')
        need(playback_state(path)['LATE_INIT_COUNT'] == before + 1,
             f'Unit {unit}: late initialization did not advance')
    report['after_late_init'] = check_stereo(mapping, paths, initialized=True, observations=checks)
    pcm.settle(1.0)  # Conservative settling margin; minimum has not been measured.
    report['remaining_prerequisites'] = [UNMET[-1]]
    report['playback_ready'] = True
    report['tones'] = []
    for name, channels in (('left', {0}), ('right', {1}), ('both', {0, 1})):
        pcm.healthy()
        check_stereo(mapping, paths, initialized=True, observations=checks)
        print(f'Listening test: {name}, two seconds', flush=True)
        pcm.play(tone(channels))
        report['tones'].append({'channels': name, 'seconds': 2, 'peak_limit': 1433})
    report['after_playback'] = check_stereo(mapping, paths, initialized=True, observations=checks)
    report['human_result'] = 'pending; successful software checks do not establish audible output'


def initialize(args, report):
    need(os.geteuid() == 0, 'initialize requires root')
    need(args.action == 'recover' or args.allow_amp_power,
         'initialize/listen requires --allow-amp-power for this authorized run')
    need(args.action != 'listen' or args.allow_playback,
         'listen requires separate explicit --allow-playback authorization')
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
    writer, master = codec_paths()
    need(writer.exists(), 'WCD codec debugfs write_reg node is unavailable')
    control = master / 'power/control'
    saved_control = read_text(control)
    need(saved_control in ('auto', 'on'), 'Unknown master runtime PM policy')
    report['runtime_pm'] = {'master': str(master), 'saved_control': saved_control,
                            'restored': False}
    report['stages'] = []
    parked = None
    pcm_holder = []
    signals = {}

    def interrupted(signum, frame):
        raise InterruptedError(f'Interrupted by signal {signum}')

    # Signals arriving during cleanup must not bypass the park operation.
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signals[signum] = signal.signal(signum, interrupted)
    try:
        # Native runtime resume can restart the master/enumerator, but its GPIO
        # writes are gated by exact_windows_init or core_enum, both rejected above.
        control.write_text('on\n')
        deadline = time.monotonic() + 2
        while read_text(master / 'power/runtime_status') != 'active':
            need(time.monotonic() < deadline, 'SoundWire master did not resume')
            time.sleep(0.05)
        initial = inventory(master)
        report['before'] = initial
        need(initial['state'] is not None, 'SoundWire master is not held active')
        parked = initial['state']['GPIO_VAL'] & ~0x06
        need(len(initial['internal_cards']) == 1, 'Cannot identify one internal ALSA card')
        need(len(initial['devices']) == 2 and
             all(s['initialized'] is not None for s in initial['devices']),
             'Both native codecs must expose initialization status before amplifier power')
        need(initial['state']['GPIO_DIR'] & 0x1e == 0x1e and
             initial['state']['GPIO_VAL'] & 0x06 == 0,
             'Physical GPIO direction is wrong or an amplifier is already enabled')
        need(initial['state']['SLV_STATUS'] == 0, 'Amps must be detached before the test')
        if args.action != 'recover':
            need((initial['state']['FIFO_STATUS'] >> 8) & 0x1f == 0,
                 'SoundWire write FIFO is not empty; perform parked recovery before powering amps')
        if parked & 0x18 != 0x18:
            # Cold startup and master reload can clear auxiliary outputs 3/4.
            # Restore them with both amplifier enables (1/2) held low. Preserve
            # unrelated GPIO values and verify physical, page-safe readback.
            parked |= 0x18
            writer.write_text(f'43 {parked:02x}\n')
            report['startup_parked_state'] = state()
            need(report['startup_parked_state']['GPIO_VAL'] & 0x1e == 0x18 and
                 report['startup_parked_state']['SLV_STATUS'] == 0,
                 'Could not establish the auxiliary parked GPIO state')
        report['parked'] = True
        if args.action == 'recover':
            # The driver independently requires physical amps-off, no stream,
            # an active master and coherent readback. This never enables amps.
            try:
                (MODULES / 'soundwire_qcom/parameters/spx_audio_flush').write_text('1\n')
            finally:
                report['recovery_after'] = state()
            need(report['recovery_after']['FIFO_STATUS'] & 0x1f1f00 == 0,
                 'Command FIFO readback is not empty after parked recovery')
            report['fifo_recovered'] = True
            return
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
        report['remaining_prerequisites'].remove(UNMET[0])
        if args.action == 'listen':
            listen(args, report, pcm_holder)
    finally:
        for signum in signals:
            signal.signal(signum, signal.SIG_IGN)
        try:
            report['parked'] = False
            if parked is not None:
                writer.write_text(f'43 {parked:02x}\n')
                report['parked_state'] = state()
                need(report['parked_state']['GPIO_VAL'] & 0x1e == 0x18,
                     'Amplifier powerdown could not be confirmed')
                report['parked'] = True
            while pcm_holder:
                report['pcm']['log'] = pcm_holder.pop().close()
            if report['parked']:
                control.write_text(saved_control + '\n')
                need(read_text(control) == saved_control, 'Master runtime PM policy was not restored')
                report['runtime_pm']['restored'] = True
        finally:
            while pcm_holder:
                report['pcm']['log'] = pcm_holder.pop().close()
            for signum, handler in signals.items():
                signal.signal(signum, handler)
    if 'pcm' in report:
        need(not re.search(r'underrun|overrun|error', report['pcm']['log'], re.I),
             'ALSA reported an underrun or playback error; inspect the PCM log')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('plan', 'inspect', 'initialize', 'listen', 'recover'), default='plan')
    parser.add_argument('--output', type=Path, help='directory for result JSON')
    parser.add_argument('--owner', help='coordinator device-lock owner (initialize)')
    parser.add_argument('--desktop-user', help='user whose audio units the caller has paused')
    parser.add_argument('--allow-amp-power', action='store_true',
                        help='explicitly authorize this bounded initialization run')
    parser.add_argument('--allow-playback', action='store_true',
                        help='explicitly authorize this one bounded listening run')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    report = {'action': args.action, 'utc': stamp, 'playback_ready': False,
              'microphone_capture': False, 'success': False, 'parked': False,
              'remaining_prerequisites': list(UNMET)}
    result = 0
    try:
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            if args.action in ('initialize', 'listen', 'recover'):
                # A killed run must never leave an earlier "parked" verdict.
                save_run_result(args.output, report)
        if args.action == 'plan':
            report['initialization'] = (
                'Pause desktop audio services/sockets. Hold the discovered native '
                'SoundWire master active. Require parked GPIO 0x1e/0x18 '
                'and no playback PCM. Power pin1 and require native unit3, then power '
                'pin2 and require both native units3/4 at distinct addresses1/2. '
                'Allow five seconds per stage and require two agreeing samples. '
                'Attempt to park both amps, verify physical GPIO readback and only '
                'then restore the saved runtime PM policy. '
                'No PCM, tone, microphone capture, or amplifier gain/protection changes.')
            report['listening'] = (
                'Separate authorization required. After native enumeration, route RX0/1 '
                'to physical left/right speakers at minimum PA gain and 0 dB WCD gain, '
                'with companders off. Open one fresh 48 kHz stereo PCM on silence. '
                'Require frame7/bank0, DP1/4 offsets1/6, then late-initialize each codec. '
                'Verify shadows and settle on silence for one second. Play two seconds '
                'left, right, then both (peak <=1433/32768); return to silence and park '
                'both amplifiers before closing PCM. No microphone capture.')
            report['recovery'] = (
                'With amplifiers already off, desktop audio stopped and all PCM closed, '
                'hold the master active and invoke the driver-owned guarded FIFO flush '
                'once. Require empty read/write counts, confirm parked GPIO and restore '
                'runtime PM. This does not power amplifiers or open a PCM.')
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
        if args.action in ('initialize', 'listen', 'recover'):
            save_run_result(args.output, report)
    print(text, end='')
    return result


if __name__ == '__main__':
    sys.exit(main())
