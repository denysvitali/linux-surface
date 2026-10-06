#!/usr/bin/env python3
"""Prepare, inspect and explicitly test native SPX speaker audio.

Default: print an offline plan. ``initialize`` powers the amps sequentially,
allows five seconds of polling per stage, checks hardware identities against
the native SoundWire devices, and attempts to park both amps on every exit
after power-up. ``listen`` additionally requires explicit playback permission;
it owns one fresh PCM, checks stereo routing and late initialization on digital
silence, then plays a bounded left/right/both sequence at minimum PA gain.
``recover`` flushes only the command FIFO, requiring amps already off and no
streams. ``feedback`` records the internal microphone across quiet and finite
speaker tones, and scores each channel. ``capture`` checks the microphone with
the amplifiers parked. ``desktop`` checks finite applications through a temporary
public PipeWire sink and verifies attached-amplifier PCM teardown. ``serve`` first
runs that acoustic test, closes the microphone, then retains the same PCM for
ordinary applications at minimum PA gain. ``--desktop-peak`` selects their fixed
attenuation (default 1433/32768, at most 12000/32768). ``desktop-mic`` tests
two bounded default recording clients over one retained capture/playback pair; it provides no persistent microphone service.
``reopen`` tests two Linux playback PCMs with one continuous microphone capture
and attached-amp teardown between them; ASM stays parked. None loads modules.
"""

import argparse
from array import array
from datetime import datetime, timezone
import errno
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
import wave


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
                 # WCD survives a machine-card reload with cached mux values,
                 # but the new DAPM routes start disconnected. Its mux put
                 # returns early for an unchanged value. Reselect while idle.
                 ('SLIM RX0 MUX', 'ZERO'), ('SLIM RX1 MUX', 'ZERO'),
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


def validate_microphone_source(action, source):
    need(source in ('DMIC0', 'DMIC1'), 'Unknown microphone source')
    need(source == 'DMIC1' or action in ('capture', 'feedback', 'desktop-mic'),
         'DMIC0 is only supported for capture or feedback or desktop-mic')


def configure_microphone(card, report, saved, source='DMIC1'):
    """Select one DMIC -> DEC0 -> MM2 route before capture; preserve controls."""
    need(source in ('DMIC0', 'DMIC1'), 'Unknown microphone source')
    need(parameter('q6asm_dai', 'spx_keep_asm') == 'Y',
         'Capture requires the known parked ASM lifetime workaround')
    for path in Path('/proc/asound').glob('card*/pcm*c/sub*/status'):
        need(read_text(path) == 'closed', f'Capture already open: {path}')
    base = ['amixer', '-c', str(card)]
    report['microphone_mixer'] = []
    for name, value in (
            ('MultiMedia2 Mixer SLIMBUS_0_TX', '1'),
            ('AIF1_CAP Mixer SLIM TX0', '1'), ('CDC_IF TX0 MUX', 'DEC0'),
            ('DEC0 Volume', '84'), ('ADC MUX0', 'DMIC'), ('DMIC MUX0', source)):
        key = 'name=' + name
        before = subprocess.run(base + ['cget', key], capture_output=True,
                                text=True, check=True, timeout=5)
        match = re.search(r'^\s*: values=(.+)$', before.stdout, re.M)
        need(match is not None, f'Cannot preserve microphone control {name}')
        saved.append((base + ['cset', key, match[1]], name))
        result = subprocess.run(base + ['cset', key, value], capture_output=True,
                                text=True, timeout=5)
        report['microphone_mixer'].append({'name': name, 'requested': value,
            'returncode': result.returncode, 'readback': result.stdout,
            'stderr': result.stderr})
        need(result.returncode == 0, f'Microphone route {name}: {result.stderr}')
        if name == 'DMIC MUX0':
            item = re.search(r"^\s*; Item #(\d+) '" + source + r"'$", result.stdout, re.M)
            selected = re.search(r'^\s*: values=(\d+)$', result.stdout, re.M)
            need(item and selected and item[1] == selected[1],
                 f'Microphone source readback did not select {source}')
            report['microphone_mixer'][-1]['selected'] = source
            report['microphone_source'] = source


class OwnedCapture:
    """One finite MM2 capture, consumed continuously without XRUN recovery."""

    def __init__(self, card, report, directory, maximum_seconds=90, retain_recording=True):
        self.maximum_seconds = maximum_seconds
        self.retain_recording = retain_recording
        source = report['microphone_source']
        need(source in ('DMIC0', 'DMIC1'), 'Capture requires a verified microphone source')
        self.report = report
        self.directory = directory
        self.raw = bytearray()
        self.mutex = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        self.limit = None
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            ['arecord', '--fatal-errors', '-q', '-D', f'plughw:{card},1',
             '-t', 'raw', '-f', 'S16_LE', '-r', '48000', '-c', '1',
             '--period-size=1920', '--buffer-size=7680', '-d', str(maximum_seconds)],
            stdout=subprocess.PIPE, stderr=self.log, bufsize=0)
        self.status = Path(f'/proc/asound/card{card}/pcm1c/sub0/status')
        report['microphone_capture'] = True
        report['capture'] = {'pid': self.process.pid, 'device': f'plughw:{card},1',
                             'source': source, 'rate': 48000, 'channels': 1,
                             'period_frames': 1920, 'buffer_frames': 7680,
                             'maximum_seconds': maximum_seconds, 'phases': []}
        self.thread = threading.Thread(target=self.consume, daemon=True)
        self.thread.start()

    def consume(self):
        last = time.monotonic()
        monitor = bytearray()
        try:
            while not self.stop.is_set():
                if not select.select([self.process.stdout], [], [], 0.2)[0]:
                    need(time.monotonic() - last < 8, 'Microphone data stalled')
                    continue
                block = os.read(self.process.stdout.fileno(), 16384)
                need(bool(block), 'Microphone stream ended unexpectedly')
                last = time.monotonic()
                with self.mutex:
                    self.raw.extend(block)
                    need(len(self.raw) <= getattr(self, 'maximum_seconds', 90) * 48000 * 2, 'Capture duration limit exceeded')
                monitor.extend(block)
                while len(monitor) >= 9600:
                    samples = array('h', monitor[:9600])
                    del monitor[:9600]
                    peak = max(abs(v) for v in samples)
                    rms = math.sqrt(sum(v*v for v in samples) / len(samples))
                    need(peak < 32000, 'Microphone clipping: automatic abort')
                    if self.limit is not None:
                        need(rms <= self.limit, 'Microphone noise/level limit exceeded')
        except (OSError, RuntimeError) as error:
            if not self.stop.is_set():
                self.error = str(error)
                # Interrupt mixer waits as well as the playback loop. The main
                # thread's existing signal handler performs amplifier parking.
                os.kill(os.getpid(), signal.SIGTERM)

    def mark(self):
        self.healthy()
        with self.mutex:
            return len(self.raw) // 2

    def samples(self, start=0, end=None):
        with self.mutex:
            data = bytes(self.raw[start * 2:None if end is None else end * 2])
        return array('h', data[:len(data) // 2 * 2])

    def healthy(self):
        need(self.error is None, self.error or 'Capture failed')
        need(self.process.poll() is None, 'Capture process exited')

    def wait_frames(self, frames):
        deadline = time.monotonic() + frames / 48000 + 8
        while True:
            self.healthy()
            with self.mutex:
                if len(self.raw) >= frames * 2:
                    return
            need(time.monotonic() < deadline, 'Capture did not deliver requested frames')
            time.sleep(0.05)

    def baseline(self):
        self.wait_frames(3 * 48000)
        samples = self.samples(48000, 3 * 48000)
        need(sum(v != 0 for v in samples) > len(samples) // 100,
             'Microphone returned silence; cannot use it as acoustic feedback')
        rms = math.sqrt(sum(v*v for v in samples) / len(samples))
        need(rms < 1000, 'Ambient level too high for bounded speaker test')
        self.limit = max(300, rms * 12)
        status = read_text(self.status)
        need(re.search(r'^state:\s+RUNNING$', status, re.M), 'Capture PCM is not RUNNING')
        need(re.search(r'^owner_pid\s*:\s*' + str(self.process.pid) + r'$', status, re.M),
             'Capture ownership changed')
        hw_params = read_text(self.status.with_name('hw_params'))
        for expression in (r'^format: S16_LE$', r'^channels: 1$',
                           r'^rate: 48000(?: |$)', r'^period_size: 1920$',
                           r'^buffer_size: 7680$'):
            need(re.search(expression, hw_params, re.M), 'Capture geometry changed')
        self.report['capture']['hw_params'] = hw_params
        self.report['capture']['baseline'] = {'start_frame': 48000, 'end_frame': 144000,
            'rms': rms, 'peak': max(abs(v) for v in samples),
            'abort_rms': self.limit, 'status': status}
        return samples

    def close(self):
        self.stop.set()
        self.report['capture']['stop_requested'] = self.process.poll() is None
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.thread.join(timeout=2)
        self.process.stdout.close()
        self.log.seek(0)
        self.report['capture']['log'] = self.log.read().decode(errors='replace')
        self.log.close()
        self.report['capture']['error'] = self.error
        self.report['capture']['returncode'] = self.process.returncode
        samples = self.samples()
        self.report['capture']['frames'] = len(samples)
        if getattr(self, 'retain_recording', True):
            path = self.directory / 'microphone.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                output.writeframes(samples.tobytes())
            self.report['capture']['recording'] = str(path)
        else:
            self.report['capture']['recording'] = None
            self.report['capture']['closed_status'] = read_text(self.status)
            self.report['capture']['clean_dsp_teardown_verified'] = False
            with self.mutex:
                self.raw.clear()


class OwnedPCM:
    """One fresh aplay, continuously fed silence unless a finite tone is queued."""

    def __init__(self, card):
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            ['aplay', '--fatal-errors', '-D', f'hw:{card},0', '-t', 'raw', '-f', 'S16_LE',
             '-r', '48000', '-c', '2', '--period-size=2400', '--buffer-size=12000'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        self.status = Path(f'/proc/asound/card{card}/pcm0p/sub0/status')
        self.stop = threading.Event()
        self.pending = queue.Queue()
        self.error = None
        self.source = None
        self.source_lock = threading.Lock()
        self.feed_stats = {'inserted_gap_events': 0, 'inserted_gap_frames': 0}
        self.thread = threading.Thread(target=self.feed, daemon=True)
        self.thread.start()

    def feed(self):
        try:
            fd = self.process.stdin.fileno()
            while not self.stop.is_set():
                try:
                    data, done = self.pending.get_nowait()
                except queue.Empty:
                    with self.source_lock:
                        source = self.source
                        if source is None:
                            data, done = bytes(2400 * 4), None
                        else:
                            source.healthy()
                            try:
                                # Preserve every queued frame even across an
                                # active-to-idle transition.
                                data, done = source.blocks.get_nowait(), None
                            except queue.Empty:
                                if not source.forward:
                                    data, done = bytes(2400 * 4), None
                                else:
                                    try:
                                        data, done = source.blocks.get(timeout=0.1), None
                                    except queue.Empty:
                                        source.healthy()
                                        # The 250 ms PCM ring absorbs normal
                                        # monitor delivery bursts. Inserting
                                        # silence here changes active waveform
                                        # timing and shifts its spectrum. Real
                                        # source failure/XRUN must still abort.
                                        continue
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
        except (OSError, RuntimeError) as error:
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

    def set_source(self, source):
        # Wait until no feeder iteration can still inspect the old process.
        with self.source_lock:
            self.source = source

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


class DesktopMonitor:
    """Frame-aligned, level-checked monitor data; never amplify or reopen PCM."""

    def __init__(self, process, ordinary=False, desktop_peak=1433):
        need(isinstance(desktop_peak, int) and 1433 <= desktop_peak <= 12000,
             'Desktop peak must be between 1433 and 12000')
        need(ordinary or desktop_peak == 1433,
             'Only the ordinary desktop path may change its peak limit')
        self.process = process
        self.blocks = queue.Queue(maxsize=40)  # At most 200 ms, never unbounded.
        self.stop = threading.Event()
        self.error = None
        self.ordinary = ordinary
        self.peak_limit = desktop_peak
        self.forward = ordinary
        self.peak = 0
        self.input_peak = 0
        self.max_interarrival_seconds = 0.0
        self.thread = threading.Thread(target=self.consume, daemon=True)
        self.closed = False

    def consume(self):
        pending = bytearray()
        last = time.monotonic()
        try:
            while not self.stop.is_set():
                if not select.select([self.process.stdout], [], [], 0.1)[0]:
                    need(time.monotonic() - last < 2, 'Desktop monitor stalled')
                    continue
                block = os.read(self.process.stdout.fileno(), 4096)
                need(block, 'Desktop monitor ended')
                now = time.monotonic()
                self.max_interarrival_seconds = max(self.max_interarrival_seconds, now - last)
                last = now
                pending.extend(block)
                while len(pending) >= 960 and not self.stop.is_set():
                    frame = bytes(pending[:960])
                    del pending[:960]
                    peak = max(abs(v[0]) for v in struct.iter_unpack('<h', frame))
                    self.input_peak = max(self.input_peak, peak)
                    if self.ordinary:
                        # Fixed attenuation preserves channels and dynamics.
                        # Even -32768 stays within the selected limit; full-scale audio
                        # is allowed without exposing the legacy 44x gain.
                        frame = struct.pack('<480h', *(int(value * self.peak_limit / 32768)
                            for value, in struct.iter_unpack('<h', frame)))
                        peak = max(abs(v[0]) for v in struct.iter_unpack('<h', frame))
                    self.peak = max(self.peak, peak)
                    need(peak <= self.peak_limit,
                         f'Desktop monitor exceeds peak limit {self.peak_limit}')
                    need(self.forward or peak <= 1, 'Unexpected desktop audio outside owned playback')
                    # Idle/scoring must not make ALSA follow PipeWire's clock.
                    # Consume the monitor continuously, but let OwnedPCM supply
                    # silence using ALSA backpressure instead of queuing it here.
                    if not self.forward:
                        continue
                    try:
                        self.blocks.put(frame, timeout=0.5)
                    except queue.Full:
                        raise RuntimeError('Desktop PCM forwarding stalled')
        except (OSError, RuntimeError) as error:
            if not self.stop.is_set():
                self.error = str(error)
                os.kill(os.getpid(), signal.SIGTERM)

    def healthy(self):
        need(self.error is None, self.error or 'Desktop monitor failed')
        need(self.process.poll() is None, 'Desktop monitor process exited')

    def close(self):
        if self.closed:
            return
        self.stop.set()
        stop_desktop_process(self.process)
        self.thread.join(timeout=1)
        self.process.stdout.close()
        self.closed = True


def stop_desktop_process(process):
    """Each desktop child owns a session, including its runuser child."""
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


class DesktopGraph:
    """Temporarily allow only the desktop graph; retain every legacy guard."""

    units = UNITS[:5]

    def __init__(self, username, report):
        self.account = pwd.getpwnam(username)
        runtime = Path('/run/user') / str(self.account.pw_uid)
        self.runtime = runtime
        self.command = ['runuser', '-u', username, '--', 'env',
                        f'XDG_RUNTIME_DIR={runtime}',
                        f'DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus',
                        f'PULSE_SERVER=unix:{runtime}/pulse/native']
        self.overrides = []
        self.directories = []
        self.processes = []
        self.module = None
        self.monitor = None
        self.microphone = None
        self.started = False
        self.report = report
        self.sink = f'spx_desktop_test_{os.getpid()}'
        self.public_restore = []

    def run(self, *command):
        return subprocess.run(self.command + list(command), check=True,
                              capture_output=True, text=True, timeout=5).stdout.strip()

    def start(self):
        # Preserve the existing policy which prevents hardware ALSA probing.
        policy = read_text('/etc/wireplumber/wireplumber.conf.d/51-spx-disable-alsa-monitor.conf')
        need(re.search(r'hardware\.audio\s*=\s*disabled', policy),
             'WirePlumber hardware probing must remain disabled')
        for unit in self.units:
            directory = self.runtime / 'systemd/user' / (unit + '.d')
            for parent in reversed([directory, *directory.parents]):
                if parent.is_relative_to(self.runtime) and not parent.exists():
                    parent.mkdir()
                    os.chown(parent, self.account.pw_uid, self.account.pw_gid)
                    self.directories.append(parent)
            path = directory / f'zz-spx-desktop-{os.getpid()}.conf'
            # Never overwrite an existing user's override.
            with path.open('x') as output:
                self.overrides.append(path)
                output.write('[Unit]\nConditionKernelCommandLine=\n')
            os.chown(path, self.account.pw_uid, self.account.pw_gid)
        self.run('systemctl', '--user', 'daemon-reload')
        self.started = True  # A partial start also requires stopping all five.
        self.run('systemctl', '--user', 'start', *self.units)
        active = self.run('systemctl', '--user', 'show', '--property=ActiveState',
                          '--value', '--', *UNITS[5:]).split()
        need(len(active) == len(UNITS[5:]) and
             all(value in ('inactive', 'failed') for value in active),
             'Legacy audio owner unexpectedly started')
        sinks = json.loads(self.run('pactl', '--format=json', 'list', 'sinks'))
        need(all(not any(key.startswith(('alsa.', 'api.alsa.'))
                         for key in s.get('properties', {})) for s in sinks),
             'PipeWire exposed an ALSA hardware sink')
        default_sink = self.run('pactl', 'get-default-sink')
        if getattr(self, 'preserve_default_source', False):
            self.default_source_before_test = self.run('pactl', 'get-default-source')
        # This is a real public Pulse sink, but never the default. Other
        # desktop applications remain routed to their existing sink.
        self.module = self.run('pactl', 'load-module', 'module-null-sink',
                               f'sink_name={self.sink}', 'rate=48000', 'channels=2',
                               'channel_map=front-left,front-right',
                               'sink_properties=priority.session=0')
        need(self.module.isdigit(), 'Pulse did not return an owned module ID')
        need(self.run('pactl', 'get-default-sink') == default_sink,
             'Test sink unexpectedly became the desktop default')
        self.run('pactl', 'set-sink-volume', self.sink, '65536')
        self.run('pactl', 'set-sink-mute', self.sink, '0')
        self.run('pactl', 'set-source-volume', self.sink + '.monitor', '65536')
        self.run('pactl', 'set-source-mute', self.sink + '.monitor', '0')
        process = subprocess.Popen(self.command + [
            'parec', '--raw', '--device=' + self.sink + '.monitor',
            '--format=s16le', '--rate=48000', '--channels=2',
            '--latency-msec=5', '--process-time-msec=5'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            start_new_session=True)
        self.monitor = DesktopMonitor(process)
        self.monitor.thread.start()
        self.report.update(sink=self.sink, default_sink_changed=False,
                           gain=1, peak_limit=1433)

    def play(self, data, name):
        self.monitor.healthy()
        self.monitor.forward = True
        process = subprocess.Popen(self.command + [
            'pacat', '--playback', '--raw', '--device=' + self.sink,
            '--format=s16le', '--rate=48000', '--channels=2',
            '--channel-map=front-left,front-right', '--volume=65536',
            '--latency-msec=20', '--process-time-msec=5',
            '--client-name=spx-desktop-' + name], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        self.processes.append(process)
        _, error = process.communicate(data, timeout=6)
        entry = {'name': name, 'pid': process.pid, 'exit_code': process.returncode,
                 'stderr': error.decode(errors='replace')}
        self.report['applications'].append(entry)
        need(process.returncode == 0, f'Desktop application failed: {entry}')

    def connect_public(self, pcm, desktop_peak=1433):
        """Transfer the already initialized PCM to the existing desktop sink."""
        need(self.monitor is None, 'Acoustic monitor must be detached before handoff')
        sinks = json.loads(self.run('pactl', '--format=json', 'list', 'sinks'))
        sources = json.loads(self.run('pactl', '--format=json', 'list', 'sources'))
        sink = next((item for item in sinks if item['name'] == 'spx_speakers'), None)
        source = next((item for item in sources if item['name'] == 'spx_speakers.monitor'), None)
        need(sink is not None and source is not None, 'Existing spx_speakers sink/monitor missing')
        need(not any(key.startswith(('alsa.', 'api.alsa.'))
                     for key in sink.get('properties', {})), 'Public sink must remain virtual')
        self.public_restore.append(('pactl', 'set-default-sink',
                                    self.run('pactl', 'get-default-sink')))
        for kind, item in (('sink', sink), ('source', source)):
            volumes = item['volume']
            need(set(volumes) == {'front-left', 'front-right'}, 'Public endpoint must be stereo')
            self.public_restore.extend([
                ('pactl', f'set-{kind}-volume', item['name'],
                 str(volumes['front-left']['value']), str(volumes['front-right']['value'])),
                ('pactl', f'set-{kind}-mute', item['name'], str(int(item['mute'])))])
            self.run('pactl', f'set-{kind}-volume', item['name'], '65536')
            self.run('pactl', f'set-{kind}-mute', item['name'], '0')
        self.run('pactl', 'set-default-sink', 'spx_speakers')
        self.sink = 'spx_speakers'
        self.public_sink_id = sink['index']
        process = subprocess.Popen(self.command + [
            'parec', '--raw', '--device=spx_speakers.monitor', '--format=s16le',
            '--rate=48000', '--channels=2', '--latency-msec=5', '--process-time-msec=5'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            start_new_session=True)
        self.monitor = DesktopMonitor(process, ordinary=True, desktop_peak=desktop_peak)
        self.monitor.thread.start()
        pcm.set_source(self.monitor)
        self.report['ordinary_sink'] = 'spx_speakers'

    def require_public_idle(self):
        inputs = json.loads(self.run('pactl', '--format=json', 'list', 'sink-inputs'))
        need(not any(str(item['sink']) == str(self.public_sink_id) and
                     not item.get('corked', False) for item in inputs),
             'An ordinary application is active during public acoustic verification')

    def close(self):
        errors = []

        def attempt(function, *args):
            try:
                function(*args)
            except Exception as error:
                errors.append(type(error).__name__ + ': ' + str(error))

        for recording in getattr(self, 'recordings', []):
            attempt(recording.close)
        if getattr(self, 'microphone', None) is not None:
            attempt(self.microphone.close)
            self.microphone = None
        for process in self.processes:
            attempt(stop_desktop_process, process)
        if self.monitor:
            self.report['monitor_peak'] = self.monitor.peak
            self.report['monitor_error'] = self.monitor.error
            self.report['monitor_max_interarrival_seconds'] = self.monitor.max_interarrival_seconds
            attempt(self.monitor.close)
            self.monitor = None
        for command in reversed(getattr(self, 'public_restore', [])):
            attempt(self.run, *command)
        self.public_restore = []
        if self.module is not None:
            attempt(self.run, 'pactl', 'unload-module', self.module)
            self.module = None
        if self.started:
            attempt(self.run, 'systemctl', '--user', 'stop', *self.units)
        for path in self.overrides:
            attempt(path.unlink)
        self.overrides.clear()
        for directory in reversed(self.directories):
            try:
                directory.rmdir()
            except OSError as error:
                if error.errno not in (errno.ENOTEMPTY, errno.ENOENT):
                    errors.append(str(error))
        self.directories.clear()
        attempt(self.run, 'systemctl', '--user', 'daemon-reload')
        self.report['graph_restored'] = not errors
        need(not errors, 'Desktop graph cleanup failed: ' + '; '.join(errors))


def check_desktop_teardown(paths, report):
    evidence = report['teardown'] = {'passed': False, 'samples': []}
    deadline = time.monotonic() + 5
    while True:
        snapshot = state()
        codecs = {unit: playback_state(path) for unit, path in paths.items()}
        evidence['samples'].append({'master': snapshot, 'codecs': codecs})
        stopped = all(not c['STREAM_CONFIGURED'] and not c['STREAM_ENABLED'] and
                      not c['DAC_PREPARED'] and not c['SHADOW_PA_ENABLE'] & 0x80
                      for c in codecs.values())
        ports_off = all(snapshot[f'DP{port}_B{bank}'] & 0xff000000 == 0
                        for port in (1, 4) for bank in (0, 1))
        if stopped and ports_off and snapshot['FIFO_STATUS'] & 0x1f1f00 == 0:
            assert_pcm_idle()
            need(snapshot['SLV_STATUS'] == 0x14 and snapshot['GPIO_VAL'] & 0x1e == 0x1e,
                 'Amplifiers detached before desktop teardown finished')
            evidence['passed'] = True
            return
        need(time.monotonic() < deadline, 'Desktop PCM did not close cleanly while amps attached')
        time.sleep(0.1)


class DesktopMicSource:
    """Owned default source for one finite retained hardware capture."""

    def __init__(self, graph, capture, report, previous_default=None):
        self.graph, self.capture, self.report = graph, capture, report
        self.module = self.previous = self.directory = self.fifo = self.fd = None
        self.stop = threading.Event()
        self.forward = False
        self.error = None
        self.thread = None
        self.name = f'spx_microphone_test_{os.getpid()}'
        self.previous = previous_default

    def start(self):
        if self.previous is None:
            self.previous = self.graph.run('pactl', 'get-default-source')
        self.directory = Path(tempfile.mkdtemp(prefix='spx-mic-', dir=self.graph.runtime))
        account = self.graph.account
        os.chown(self.directory, account.pw_uid, account.pw_gid)
        self.fifo = self.directory / 'capture'
        os.mkfifo(self.fifo, 0o600)
        os.chown(self.fifo, account.pw_uid, account.pw_gid)
        self.module = self.graph.run('pactl', 'load-module', 'module-pipe-source',
            'file=' + str(self.fifo), 'source_name=' + self.name,
            'format=s16le', 'rate=48000', 'channels=1', 'channel_map=mono')
        need(self.module.isdigit(), 'Pipe source did not return an owned module ID')
        sources = json.loads(self.graph.run('pactl', '--format=json', 'list', 'sources'))
        source = next((s for s in sources if s['name'] == self.name), None)
        need(source is not None and source.get('monitor_of_sink') in (None, 'n/a', 4294967295),
             'Owned microphone source missing or is a sink monitor')
        self.source_id = source['index']
        self.graph.run('pactl', 'set-source-volume', self.name, '65536')
        self.graph.run('pactl', 'set-source-mute', self.name, '0')
        self.graph.run('pactl', 'set-default-source', self.name)
        need(self.graph.run('pactl', 'get-default-source') == self.name,
             'Default source did not select the fitted microphone adapter')
        # The module owns the reader. Do not hold a fake reader which could
        # hide module failure; do not block the main thread waiting for it.
        deadline = time.monotonic() + 3
        while self.fd is None:
            try:
                self.fd = os.open(self.fifo, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno != errno.ENXIO or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        fcntl.fcntl(self.fd, fcntl.F_SETPIPE_SZ, 4096)
        self.report.update(source=self.name, source_index=self.source_id,
                           previous_default=self.previous, format='S16_LE/48000/mono')
        self.thread = threading.Thread(target=self.feed, daemon=True)
        self.thread.start()

    def feed(self):
        try:
            cursor = self.capture.mark()
            while not self.stop.wait(0.01):
                end = self.capture.mark()
                if not self.forward:
                    cursor = end  # Never replay idle/private audio to a new client.
                    continue
                need(end - cursor <= 48000, 'Microphone FIFO adapter fell behind')
                if end == cursor:
                    continue
                data = self.capture.samples(cursor, end).tobytes()
                cursor = end
                deadline = time.monotonic() + 1
                while data and self.forward and not self.stop.is_set():
                    if not select.select([], [self.fd], [], 0.1)[1]:
                        need(time.monotonic() < deadline, 'Desktop microphone FIFO stalled')
                        continue
                    try:
                        count = os.write(self.fd, data[:4096])
                    except BlockingIOError:
                        continue
                    need(count > 0, 'Desktop microphone FIFO stopped')
                    data = data[count:]
                    deadline = time.monotonic() + 1
        except (OSError, RuntimeError) as error:
            if not self.stop.is_set():
                self.error = str(error)
                os.kill(os.getpid(), signal.SIGTERM)

    def healthy(self):
        self.capture.healthy()
        need(self.error is None, self.error or 'Microphone FIFO adapter failed')

    def require_client_route(self, name):
        need(self.graph.run('pactl', 'get-default-source') == self.name,
             'Desktop default microphone changed')
        outputs = json.loads(self.graph.run('pactl', '--format=json', 'list', 'source-outputs'))
        matches = [s for s in outputs if s.get('properties', {}).get('application.name') == name]
        if not matches:
            return False
        need(len(matches) == 1 and str(matches[0]['source']) == str(self.source_id),
             'Default recording client selected another source')
        self.report.setdefault('routes', []).append(dict(client=name, source=matches[0]['source'],
                                                         source_output=matches[0]['index']))
        return True

    def close(self):
        self.forward = False
        self.stop.set()
        errors = []
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                errors.append('Microphone FIFO thread did not stop')
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # Restoration failure must not prevent unloading our source/FIFO.
        for command in ([('pactl', 'set-default-source', self.previous)] if self.previous else []) + \
                       ([('pactl', 'unload-module', self.module)] if self.module else []):
            try:
                self.graph.run(*command)
                if command[1] == 'set-default-source':
                    need(self.graph.run('pactl', 'get-default-source') == self.previous,
                         'Original default microphone was not restored')
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        if self.fifo:
            self.fifo.unlink(missing_ok=True)
        if self.directory:
            self.directory.rmdir()
        self.module = self.previous = self.directory = self.fifo = None
        self.report.update(restored=not errors, adapter_error=self.error, cleanup_errors=errors)
        need(not errors, 'Desktop microphone cleanup failed: ' + '; '.join(errors))


class DesktopRecording(OwnedCapture):
    """Ordinary default-source client; no device selection or ALSA ownership."""

    def __init__(self, graph, name):
        self.maximum_seconds = 60
        self.raw = bytearray()
        self.mutex = threading.Lock()
        self.stop = threading.Event()
        self.error = self.limit = None
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen(graph.command + [
            'parec', '--raw', '--format=s16le', '--rate=48000', '--channels=1',
            '--latency-msec=20', '--process-time-msec=10', '--client-name=' + name],
            stdout=subprocess.PIPE, stderr=self.log, bufsize=0, start_new_session=True)
        graph.processes.append(self.process)
        if not hasattr(graph, 'recordings'):
            graph.recordings = []
        graph.recordings.append(self)
        self.thread = threading.Thread(target=self.consume, daemon=True)
        self.thread.start()

    def close(self):
        if self.log.closed:
            return
        self.stop.set()
        stop_desktop_process(self.process)
        self.thread.join(timeout=2)
        self.process.stdout.close()
        self.log.seek(0)
        log = self.log.read().decode(errors='replace')
        self.log.close()
        with self.mutex:
            self.raw.clear()
        need(not self.thread.is_alive() and not self.error,
             self.error or 'Desktop recording thread did not stop')
        need(not re.search(r'error|overrun|underrun', log, re.I),
             'Desktop recording client reported an error: ' + log)


def desktop_microphone(args, report, pcm, paths, mapping, capture, holders):
    """Two default desktop clients over one retained capture/playback pair."""
    from acoustic import score_phase

    evidence = report['desktop'] = {'microphone_client_passed': False,
        'maximum_seconds': 60, 'clients': [], 'scope': 'default client path only'}
    graph = DesktopGraph(args.desktop_user, evidence)
    holders.append(graph)
    started = time.monotonic()
    def expire():
        evidence['deadline_expired'] = True
        os.kill(os.getpid(), signal.SIGTERM)

    evidence['deadline_expired'] = False
    timer = threading.Timer(60, expire)
    timer.start()
    try:
        graph.preserve_default_source = True
        graph.start()
        source = graph.microphone = DesktopMicSource(
            graph, capture, evidence, graph.default_source_before_test)
        source.start()
        owners = {'capture': read_text(capture.status), 'playback': pcm.healthy()}
        evidence['hardware_owners_before'] = owners
        for index in range(2):
            name = f'spx-default-microphone-{os.getpid()}-{index}'
            client = DesktopRecording(graph, name)
            entry = {'name': name, 'pid': client.process.pid, 'passed': False}
            evidence['clients'].append(entry)
            try:
                deadline = time.monotonic() + 5
                while not source.require_client_route(name):
                    client.healthy()
                    source.healthy()
                    need(time.monotonic() < deadline, 'Default microphone client did not attach')
                    time.sleep(0.05)
                source.forward = True
                # Discard startup/pipe latency, then fix a contiguous reference.
                client.wait_frames(3 * 48000)
                end = client.mark()
                reference = client.samples(end - 2 * 48000, end)
                source.healthy()
                check_stereo(mapping, paths, initialized=True)
                begin = client.mark()
                pcm.play(tone({0, 1}))  # Exactly the quiet1433/minimum-PA recipe.
                client.wait_frames(begin + 3 * 48000)
                end = client.mark()
                entry.update(start_frame=begin, end_frame=end,
                             score=score_phase(client.samples(begin, end), reference, [440, 660]))
                need(entry['score']['passed'], 'Default microphone acoustic test failed: ' +
                     entry['score']['reason'])
                for kind, current in (('capture', read_text(capture.status)),
                                      ('playback', pcm.healthy())):
                    for field in ('owner_pid', 'trigger_time'):
                        before = re.search(r'^' + field + r'\s*:\s*(.+)$', owners[kind], re.M)
                        after = re.search(r'^' + field + r'\s*:\s*(.+)$', current, re.M)
                        need(before and after and before[1] == after[1],
                             'Hardware ' + kind + ' owner/trigger changed')
                source.healthy()
                entry['passed'] = True
            finally:
                source.forward = False
                client.close()
            # Hardware remains open on silence between distinct client owners.
            pcm.settle(1)
        need(len({c['pid'] for c in evidence['clients']}) == 2,
             'Expected two distinct default-source clients')
        evidence['microphone_client_passed'] = True
        report['acoustic_passed'] = True
        report['remaining_prerequisites'] = [
            'A02 quality, simultaneous mic mapping, persistent/on-demand availability, '
            'hardware capture reopen and full A03 teardown/resume remain open.']
    finally:
        timer.cancel()
        evidence['seconds'] = time.monotonic() - started


def desktop_playback(args, report, pcm, paths, mapping, capture, holders):
    from acoustic import score_phase

    evidence = report['desktop'] = {'acoustic_passed': False, 'applications': [],
                                   'phases': [], 'maximum_seconds': 45}
    graph = DesktopGraph(args.desktop_user, evidence)
    holders.append(graph)  # On failure outer cleanup parks before graph cleanup.
    start_time = time.monotonic()
    deadline = threading.Timer(45, lambda: os.kill(os.getpid(), signal.SIGTERM))
    deadline.start()
    try:
        graph.start()
        pcm.set_source(graph.monitor)
        pcm.settle(0.5)
        for name, channels in (('left', {0}), ('right', {1}), ('both', {0, 1}),
                               ('second-app', {0, 1})):
            # Measure the current room/amp background before each stimulus.
            # Always use the last contiguous two seconds, chosen before any
            # tone plays; never search the recording for a quieter reference.
            graph.monitor.forward = False
            quiet_begin = capture.mark()
            quiet_seconds = 5 if name == 'second-app' else 2
            pcm.settle(quiet_seconds)
            capture.wait_frames(quiet_begin + quiet_seconds * 48000)
            quiet_end = capture.mark()
            quiet_start = quiet_end - 2 * 48000
            reference = capture.samples(quiet_start, quiet_end)
            if name == 'second-app':
                evidence['idle_seconds'] = 5
            check_stereo(mapping, paths, initialized=True)
            begin = capture.mark()
            phase = {'name': name, 'reference_start_frame': quiet_start,
                     'reference_end_frame': quiet_end, 'start_frame': begin}
            evidence['phases'].append(phase)
            graph.play(tone(channels), name)
            pcm.settle(0.8)
            graph.monitor.forward = False
            graph.monitor.healthy()
            capture.wait_frames(begin + 3 * 48000)
            end = capture.mark()
            scored = score_phase(capture.samples(begin, end), reference,
                                 [440 if channel == 0 else 660 for channel in sorted(channels)])
            phase.update(end_frame=end, score=scored)
            need(scored['passed'], f'Desktop {name} acoustic test failed: {scored["reason"]}')
            pcm.healthy()
        evidence['acoustic_passed'] = True
        pcm.set_source(None)
        evidence['monitor_peak'] = graph.monitor.peak
        evidence['monitor_max_interarrival_seconds'] = graph.monitor.max_interarrival_seconds
        graph.monitor.close()
        graph.monitor = None
        pcm.settle(0.8)
    finally:
        deadline.cancel()
        evidence['seconds'] = time.monotonic() - start_time


def restore_microphone_mixer(report, saved):
    """Consume saved controls once, including after a partial setup failure."""
    restored = report.setdefault('microphone_mixer_restore', [])
    errors = report.setdefault('cleanup_errors', [])
    while saved:
        command, name = saved.pop()
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            restored.append({'name': name, 'returncode': result.returncode,
                             'stderr': result.stderr})
        except Exception as error:
            errors.append('capture mixer: ' + type(error).__name__ + ': ' + str(error))


def finish_recording(capture, report, saved):
    """Close recording and restore its route before any ordinary app handoff."""
    try:
        capture.close()
        need(capture.process.poll() is not None, 'Microphone process remains active')
        need(read_text(capture.status) == 'closed', 'Microphone PCM remains open')
        report['recording_closed'] = True
    finally:
        restore_microphone_mixer(report, saved)
    need(not report['capture'].get('error'), 'Microphone monitor failed')
    need(not re.search(r'overrun|underrun|error', report['capture']['log'], re.I),
         'Capture reported an ALSA error')
    need(not report.get('cleanup_errors') and
         all(item['returncode'] == 0 for item in report['microphone_mixer_restore']),
         'Microphone mixer restoration failed')


def verify_public_playback(report, pcm, graph, capture, desktop_peak=1433):
    """Score the actual attenuated public route before ending microphone capture."""
    from acoustic import score_phase

    evidence = report['public_desktop'] = {'acoustic_passed': False,
        'sink': 'spx_speakers', 'input_peak_limit': 32767, 'output_peak_limit': desktop_peak,
        'gain': desktop_peak / 32768, 'maximum_seconds': 30, 'deadline_expired': False,
        'phase_seconds': {}}
    started = time.monotonic()

    def phase(name):
        evidence['phase'] = name
        evidence['phase_seconds'][name] = time.monotonic() - started

    def expire():
        evidence.update(deadline_expired=True, timeout_phase=evidence['phase'],
                        timeout_seconds=time.monotonic() - started,
                        timeout_reason='Public playback verification deadline exceeded')
        os.kill(os.getpid(), signal.SIGTERM)

    # Include Pulse setup and CPU-bound scoring under frequency scaling. This
    # does not lengthen the two-second tone or the overall 90-second capture cap.
    phase('connect')
    deadline = threading.Timer(evidence['maximum_seconds'], expire)
    deadline.start()
    try:
        graph.connect_public(pcm, desktop_peak=desktop_peak)
        phase('settle')
        pcm.settle(0.5)
        graph.require_public_idle()
        graph.monitor.forward = False
        graph.monitor.input_peak = 0
        phase('reference')
        quiet_begin = capture.mark()
        pcm.settle(2)
        capture.wait_frames(quiet_begin + 2 * 48000)
        quiet_end = capture.mark()
        evidence.update(reference_start_frame=quiet_end - 2 * 48000,
                        reference_end_frame=quiet_end)
        reference = capture.samples(quiet_end - 2 * 48000, quiet_end)
        graph.require_public_idle()
        need(graph.monitor.input_peak <= 1,
             'Public monitor was not silent during its acoustic reference')
        begin = capture.mark()
        evidence['start_frame'] = begin
        phase('playback')
        graph.play(tone({0, 1}, amplitude=32767), 'public-both')
        phase('drain')
        pcm.settle(0.8)
        capture.wait_frames(begin + 3 * 48000)
        end = capture.mark()
        evidence['end_frame'] = end
        graph.require_public_idle()
        # As in the temporary desktop test, score only after playback has
        # drained, using ALSA-paced local silence. A CPU-bound Python scorer
        # can starve the 5 ms monitor/feeder handoff even with queued samples.
        # Leave this mode in place through microphone close and mixer restore.
        graph.monitor.forward = False
        evidence.update(input_peak=graph.monitor.input_peak, output_peak=graph.monitor.peak)
        phase('scoring')
        scored = score_phase(capture.samples(begin, end), reference, [440, 660])
        evidence['score'] = scored
        phase('validate')
        graph.require_public_idle()
        graph.monitor.healthy()
        pcm.healthy()
        need(scored['passed'], f'Public desktop acoustic test failed: {scored["reason"]}')
        evidence['acoustic_passed'] = True
        evidence['public_volume'] = {'current': [65536, 65536],
            'prior': list(next(command[3:] for command in graph.public_restore
                               if command[1] == 'set-sink-volume')),
            'restored_on_cleanup': True}
        phase('complete')
    finally:
        deadline.cancel()
        evidence['seconds'] = time.monotonic() - started


def serve_desktop(args, report, pcm, graph, paths, mapping):
    """Ordinary desktop session; no microphone is open in this loop."""
    need(report['desktop']['acoustic_passed'] and
         report['public_desktop']['acoustic_passed'] and report.get('recording_closed'),
         'Serve handoff requires acoustic verification and a closed microphone')
    graph.monitor.forward = True
    pcm.settle(0.5)
    graph.monitor.healthy()
    check_stereo(mapping, paths, initialized=True)
    started = time.monotonic()
    deadline = started + args.serve_seconds if args.serve_seconds else None
    ready = report['serve'] = {
        'acoustic_passed': True, 'public_acoustic_passed': True,
        'recording_closed': True, 'sink': 'spx_speakers',
        'owner_pid': os.getpid(), 'pcm_pid': pcm.process.pid,
        'boot_id': report['before']['boot_id'], 'release': report['before']['release'],
        'maximum_seconds': args.serve_seconds, 'deadline_monotonic': deadline,
        'deadline_utc': (datetime.fromtimestamp(time.time() + args.serve_seconds,
                                               timezone.utc).isoformat()
                         if args.serve_seconds else None),
        'gain': args.desktop_peak / 32768, 'peak_limit': args.desktop_peak, 'pa_gain': 0,
        'pcm_feed': dict(pcm.feed_stats),
        'monitor_max_interarrival_seconds': graph.monitor.max_interarrival_seconds,
        'note': 'Conservative fixed attenuation; useful listening volume is not yet validated.'}
    stop = threading.Event()

    def terminate(signum, frame):
        # A monitor fault sends the same signal as a requested service stop.
        # Faults must unwind immediately to amplifier parking, not normal close.
        graph.monitor.healthy()
        pcm.healthy()
        stop.set()

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        temporary = args.output / f'.serve-ready.{os.getpid()}'
        temporary.write_text(json.dumps(ready, indent=2) + '\n')
        temporary.replace(args.output / 'serve-ready.json')
        save_run_result(args.output, report)
        next_hardware_check = started
        while not stop.wait(0.1):
            pcm.healthy()
            graph.monitor.healthy()
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            if now >= next_hardware_check:
                check_stereo(mapping, paths, initialized=True)
                next_hardware_check = now + 5
        pcm.healthy()
        graph.monitor.healthy()
        ready.update(stopped=True, stop_reason='SIGTERM' if stop.is_set() else 'deadline',
                     seconds=time.monotonic() - started,
                     input_peak=graph.monitor.input_peak, output_peak=graph.monitor.peak,
                     pcm_feed=dict(pcm.feed_stats),
                     monitor_max_interarrival_seconds=graph.monitor.max_interarrival_seconds)
        # Keep the same PCM running on silence while the monitor is removed.
        pcm.set_source(None)
        graph.monitor.close()
        graph.monitor = None
        pcm.settle(0.8)
    finally:
        signal.signal(signal.SIGTERM, previous)


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


def listen(args, report, pcm_holder, capture=None, baseline=None, desktop_holder=None,
           before_serve=None):
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
    report['pcm']['feed'] = pcm.feed_stats
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
    if args.action == 'reopen':
        for expression in (r'^period_size: 2400$', r'^buffer_size: 12000$'):
            need(re.search(expression, hw_params, re.M), 'Playback reopen geometry changed')
    report['pcm']['hw_params'] = hw_params
    checks = report.setdefault('playback_checks', [])
    report['before_late_init'] = check_stereo(mapping, paths, observations=checks)
    report['late_initialization'] = []
    for unit, path in paths.items():
        before = playback_state(path)['LATE_INIT_COUNT']
        operation = {'unit': unit, 'before_count': before}
        report['late_initialization'].append(operation)
        try:
            (path / 'spx_late_init').write_text('1\n')
        except OSError as error:
            operation['error'] = str(error)
            raise RuntimeError(f'Unit {unit}: late initialization failed: {error}') from error
        finally:
            # Detachment clears the late-init verdict. Retain it before the
            # outer cleanup powers the amps down, including a rejected replay.
            operation['after'] = playback_state(path)
        need(playback_state(path)['LATE_INIT_COUNT'] == before + 1,
             f'Unit {unit}: late initialization did not advance')
    report['after_late_init'] = check_stereo(mapping, paths, initialized=True, observations=checks)
    pcm.settle(1.0)  # Conservative settling margin; minimum has not been measured.
    report['remaining_prerequisites'] = [UNMET[-1]]
    report['playback_ready'] = True
    if args.action == 'desktop-mic':
        desktop_microphone(args, report, pcm, paths, mapping, capture, desktop_holder)
        return
    if args.action in ('desktop', 'serve'):
        desktop_playback(args, report, pcm, paths, mapping, capture, desktop_holder)
        if args.action == 'serve':
            verify_public_playback(report, pcm, desktop_holder[-1], capture, args.desktop_peak)
            before_serve()
            serve_desktop(args, report, pcm, desktop_holder[-1], paths, mapping)
        # Orderly close while the native slaves can still receive mute and
        # disable/deprepare writes. Failures retain the outer park-first path.
        report['pcm']['log'] = pcm.close()
        pcm_holder.remove(pcm)
        check_desktop_teardown(paths, report['desktop'])
        report['remaining_prerequisites'] = [
            'Suspend, hardware reopen, useful volume and long-term reliability remain untested.'
            if args.action == 'serve' else
            'Persistent/default desktop audio, suspend and long-term reliability remain untested.']
        return
    if args.action == 'reopen':
        # Fix the reference before any stimulus, after this stream's late init.
        quiet_begin = capture.mark()
        pcm.settle(2)
        capture.wait_frames(quiet_begin + 2 * 48000)
        quiet_end = capture.mark()
        quiet_start = quiet_end - 2 * 48000
        baseline = capture.samples(quiet_start, quiet_end)
        report['reopen_reference'] = {'start_frame': quiet_start, 'end_frame': quiet_end,
            'rms': math.sqrt(sum(v*v for v in baseline) / len(baseline))}
    report['tones'] = []
    for name, channels in (('left', {0}), ('right', {1}), ('both', {0, 1})):
        pcm.healthy()
        check_stereo(mapping, paths, initialized=True, observations=checks)
        print(f'Listening test: {name}, two seconds', flush=True)
        start = capture.mark() if capture else None
        pcm.play(tone(channels))
        report['tones'].append({'channels': name, 'seconds': 2, 'peak_limit': 1433})
        if capture:
            from acoustic import score_phase
            capture.wait_frames(start + 3 * 48000)
            end = capture.mark()
            result = score_phase(capture.samples(start, end), baseline,
                                 [440 if channel == 0 else 660 for channel in sorted(channels)])
            phase_name = f'cycle-{report["reopen_cycle"]}-{name}' if args.action == 'reopen' else name
            report['capture']['phases'].append({'name': phase_name, 'start_frame': start,
                                               'end_frame': end, 'score': result})
            need(result['passed'], f'Acoustic {name} test failed: {result["reason"]}')
    report['after_playback'] = check_stereo(mapping, paths, initialized=True, observations=checks)
    if capture:
        report['acoustic_tones_detected'] = True
        report['remaining_prerequisites'] = ['Uncalibrated internal mic cannot establish physical channel location, SPL, or desktop audio readiness.']
    else:
        report['human_result'] = 'pending; successful software checks do not establish audible output'


def playback_reopen(args, report, pcm_holder, capture, baseline):
    """Close two Linux playback PCMs while attached; retain ASM and one capture."""
    need(capture is not None, 'Playback reopen requires continuous microphone feedback')
    paths = {s['unit']: Path('/sys/bus/soundwire/devices') / s['name'] for s in devices()}
    evidence = report['reopen'] = {'passed': False, 'cycles': [],
        'capture_pid': capture.process.pid, 'asm_kept': True,
        'scope': 'Linux playback PCM close/reopen; no DSP or capture reopen'}
    for number in (1, 2):
        cycle = {'number': number, 'passed': False, 'capture_start_frame': capture.mark()}
        evidence['cycles'].append(cycle)
        report['reopen_cycle'] = number
        first_phase = len(report['capture']['phases'])
        for key in ('pcm', 'reopen_reference', 'late_initialization',
                    'before_late_init', 'after_late_init', 'after_playback'):
            report.pop(key, None)
        try:
            listen(args, report, pcm_holder, capture, baseline)
        finally:
            # Retain the failed stream as well as successful cycles. In
            # particular, never label the first stream's final state as the
            # reopened stream's result after an early acoustic failure.
            for source, target in (('pcm', 'pcm'), ('reopen_reference', 'reference'),
                                   ('late_initialization', 'late_initialization'),
                                   ('after_late_init', 'after_late_init'),
                                   ('after_playback', 'after_playback')):
                if source in report:
                    cycle[target] = report[source]
            cycle['acoustic_phases'] = report['capture']['phases'][first_phase:]
        pcm = pcm_holder[-1]
        cycle['pcm']['log'] = pcm.close()
        pcm_holder.remove(pcm)
        cycle['closed_status'] = read_text(pcm.status)
        need(cycle['closed_status'] == 'closed', 'Playback PCM remains open after close')
        need(not re.search(r'underrun|overrun|error', cycle['pcm']['log'], re.I),
             'Playback close reported an ALSA error')
        check_desktop_teardown(paths, cycle)
        capture.healthy()
        cycle['capture_status_after_close'] = read_text(capture.status)
        need(re.search(r'^state:\s+RUNNING$', cycle['capture_status_after_close'], re.M) and
             re.search(r'^owner_pid\s*:\s*' + str(evidence['capture_pid']) + r'$',
                       cycle['capture_status_after_close'], re.M),
             'Continuous microphone ownership changed during playback close')
        cycle['capture_end_frame'] = capture.mark()
        need(cycle['capture_end_frame'] > cycle['capture_start_frame'],
             'Microphone did not advance during playback cycle')
        cycle['passed'] = True
    need(len({cycle['pcm']['pid'] for cycle in evidence['cycles']}) == 2,
         'Playback reopen did not use two distinct PCM owners')
    evidence['passed'] = True
    report['acoustic_passed'] = True
    report['remaining_prerequisites'] = [
        'Full DSP/capture teardown, suspend, volume and long-term reliability remain untested.']


def cleanup_audio_consumers(report, pcms, graphs, capture, saved, signals, timer):
    """Attempt every consumer cleanup, mixer restoration and signal reset."""
    errors = report.setdefault('cleanup_errors', [])

    def attempt(label, function, *args):
        try:
            return function(*args)
        except Exception as error:
            message = label + ': ' + type(error).__name__ + ': ' + str(error)
            errors.append(message)
            if label == 'desktop':
                report.setdefault('desktop', {})['cleanup_error'] = message

    try:
        while pcms:
            report.setdefault('pcm', {})['log'] = attempt('PCM', pcms.pop().close)
        for graph in graphs:
            attempt('desktop', graph.close)
        if capture:
            attempt('capture', capture.close)
        if timer:
            attempt('capture deadline', timer.cancel)
        attempt('microphone mixer', restore_microphone_mixer, report, saved)
    finally:
        for signum, handler in signals.items():
            attempt('signal reset', signal.signal, signum, handler)


def initialize(args, report):
    source = getattr(args, 'microphone_source', 'DMIC1')
    validate_microphone_source(args.action, source)
    need(os.geteuid() == 0, 'initialize requires root')
    need(args.action in ('recover', 'capture') or args.allow_amp_power,
         'initialize/listen requires --allow-amp-power for this authorized run')
    need(args.action not in ('listen', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic') or args.allow_playback,
         'listen requires separate explicit --allow-playback authorization')
    need(args.action not in ('capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic') or args.allow_capture,
         'Microphone recording requires --allow-capture')
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
    if args.action in ('listen', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
        need(parameter('snd_soc_wcd934x', 'spx_persist_stream') == 'Y',
             'Playback requires WCD SLIM stream persistence before its first open')
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
    desktop_holder = []
    capture = None
    saved_mixer = []
    baseline = None
    capture_deadline = None
    signals = {}

    def release_recording():
        nonlocal capture
        try:
            finish_recording(capture, report, saved_mixer)
        finally:
            # Close and mixer restoration have already been attempted.
            capture = None

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
        if args.action in ('capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
            need(args.output is not None, 'Capture requires a private result directory')
            directory = args.output / ('capture-' + report['utc'])
            directory.mkdir(mode=0o700)
            configure_microphone(initial['internal_cards'][0], report, saved_mixer, source)
            if args.action == 'desktop-mic':
                def expire_capture():
                    report['capture_deadline_expired'] = True
                    os.kill(os.getpid(), signal.SIGTERM)

                report['capture_deadline_expired'] = False
                capture_deadline = threading.Timer(60, expire_capture)
                capture_deadline.start()
                capture = OwnedCapture(initial['internal_cards'][0], report, directory,
                                       maximum_seconds=60, retain_recording=False)
            else:
                capture = OwnedCapture(initial['internal_cards'][0], report, directory)
            baseline = capture.baseline()
            if args.action == 'capture':
                report['capture_running'] = True
                return
        for bits, expected in ((0x02, {3}), (0x06, {3, 4})):
            assert_desktop_paused(args.desktop_user)
            assert_pcm_idle()
            capture_frame = capture.mark() if capture else None
            report['parked'] = False
            writer.write_text(f'43 {parked | bits:02x}\n')
            stage = {'powered_pins': bits, 'samples': [],
                     'capture_frame_before_power': capture_frame}
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
                        stage['capture_frame_initialized'] = capture.mark() if capture else None
                        break
                    stable = mapping
                time.sleep(0.25)
            else:
                raise RuntimeError(f'Native enumeration did not settle: {last_error}')
        report['enumeration_passed'] = True
        report['remaining_prerequisites'].remove(UNMET[0])
        if args.action == 'reopen':
            playback_reopen(args, report, pcm_holder, capture, baseline)
        elif args.action in ('listen', 'feedback', 'desktop', 'serve', 'desktop-mic'):
            listen(args, report, pcm_holder, capture, baseline, desktop_holder, release_recording)
        if args.action == 'feedback':
            # Control for electrical crosstalk: keep the identical capture/PCM
            # routes, disable the physical amps, then send the same digital tones.
            from acoustic import score_phase
            writer.write_text(f'43 {parked:02x}\n')
            report['control_parked_state'] = state()
            need(report['control_parked_state']['GPIO_VAL'] & 0x1e == 0x18,
                 'Cannot verify physical powerdown for acoustic control')
            capture.wait_frames(capture.mark() + 48000)
            start = capture.mark()
            pcm_holder[0].play(tone({0, 1}))
            capture.wait_frames(start + 3 * 48000)
            end = capture.mark()
            controls = [score_phase(capture.samples(start, end), baseline, [hz])
                        for hz in (440, 660)]
            report['capture']['amps_off_control'] = {'start_frame': start,
                'end_frame': end, 'scores': controls}
            for result in controls:
                for target in result['targets'].values():
                    need(target['rms'] < 1 or target['baseline_rise_db'] < 10 or
                         target['neighbor_rise_db'] < 10,
                         'Test tone persists with amps off: acoustic result inconclusive')
            report['acoustic_passed'] = True
    finally:
        report['background_errors'] = {
            'capture': getattr(capture, 'error', None),
            'playback': [getattr(pcm, 'error', None) for pcm in pcm_holder],
            'desktop_monitor': [getattr(getattr(graph, 'monitor', None), 'error', None)
                                for graph in desktop_holder],
            'microphone_adapter': [getattr(getattr(graph, 'microphone', None), 'error', None)
                                   for graph in desktop_holder]}
        cleanup_errors = report.setdefault('cleanup_errors', [])
        for signum in signals:
            try:
                signal.signal(signum, signal.SIG_IGN)
            except Exception as error:
                cleanup_errors.append('ignore signal: ' + str(error))
        # A broken desktop object must not prevent physical amplifier parking.
        for graph in desktop_holder:
            try:
                monitor = getattr(graph, 'monitor', None)
                if monitor:
                    monitor.stop.set()
            except Exception as error:
                cleanup_errors.append('stop monitor: ' + type(error).__name__ + ': ' + str(error))
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
            if 'pcm' in report and report['parked']:
                # The physical powerdown snapshot precedes PCM teardown. Retain
                # its later FIFO/port state too: teardown can leave commands
                # queued even though amplifier parking succeeded.
                report['after_pcm_close_state'] = state()
            if report['parked']:
                control.write_text(saved_control + '\n')
                need(read_text(control) == saved_control, 'Master runtime PM policy was not restored')
                report['runtime_pm']['restored'] = True
        finally:
            cleanup_audio_consumers(report, pcm_holder, desktop_holder, capture,
                                    saved_mixer, signals, capture_deadline)
    need(not report.get('cleanup_errors'), 'Audio cleanup failed; see cleanup_errors')
    if 'pcm' in report:
        need(not re.search(r'underrun|overrun|error', report['pcm']['log'], re.I),
             'ALSA reported an underrun or playback error; inspect the PCM log')
    if args.action in ('desktop', 'serve', 'desktop-mic'):
        need(report['desktop'].get('graph_restored') and
             not report['desktop'].get('cleanup_error'), 'Desktop graph cleanup failed')


def serve_duration(value):
    seconds = int(value)
    if not 0 <= seconds <= 86400:
        raise argparse.ArgumentTypeError('serve duration must be between 0 and 86400 seconds')
    return seconds


def desktop_peak_limit(value):
    peak = int(value)
    if not 1433 <= peak <= 12000:
        raise argparse.ArgumentTypeError('desktop peak must be between 1433 and 12000')
    return peak


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('plan', 'inspect', 'initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'), default='plan')
    parser.add_argument('--output', type=Path, help='directory for result JSON')
    parser.add_argument('--owner', help='coordinator device-lock owner (initialize)')
    parser.add_argument('--desktop-user', help='user whose audio units the caller has paused')
    parser.add_argument('--allow-amp-power', action='store_true',
                        help='explicitly authorize this bounded initialization run')
    parser.add_argument('--allow-playback', action='store_true',
                        help='explicitly authorize this one bounded listening run')
    parser.add_argument('--allow-capture', action='store_true',
                        help='authorize bounded internal microphone recording')
    parser.add_argument('--microphone-source', choices=('DMIC0', 'DMIC1'), default='DMIC1',
                        help='bounded capture/feedback/desktop-mic input (default: DMIC1)')
    parser.add_argument('--serve-seconds', type=serve_duration, default=3600,
                        help='ordinary desktop session duration, 0 until stopped or 1..86400 seconds (default: 3600)')
    parser.add_argument('--desktop-peak', type=desktop_peak_limit,
                        help='serve-only ordinary PCM peak, 1433..12000 (default: 1433)')
    args = parser.parse_args()
    if args.microphone_source != 'DMIC1' and args.action not in ('capture', 'feedback', 'desktop-mic'):
        parser.error('--microphone-source DMIC0 requires capture or feedback or desktop-mic')
    if args.desktop_peak is not None and args.action != 'serve':
        parser.error('--desktop-peak is only valid with serve')
    if args.desktop_peak is None:
        args.desktop_peak = 1433
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    report = {'action': args.action, 'utc': stamp, 'playback_ready': False,
              'microphone_capture': False, 'success': False, 'parked': False,
              'remaining_prerequisites': list(UNMET)}
    if args.action == 'feedback':
        report['remaining_prerequisites'][-1] = (
            'Detect requested tones in the microphone above quiet/noise, '
            'and confirm they disappear with amplifier power off.')
    result = 0
    try:
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            if args.action in ('initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
                # A killed run must never leave an earlier "parked" verdict.
                save_run_result(args.output, report)
                if args.action == 'serve':
                    (args.output / 'serve-ready.json').unlink(missing_ok=True)
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
            if report['microphone_capture']:
                need(not report['capture'].get('error'), 'Microphone monitor failed')
                need(not re.search(r'overrun|underrun|error', report['capture']['log'], re.I),
                     'Capture reported an ALSA error')
                need(all(item['returncode'] == 0 for item in report['microphone_mixer_restore']),
                     'Microphone mixer restoration failed')
        report['success'] = True
    except Exception as error:
        report['error'] = str(error)
        report['error_type'] = type(error).__name__
        result = 1
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        (args.output / f'audio-{args.action}-{stamp}.json').write_text(text)
        if args.action in ('initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
            save_run_result(args.output, report)
    print(text, end='')
    return result


if __name__ == '__main__':
    sys.exit(main())
