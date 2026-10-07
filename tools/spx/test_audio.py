#!/usr/bin/env python3
"""Offline checks only: generated samples, PCM pipe writes and permission gates."""
import importlib.util
import contextlib
import io
import fcntl
import json
import os
from pathlib import Path
import queue
import select
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('spx_audio', Path(__file__).with_name('audio.py'))
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class AudioTests(unittest.TestCase):
    def test_array_gate_precedes_hardware(self):
        for action, source in (('capture', 'DMIC1'), ('desktop-mic', 'DMIC1'), ('feedback', 'DMIC0')):
            with self.subTest(action=action), patch.object(audio.os, 'geteuid') as hardware:
                with self.assertRaisesRegex(RuntimeError, 'microphone-array requires feedback'):
                    audio.initialize(SimpleNamespace(action=action, microphone_source=source,
                                                     microphone_array=True), {})
                hardware.assert_not_called()

    def test_array_routes_preserved_disabled_then_enabled_in_native_order(self):
        report, saved, writes = {}, [], []
        routes = ['AIF1_CAP Mixer SLIM TX' + str(i) for i in range(4)]
        def mixer(command, **kwargs):
            if command[-1] == 'controls':
                output = '\n'.join("numid=1,name='" + name + "'" for name in routes)
            elif command[-2] == 'cget':
                output = ': values=on\n'
            else:
                name, value = command[-2][5:], command[-1]
                writes.append((name, value))
                if 'MUX' in name:
                    output = "; Item #1 '" + value + "'\n: values=1\n"
                else:
                    output = ': values=' + ('on' if value == '1' else 'off' if value == '0' else value) + '\n'
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        with patch.object(audio, 'parameter', return_value='Y'), \
                patch.object(audio, 'Path') as paths, \
                patch.object(audio.subprocess, 'run', side_effect=mixer):
            paths.return_value.glob.return_value = []
            audio.configure_microphone(0, report, saved, 'DMIC1', True)
        self.assertEqual(writes[1:5], [(name, '0') for name in routes])
        self.assertEqual(writes[-2:], [(routes[0], '1'), (routes[1], '1')])
        self.assertEqual(len(saved), len(set(name for _, name in saved)))
        self.assertEqual(report['microphone_array']['sources'], ['DMIC1', 'DMIC0'])
        selected = {item['name']: item.get('selected') for item in report['microphone_mixer']}
        self.assertEqual(selected['DMIC MUX1'], 'DMIC0')

    def test_stereo_frame_accounting_and_deinterleave(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        capture.channels = 2
        capture.raw = bytearray(struct.pack('<6h', 1, 11, 2, 12, 3, 13) + b'\x00')
        capture.mutex = threading.Lock()
        capture.healthy = Mock()
        self.assertEqual(capture.mark(), 3)
        self.assertEqual(list(capture.samples(1, 3)), [2, 12, 3, 13])
        self.assertEqual([list(v) for v in audio.deinterleave(capture.samples(), 2)],
                         [[1, 2, 3], [11, 12, 13]])
        capture.channels = 1
        self.assertEqual(capture.mark(), 6)
        self.assertEqual(list(capture.samples(1, 3)), [11, 2])

    def test_stereo_capture_is_native_bounded_and_discards_raw(self):
        report = {'microphone_source': 'DMIC1'}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(audio.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)) as opened, \
                patch.object(audio.threading, 'Thread'):
            capture = audio.OwnedCapture(0, report, Path(directory), maximum_seconds=50,
                                         retain_recording=False, channels=2)
            capture.log.close()
        command = opened.call_args.args[0]
        self.assertIn('hw:0,1', command)
        self.assertIn('--period-size=960', command)
        self.assertIn('--buffer-size=3840', command)
        self.assertLessEqual(report['capture']['period_frames'] * 4, 4096)
        self.assertEqual(report['capture']['period_frames'] % 480, 0)
        self.assertEqual(command[command.index('-c') + 1], '2')
        self.assertEqual(command[-2:], ['-d', '50'])
        self.assertFalse(capture.retain_recording)

    def test_stereo_baseline_verifies_native_geometry_and_keeps_rejected_params(self):
        from array import array
        for period in (960, 1920):
            with self.subTest(period=period):
                capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
                capture.channels, capture.period_frames, capture.buffer_frames = 2, 960, 3840
                capture.report = {'capture': {}}
                capture.process = SimpleNamespace(pid=123)
                capture.status = Path('/capture/status')
                capture.wait_frames = Mock()
                capture.samples = Mock(return_value=array('h', [1, 2] * 100))
                params = f'format: S16_LE\nchannels: 2\nrate: 48000\nperiod_size: {period}\nbuffer_size: 3840\n'
                with patch.object(audio, 'read_text', side_effect=['state: RUNNING\nowner_pid: 123\n', params]):
                    if period == 960:
                        capture.baseline()
                        self.assertEqual(capture.report['capture']['baseline']['input_rms'], [1, 2])
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'Capture geometry changed'):
                            capture.baseline()
                self.assertEqual(capture.report['capture']['hw_params'], params)

    def test_array_scorer_rejects_missing_input_and_exact_duplicate(self):
        from array import array
        import math
        n = 48000
        quiet = [int(2 * math.sin(i * .123)) for i in range(n)]
        tone = [int(100 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(n)]
        def interleave(a, b):
            return array('h', [v for pair in zip(a, b) for v in pair])
        duplicate = audio.score_array_phase(interleave(tone, tone), interleave(quiet, quiet), [440])
        self.assertFalse(duplicate['passed'])
        self.assertTrue(duplicate['exact_duplicate'])
        missing = audio.score_array_phase(interleave(tone, [0] * n), interleave(quiet, quiet), [440])
        self.assertFalse(missing['passed'])
        self.assertFalse(missing['inputs'][1]['passed'])

    def test_array_independence_requires_distinct_transfer(self):
        def phases(right):
            return [{'name': name, 'score': {'passed': True, 'exact_duplicate': False,
                    'inputs': [{'targets': {str(hz): {'rms': a}}},
                               {'targets': {str(hz): {'rms': b}}}]}}
                    for name, hz, a, b in [('left', 440, 20, 10), ('right', 660, right, 10)]]
        self.assertFalse(audio.array_independence(phases(20))['milestone_passed'])
        self.assertTrue(audio.array_independence(phases(5))['milestone_passed'])

    def test_right_first_only_changes_reopened_cycle(self):
        expected = [('left', {0}), ('right', {1}), ('both', {0, 1})]
        self.assertEqual(list(audio.playback_tones('reopen', 1, 'right')), expected)
        self.assertEqual(list(audio.playback_tones('feedback', 2, 'right')), expected)
        self.assertEqual(list(audio.playback_tones('reopen', 2, None)), expected)
        self.assertEqual(list(audio.playback_tones('reopen', 2, 'right')),
                         [expected[1], expected[0], expected[2]])

    def test_tones_have_bounded_level_and_correct_channels(self):
        for channels in ({0}, {1}, {0, 1}):
            data = audio.tone(channels)
            self.assertEqual(len(data), 2 * 48000 * 4)
            frames = list(struct.iter_unpack('<hh', data))
            self.assertEqual(frames[0], (0, 0))
            self.assertEqual(frames[-1], (0, 0))
            for channel in (0, 1):
                peak = max(abs(frame[channel]) for frame in frames)
                self.assertLessEqual(peak, 1433)
                self.assertEqual(peak > 0, channel in channels)

    def test_feeder_preserves_partial_writes_then_returns_to_silence(self):
        # No ALSA process/device: a real pipe with deliberately short writes.
        reader, writer = os.pipe()
        os.set_blocking(writer, False)
        pcm = audio.OwnedPCM.__new__(audio.OwnedPCM)
        pcm.process = SimpleNamespace(stdin=os.fdopen(writer, 'wb', buffering=0))
        pcm.stop = threading.Event()
        pcm.pending = queue.Queue()
        pcm.error = None
        pcm.source = None
        pcm.source_lock = threading.Lock()
        data = audio.tone({1}, seconds=0.03)
        done = threading.Event()
        pcm.pending.put((data, done))
        original_write = os.write
        received = bytearray()
        with patch.object(audio.os, 'write', side_effect=lambda fd, b: original_write(fd, b[:31])):
            feeder = threading.Thread(target=pcm.feed)
            feeder.start()
            try:
                while len(received) < len(data) + 9600:
                    received.extend(os.read(reader, 4096))
                self.assertTrue(done.wait(timeout=1))
            finally:
                pcm.stop.set()
                feeder.join(timeout=2)
                pcm.process.stdin.close()
                os.close(reader)
        self.assertFalse(feeder.is_alive())
        self.assertIsNone(pcm.error)
        self.assertEqual(received[:len(data)], data)
        self.assertEqual(received[len(data):], bytes(len(received) - len(data)))

    def test_listen_rejects_missing_playback_permission_before_hardware(self):
        args = SimpleNamespace(action='listen', allow_amp_power=True, allow_playback=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'playback'):
                audio.initialize(args, {})

    def test_initialize_rejects_missing_power_permission_before_hardware(self):
        args = SimpleNamespace(action='initialize', allow_amp_power=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'amp-power'):
                audio.initialize(args, {})

    def test_feedback_requires_capture_permission_before_hardware(self):
        args = SimpleNamespace(action='feedback', allow_amp_power=True,
                               allow_playback=True, allow_capture=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'allow-capture'):
                audio.initialize(args, {})

    def test_capture_requires_capture_permission_without_amp_permission(self):
        args = SimpleNamespace(action='capture', allow_amp_power=False, allow_capture=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'allow-capture'):
                audio.initialize(args, {})

    def test_microphone_source_is_written_verified_and_recorded_before_capture(self):
        for source, index in (('DMIC0', 1), ('DMIC1', 2)):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                report, saved = {}, []
                readback = "; Item #0 'ZERO'\n; Item #1 'DMIC0'\n; Item #2 'DMIC1'\n: values=" + str(index) + '\n'

                def mixer(command, **kwargs):
                    text = readback if command[-2:] == ['name=DMIC MUX0', source] else ': values=0\n'
                    return SimpleNamespace(returncode=0, stdout=text, stderr='')

                def opened(command, **kwargs):
                    self.assertEqual(report['microphone_source'], source)
                    self.assertEqual(report['microphone_mixer'][-1]['selected'], source)
                    self.assertEqual(command[-2:], ['-d', '90'])
                    self.assertIn('--period-size=1920', command)
                    self.assertIn('--buffer-size=7680', command)
                    return SimpleNamespace(pid=2345)

                with patch.object(audio, 'parameter', return_value='Y'), \
                        patch.object(audio, 'Path') as paths, \
                        patch.object(audio.subprocess, 'run', side_effect=mixer) as run, \
                        patch.object(audio.subprocess, 'Popen', side_effect=opened), \
                        patch.object(audio.threading, 'Thread'):
                    paths.return_value.glob.return_value = []
                    audio.configure_microphone(0, report, saved, source)
                    capture = audio.OwnedCapture(0, report, Path(directory))
                    capture.log.close()
                self.assertEqual(run.call_args.args[0][-2:], ['name=DMIC MUX0', source])
                self.assertEqual(len(saved), 6)
                self.assertEqual(report['capture']['source'], source)
                self.assertEqual(report['microphone_mixer'][-1]['readback'], readback)

    def test_microphone_source_readback_mismatch_stops_before_capture(self):
        report, saved = {}, []
        wrong = "; Item #1 'DMIC0'\n; Item #2 'DMIC1'\n: values=2\n"
        with patch.object(audio, 'parameter', return_value='Y'), \
                patch.object(audio, 'Path') as paths, \
                patch.object(audio.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=wrong, stderr='')), \
                patch.object(audio.subprocess, 'Popen') as opened:
            paths.return_value.glob.return_value = []
            with self.assertRaisesRegex(RuntimeError, 'readback did not select DMIC0'):
                audio.configure_microphone(0, report, saved, 'DMIC0')
            opened.assert_not_called()
        self.assertNotIn('microphone_source', report)
        self.assertEqual(report['microphone_mixer'][-1]['readback'], wrong)

    def test_dmic0_is_rejected_on_other_actions_before_hardware(self):
        for action in ('initialize', 'listen', 'recover', 'desktop', 'serve', 'reopen'):
            with self.subTest(action=action), \
                    patch.object(audio.os, 'geteuid', side_effect=AssertionError('hardware')):
                with self.assertRaisesRegex(RuntimeError, 'only supported for capture or feedback'):
                    audio.initialize(SimpleNamespace(action=action, microphone_source='DMIC0'), {})
        for action in ('capture', 'feedback'):
            audio.validate_microphone_source(action, 'DMIC0')

    def test_microphone_cli_rejects_invalid_source_before_hardware(self):
        for action, source in (('serve', 'DMIC0'), ('feedback', 'DMIC2')):
            with self.subTest(action=action, source=source), \
                    patch.object(audio.sys, 'argv', ['audio.py', action, '--microphone-source', source]), \
                    patch.object(audio.sys, 'stderr', io.StringIO()), \
                    patch.object(audio, 'initialize') as initialize:
                with self.assertRaises(SystemExit) as stopped:
                    audio.main()
                self.assertEqual(stopped.exception.code, 2)
                initialize.assert_not_called()

    def test_capture_monitor_retains_clipped_chunk_and_requests_abort(self):
        # Exercise the actual pipe-consumption path without an ALSA device or
        # delivering a real signal to the test runner.
        reader, writer = os.pipe()
        block = struct.pack('<4800h', *([32767] * 4800))
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        capture.process = SimpleNamespace(stdout=os.fdopen(reader, 'rb', buffering=0))
        capture.stop = threading.Event()
        capture.mutex = threading.Lock()
        capture.raw = bytearray()
        capture.error = None
        capture.limit = None
        feeder = threading.Thread(target=lambda: (os.write(writer, block), os.close(writer)))
        with patch.object(audio.os, 'kill') as abort:
            feeder.start()
            try:
                capture.consume()
                self.assertIn('clipping', capture.error)
                abort.assert_called_once_with(os.getpid(), audio.signal.SIGTERM)
                self.assertEqual(capture.raw, block)
            finally:
                capture.process.stdout.close()
                feeder.join(timeout=2)

    def test_failed_transport_check_retains_both_codec_observations(self):
        snapshot = {'GPIO_VAL': 0x1e, 'MCP_STATUS': 0, 'FRAME_B0': 7,
                    'DP1_B0': 0x01000107, 'DP4_B0': 0}
        observations = []
        with patch.object(audio, 'state', return_value=snapshot), \
                patch.object(audio, 'devices', return_value=[]), \
                patch.object(audio, 'identity_map', return_value={3: 1, 4: 2}), \
                patch.object(audio, 'playback_state', side_effect=[{'UNIT': 3}, {'UNIT': 4}]):
            with self.assertRaisesRegex(RuntimeError, 'DP4_B0'):
                audio.check_stereo({3: 1, 4: 2}, {3: 'left', 4: 'right'},
                                   observations=observations)
        self.assertEqual(len(observations), 1)
        self.assertEqual(set(observations[0]['codec_shadows']), {3, 4})
        self.assertEqual(observations[0]['master']['DP4_B0'], 0)
        self.assertFalse(observations[0]['passed'])

    def test_mixer_error_is_retained_before_setup_stops(self):
        controls = SimpleNamespace(stdout="numid=95,iface=MIXER,name='SpkrLeft PA Volume'\n")
        failure = SimpleNamespace(returncode=1, stdout='', stderr='Input/output error\n')
        report = {}
        with patch.object(audio.subprocess, 'run', side_effect=[controls, failure]):
            with self.assertRaisesRegex(RuntimeError, 'Input/output error'):
                audio.configure_stereo(0, report)
        self.assertEqual(report['mixer'][0]['returncode'], 1)
        self.assertEqual(report['mixer'][0]['stderr'], 'Input/output error')

    def test_native_binding_without_codec_initialization_is_rejected(self):
        snapshot = {'SLV_STATUS': 0x14, 'DEV1_ID1': 0x21170213, 'DEV1_ID2': 0x10,
                    'DEV2_ID1': 0x21170214, 'DEV2_ID2': 0x10}
        slaves = [{'unit': unit, 'address': address, 'status': 'Attached',
                   'driver': 'wsa881x-codec', 'initialized': False}
                  for unit, address in ((3, 1), (4, 2))]
        with self.assertRaisesRegex(RuntimeError, 'initialized native codec'):
            audio.identity_map(snapshot, slaves, {3, 4})
        for slave in slaves:
            slave['initialized'] = True
        self.assertEqual(audio.identity_map(snapshot, slaves, {3, 4}), {3: 1, 4: 2})

    def test_desktop_monitor_reassembles_partial_stereo_frames_without_gain(self):
        reader, writer = os.pipe()
        monitor = audio.DesktopMonitor(SimpleNamespace(
            stdout=os.fdopen(reader, 'rb', buffering=0), poll=lambda: None))
        monitor.forward = True
        data = audio.tone({0, 1}, seconds=0.03)

        def produce():
            for offset in range(0, len(data), 13):
                os.write(writer, data[offset:offset + 13])

        with patch.object(audio.os, 'kill') as abort:
            monitor.thread.start()
            producer = threading.Thread(target=produce)
            producer.start()
            try:
                received = b''.join(monitor.blocks.get(timeout=2)
                                    for _ in range(len(data) // 960))
                self.assertEqual(received, data)
                self.assertLessEqual(monitor.peak, 1433)
                self.assertIsNone(monitor.error)
                abort.assert_not_called()
            finally:
                monitor.stop.set()
                producer.join(timeout=2)
                monitor.thread.join(timeout=2)
                monitor.process.stdout.close()
                os.close(writer)

    def test_desktop_monitor_rejects_excess_before_forwarding(self):
        reader, writer = os.pipe()
        monitor = audio.DesktopMonitor(SimpleNamespace(
            stdout=os.fdopen(reader, 'rb', buffering=0), poll=lambda: None))
        monitor.forward = True
        os.write(writer, struct.pack('<480h', *([1434] * 480)))
        with patch.object(audio.os, 'kill') as abort:
            try:
                monitor.consume()
                self.assertIn('peak limit', monitor.error)
                self.assertTrue(monitor.blocks.empty())
                abort.assert_called_once_with(os.getpid(), audio.signal.SIGTERM)
            finally:
                monitor.process.stdout.close()
                os.close(writer)

    def test_ordinary_monitor_attenuates_fullscale_stereo_without_channel_loss(self):
        for limit in (1433, 4000):
            with self.subTest(limit=limit):
                reader, writer = os.pipe()
                monitor = audio.DesktopMonitor(SimpleNamespace(
                    stdout=os.fdopen(reader, 'rb', buffering=0), poll=lambda: None), ordinary=True, desktop_peak=limit)
                frames = [(-32768, 32767), (16384, -8192), (0, 24000), (-24000, 0)] * 60
                payload = b''.join(struct.pack('<hh', *frame) for frame in frames)

                def produce():
                    for offset in range(0, len(payload), 13):
                        os.write(writer, payload[offset:offset + 13])

                with patch.object(audio.os, 'kill') as abort:
                    monitor.thread.start()
                    producer = threading.Thread(target=produce)
                    producer.start()
                    try:
                        received = monitor.blocks.get(timeout=2)
                        expected = [(int(left * limit / 32768), int(right * limit / 32768))
                                    for left, right in frames]
                        self.assertEqual(list(struct.iter_unpack('<hh', received)), expected)
                        self.assertEqual(monitor.input_peak, 32768)
                        self.assertEqual(monitor.peak, limit)
                        self.assertIsNone(monitor.error)
                        abort.assert_not_called()
                    finally:
                        monitor.stop.set()
                        producer.join(timeout=2)
                        monitor.thread.join(timeout=2)
                        monitor.process.stdout.close()
                        os.close(writer)


    def test_idle_monitor_drains_more_than_queue_capacity_without_enqueuing(self):
        reader, writer = os.pipe()
        monitor = audio.DesktopMonitor(SimpleNamespace(
            stdout=os.fdopen(reader, 'rb', buffering=0), poll=lambda: None))

        def produce():
            for _ in range(100):
                os.write(writer, bytes(960))

        with patch.object(audio.os, 'kill') as abort:
            monitor.thread.start()
            producer = threading.Thread(target=produce)
            producer.start()
            try:
                producer.join(timeout=2)
                self.assertFalse(producer.is_alive(), 'Idle monitor stopped draining its pipe')
                self.assertTrue(monitor.blocks.empty())
                self.assertIsNone(monitor.error)
                abort.assert_not_called()
            finally:
                monitor.stop.set()
                monitor.thread.join(timeout=2)
                monitor.process.stdout.close()
                os.close(writer)

    def test_bursty_active_audio_keeps_exact_timing_across_idle_and_scoring(self):
        import acoustic

        # Source and sink have independent clocks, outside the scorer's GIL.
        # Start with the real 250 ms hardware ring and an empty monitor queue.
        source_read, source_write = os.pipe()
        output_read, output_write = os.pipe()
        result_read, result_write = os.pipe()
        activate_read, activate_write = os.pipe()
        fcntl.fcntl(output_write, fcntl.F_SETPIPE_SZ, 4096)
        waveform = audio.tone({0, 1}, amplitude=32767)
        expected = b''.join(struct.pack('<h', int(value * 4000 / 32768))
                            for value, in struct.iter_unpack('<h', waveform))
        producer = os.fork()
        if producer == 0:
            for fd in (source_read, output_read, output_write, result_read,
                       result_write, activate_write):
                os.close(fd)
            os.read(activate_read, 1)
            os.close(activate_read)
            time.sleep(0.145)  # Initial empty-source delay still fits the ring.
            position = 0
            deadline = time.monotonic()
            try:
                for burst in range(64):
                    frames = 4560 if burst % 2 == 0 else 6960  # 95 / 145 ms.
                    count = frames * 4
                    chunk = waveform[position:position + count]
                    position += len(chunk)
                    data = memoryview(chunk + bytes(count - len(chunk)))
                    while data:
                        data = data[os.write(source_write, data):]
                    deadline += frames / 48000
                    time.sleep(max(0, deadline - time.monotonic()))
                # The measured stimulus is finite; its monitor remains alive
                # during scoring, like the actual desktop application stream.
                while True:
                    data = memoryview(bytes(4560 * 4))
                    while data:
                        data = data[os.write(source_write, data):]
                    deadline += 4560 / 48000
                    time.sleep(max(0, deadline - time.monotonic()))
            except BrokenPipeError:
                pass
            os._exit(0)
        consumer = os.fork()
        if consumer == 0:
            for fd in (source_read, source_write, output_write, result_read,
                       activate_read, activate_write):
                os.close(fd)
            buffered, played = bytearray(), bytearray()
            started = None
            levels = []
            underruns = 0
            # Actual geometry: 2400-frame periods, 12000-frame ring.
            while started is None or time.monotonic() - started < 6.5:
                if started is None:
                    buffered.extend(os.read(output_read, min(4096, 48000 - len(buffered))))
                    if len(buffered) == 48000:
                        started = time.monotonic()
                        deadline = started + 0.05
                        os.write(result_write, b'R')
                    continue
                now = time.monotonic()
                while now >= deadline:
                    levels.append(len(buffered))
                    underruns += len(buffered) < 9600
                    played.extend(buffered[:9600])
                    del buffered[:9600]
                    deadline += 0.05
                if len(buffered) < 48000 and select.select(
                        [output_read], [], [], max(0, deadline - time.monotonic()))[0]:
                    data = os.read(output_read, min(4096, 48000 - len(buffered)))
                    if not data:
                        break
                    buffered.extend(data)
                else:
                    time.sleep(max(0, min(0.001, deadline - time.monotonic())))

            def trim_idle(data):
                frames = [data[i:i + 4] for i in range(0, len(data), 4)]
                nonzero = [i for i, frame in enumerate(frames) if frame != bytes(4)]
                return b''.join(frames[nonzero[0]:nonzero[-1] + 1]) if nonzero else b''

            active = trim_idle(played)
            reference = trim_idle(expected)
            os.write(result_write, json.dumps({'underruns': underruns,
                'minimum_frames': min(levels) // 4, 'periods': len(levels),
                'waveform_matches': active == reference,
                'active_frames': len(active) // 4,
                'expected_frames': len(reference) // 4}).encode())
            # Keep the PCM pipe readable until parent cleanup. The fixed
            # 6.5-second measurement above is unchanged; slow scoring must
            # not manufacture a BrokenPipe failure after measurement ends.
            while os.read(output_read, 16384):
                pass
            os._exit(0)
        os.close(source_write)
        os.close(output_read)
        os.close(result_write)
        os.close(activate_read)
        os.set_blocking(output_write, False)
        monitor = audio.DesktopMonitor(SimpleNamespace(
            stdout=os.fdopen(source_read, 'rb', buffering=0), poll=lambda: None),
            ordinary=True, desktop_peak=4000)
        monitor.forward = False
        pcm = audio.OwnedPCM.__new__(audio.OwnedPCM)
        pcm.process = SimpleNamespace(stdin=os.fdopen(output_write, 'wb', buffering=0))
        pcm.stop, pcm.pending = threading.Event(), queue.Queue()
        pcm.error, pcm.source = None, monitor
        pcm.source_lock = threading.Lock()
        pcm.feed_stats = {'inserted_gap_events': 0, 'inserted_gap_frames': 0}
        feeder = threading.Thread(target=pcm.feed)
        terminate_child = os.kill
        with patch.object(audio.os, 'kill') as abort:
            monitor.thread.start()
            feeder.start()
            try:
                self.assertTrue(select.select([result_read], [], [], 2)[0])
                self.assertEqual(os.read(result_read, 1), b'R')
                monitor.forward = True
                os.write(activate_write, b'G')
                # Let the finite two-second waveform drain fully before scoring.
                time.sleep(3)
                monitor.forward = False
                for _ in range(3):
                    acoustic.score_phase([0] * 150000, [0] * 96000, [440, 660])
                self.assertTrue(select.select([result_read], [], [], 6)[0])
                result = json.loads(os.read(result_read, 4096))
                self.assertEqual(result['underruns'], 0, result)
                self.assertGreaterEqual(result['minimum_frames'], 2400, result)
                self.assertGreaterEqual(result['periods'], 125)
                # Compare the whole waveform, including its zero crossings:
                # filtering out inserted zero frames would hide timing damage.
                self.assertTrue(result['waveform_matches'], result)
                self.assertEqual(result['active_frames'], result['expected_frames'])
                self.assertEqual(pcm.feed_stats['inserted_gap_frames'], 0)
                self.assertIsNone(monitor.error)
                self.assertIsNone(pcm.error)
                abort.assert_not_called()
            finally:
                pcm.stop.set()
                monitor.stop.set()
                feeder.join(timeout=2)
                monitor.thread.join(timeout=2)
                pcm.process.stdin.close()
                monitor.process.stdout.close()
                os.close(result_read)
                os.close(activate_write)
                for pid in (producer, consumer):
                    try:
                        terminate_child(pid, audio.signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    os.waitpid(pid, 0)

    def test_recording_close_restores_mixer_before_handoff_and_only_once(self):
        events = []
        capture = Mock()
        capture.close.side_effect = lambda: events.append('capture closed')
        capture.process.poll.return_value = 0
        saved = [(['amixer', 'restore', 'first'], 'first'),
                 (['amixer', 'restore', 'second'], 'second')]
        report = {'capture': {'log': '', 'error': None}}

        def restore(command, **kwargs):
            events.append(command[-1])
            return SimpleNamespace(returncode=0, stderr='')

        with patch.object(audio, 'read_text', return_value='closed'), \
                patch.object(audio.subprocess, 'run', side_effect=restore):
            audio.finish_recording(capture, report, saved)
            audio.restore_microphone_mixer(report, saved)
        self.assertEqual(events, ['capture closed', 'second', 'first'])
        self.assertTrue(report['recording_closed'])
        self.assertEqual(saved, [])
        self.assertEqual(len(report['microphone_mixer_restore']), 2)

    def test_failed_capture_close_still_restores_route_and_blocks_handoff(self):
        capture = Mock()
        capture.close.side_effect = RuntimeError('capture close failed')
        saved = [(['amixer', 'restore'], 'route')]
        report = {}
        with patch.object(audio.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr='')) as restore:
            with self.assertRaisesRegex(RuntimeError, 'capture close failed'):
                audio.finish_recording(capture, report, saved)
        restore.assert_called_once()
        self.assertNotIn('recording_closed', report)
        self.assertEqual(saved, [])

    def test_serve_refuses_handoff_while_microphone_is_open(self):
        report = {'desktop': {'acoustic_passed': True},
                  'public_desktop': {'acoustic_passed': True}}
        pcm, graph = Mock(), Mock()
        with self.assertRaisesRegex(RuntimeError, 'closed microphone'):
            audio.serve_desktop(SimpleNamespace(), report, pcm, graph, {}, {})
        pcm.settle.assert_not_called()

    def test_untimed_serve_survives_eight_hours_until_signal_and_retains_pcm(self):
        report = {'action': 'serve', 'desktop': {'acoustic_passed': True},
                  'public_desktop': {'acoustic_passed': True}, 'recording_closed': True,
                  'before': {'boot_id': 'test-boot', 'release': 'test-kernel'}}
        pcm, graph = Mock(), Mock()
        pcm.process.pid = 123
        pcm.feed_stats = {'inserted_gap_events': 2, 'inserted_gap_frames': 480}
        monitor = graph.monitor
        monitor.input_peak, monitor.peak = 32768, 1433
        monitor.max_interarrival_seconds = 0.015
        handlers = {}

        def handler(signum, callback):
            previous = handlers.get(signum)
            handlers[signum] = callback
            return previous

        class StopAfterReady:
            stopped = False
            calls = 0

            def wait(self, seconds):
                ready = json.loads((output / 'serve-ready.json').read_text())
                self_test.assertTrue(ready['recording_closed'])
                self_test.assertTrue(ready['public_acoustic_passed'])
                self_test.assertEqual(ready['pcm_pid'], 123)
                self_test.assertIsNone(ready['deadline_monotonic'])
                self_test.assertIsNone(ready['deadline_utc'])
                self.calls += 1
                if self.calls == 1:
                    return False  # A nine-hour clock jump must not stop audio.
                handlers[audio.signal.SIGTERM](audio.signal.SIGTERM, None)
                return self.stopped

            def set(self):
                self.stopped = True

            def is_set(self):
                return self.stopped

        self_test = self
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            args = SimpleNamespace(output=output, serve_seconds=0, desktop_peak=1433)
            with patch.object(audio.threading, 'Event', StopAfterReady), \
                    patch.object(audio.signal, 'signal', side_effect=handler), \
                    patch.object(audio.time, 'monotonic', side_effect=[0, 32400, 32401]), \
                    patch.object(audio, 'check_stereo'):
                audio.serve_desktop(args, report, pcm, graph, {}, {})
        self.assertEqual(report['serve']['stop_reason'], 'SIGTERM')
        self.assertEqual(report['serve']['output_peak'], 1433)
        self.assertTrue(monitor.forward)
        pcm.close.assert_not_called()  # Caller performs attached-amplifier close.
        pcm.set_source.assert_called_once_with(None)
        monitor.close.assert_called_once()

    def test_serve_monitor_fault_does_not_take_normal_close_path(self):
        report = {'desktop': {'acoustic_passed': True},
                  'public_desktop': {'acoustic_passed': True}, 'recording_closed': True}
        pcm, graph = Mock(), Mock()
        graph.monitor.healthy.side_effect = RuntimeError('monitor failed')
        with self.assertRaisesRegex(RuntimeError, 'monitor failed'):
            audio.serve_desktop(SimpleNamespace(), report, pcm, graph, {}, {})
        # The initializer now receives the exception and parks before cleanup.
        pcm.set_source.assert_not_called()
        pcm.close.assert_not_called()
        graph.monitor.close.assert_not_called()

    def test_public_route_scores_fresh_quiet_and_fullscale_input_before_handoff(self):
        import acoustic

        counter = [150000]
        capture, pcm, graph = Mock(), Mock(), Mock()
        capture.mark.side_effect = lambda: counter[0]
        capture.wait_frames.side_effect = lambda frame: counter.__setitem__(0, max(frame, counter[0]))
        capture.samples.side_effect = lambda begin, end: (begin, end)
        pcm.settle.side_effect = lambda seconds: counter.__setitem__(0, counter[0] + round(seconds * 48000))
        graph.public_restore = [('pactl', 'set-sink-volume', 'spx_speakers', '25559', '25559')]
        graph.monitor.peak = 4000
        starts = []

        def play(payload, name):
            starts.append(counter[0])
            graph.monitor.forward = True
            graph.monitor.input_peak = 32767
            counter[0] += 96000

        graph.play.side_effect = play
        report = {}
        def score_public(*unused):
            self.assertFalse(graph.monitor.forward)
            return {'passed': True, 'reason': 'detected'}

        with patch.object(audio.threading, 'Timer'), \
                patch.object(audio, 'tone', return_value=b'full-scale input') as tone, \
                patch.object(acoustic, 'score_phase', side_effect=score_public) as score:
            audio.verify_public_playback(report, pcm, graph, capture, desktop_peak=4000)
        tone.assert_called_once_with({0, 1}, amplitude=32767)
        graph.connect_public.assert_called_once_with(pcm, desktop_peak=4000)
        self.assertEqual(score.call_args.args[1], (starts[0] - 96000, starts[0]))
        self.assertEqual(score.call_args.args[2], [440, 660])
        self.assertEqual(graph.require_public_idle.call_count, 4)
        self.assertFalse(graph.monitor.forward)  # Remains quiet through mic teardown.
        self.assertTrue(report['public_desktop']['acoustic_passed'])
        self.assertEqual(report['public_desktop']['gain'], 4000 / 32768)
        self.assertEqual(report['public_desktop']['output_peak_limit'], 4000)
        self.assertEqual(report['public_desktop']['public_volume']['current'], [65536, 65536])
        self.assertEqual(report['public_desktop']['public_volume']['prior'], ['25559', '25559'])
        capture.close.assert_not_called()  # Caller closes only after this score succeeds.

    def test_public_deadline_allows_setup_and_retains_interrupted_score_bounds(self):
        import acoustic

        for outcome in ('pass', 'deadline', 'external signal'):
            with self.subTest(outcome=outcome):
                clock, timers = [0.0], []
                report = {}
                capture, pcm, graph = Mock(), Mock(), Mock()

                class Timer:
                    def __init__(self, seconds, callback):
                        self.end, self.callback = clock[0] + seconds, callback
                        self.canceled = False

                    def start(self):
                        timers.append(self)

                    def cancel(self):
                        self.canceled = True

                def advance(seconds):
                    end = clock[0] + seconds
                    for timer in timers:
                        if not timer.canceled and timer.end <= end:
                            clock[0] = timer.end
                            timer.callback()
                    clock[0] = end

                capture.mark.side_effect = lambda: 150000 + round(clock[0] * 48000)
                capture.wait_frames.side_effect = lambda frame: advance(
                    max(0, (frame - capture.mark()) / 48000))
                capture.samples.side_effect = lambda begin, end: (begin, end)
                pcm.settle.side_effect = advance
                graph.connect_public.side_effect = lambda *args, **kwargs: advance(12)
                graph.public_restore = [('pactl', 'set-sink-volume', 'spx_speakers',
                                         '65536', '65536')]
                graph.monitor.peak = 1433

                def play(*unused):
                    graph.monitor.forward = True
                    graph.monitor.input_peak = 32767
                    advance(2)

                def score(samples, reference, expected):
                    evidence = report['public_desktop']
                    self.assertFalse(graph.monitor.forward)
                    self.assertEqual(samples, (evidence['start_frame'], evidence['end_frame']))
                    self.assertEqual(reference, (evidence['reference_start_frame'],
                                                 evidence['reference_end_frame']))
                    if outcome == 'external signal':
                        raise RuntimeError('Interrupted by signal 15')
                    advance(25 if outcome == 'deadline' else 4)
                    return {'passed': True, 'reason': 'detected'}

                graph.play.side_effect = play
                with patch.object(audio.threading, 'Timer', Timer), \
                        patch.object(audio.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(audio, 'tone', return_value=b'test PCM'), \
                        patch.object(acoustic, 'score_phase', side_effect=score), \
                        patch.object(audio.os, 'kill', side_effect=RuntimeError(
                            'Interrupted by signal 15')) as kill:
                    if outcome == 'pass':
                        audio.verify_public_playback(report, pcm, graph, capture)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'signal 15'):
                            audio.verify_public_playback(report, pcm, graph, capture)
                evidence = report['public_desktop']
                self.assertTrue(timers[0].canceled)
                self.assertEqual(evidence['deadline_expired'], outcome == 'deadline')
                self.assertEqual(evidence['acoustic_passed'], outcome == 'pass')
                self.assertGreater(evidence['seconds'], 15)
                self.assertEqual(evidence['output_peak_limit'], 1433)
                if outcome == 'deadline':
                    kill.assert_called_once_with(os.getpid(), audio.signal.SIGTERM)
                    self.assertEqual(evidence['timeout_phase'], 'scoring')
                    self.assertEqual(evidence['timeout_seconds'], 30)
                    self.assertIn('deadline exceeded', evidence['timeout_reason'])
                else:
                    kill.assert_not_called()
                    self.assertNotIn('timeout_reason', evidence)

    def test_serve_permission_and_duration_bounds(self):
        args = SimpleNamespace(action='serve', allow_amp_power=True,
                               allow_playback=True, allow_capture=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'allow-capture'):
                audio.initialize(args, {})
        self.assertEqual(audio.serve_duration('0'), 0)
        self.assertEqual(audio.serve_duration('1'), 1)
        self.assertEqual(audio.serve_duration('86400'), 86400)
        for value in ('-1', '86401'):
            with self.assertRaises(audio.argparse.ArgumentTypeError):
                audio.serve_duration(value)

    def test_desktop_peak_rejects_out_of_range_and_nonserve_use(self):
        for value in ('1432', '12001'):
            with self.assertRaises(audio.argparse.ArgumentTypeError):
                audio.desktop_peak_limit(value)
            with self.assertRaisesRegex(RuntimeError, 'between 1433 and 12000'):
                audio.DesktopMonitor(None, ordinary=True, desktop_peak=int(value))
        self.assertEqual(audio.desktop_peak_limit('1433'), 1433)
        self.assertEqual(audio.desktop_peak_limit('12000'), 12000)
        with self.assertRaisesRegex(RuntimeError, 'Only the ordinary'):
            audio.DesktopMonitor(None, desktop_peak=4000)
        with patch.object(audio.sys, 'argv', ['audio.py', 'desktop', '--desktop-peak', '4000']), \
                patch.object(audio.sys, 'stderr', io.StringIO()), \
                patch.object(audio, 'initialize') as initialize:
            with self.assertRaises(SystemExit) as stopped:
                audio.main()
        self.assertEqual(stopped.exception.code, 2)
        initialize.assert_not_called()

    def test_source_detach_waits_for_inflight_monitor_use(self):
        reader, writer = os.pipe()
        pcm = audio.OwnedPCM.__new__(audio.OwnedPCM)
        pcm.process = SimpleNamespace(stdin=os.fdopen(writer, 'wb', buffering=0))
        pcm.stop = threading.Event()
        pcm.pending = queue.Queue()
        pcm.error = None
        pcm.source_lock = threading.Lock()
        entered, release, detached = (threading.Event() for _ in range(3))

        def healthy():
            self.assertFalse(detached.is_set())
            entered.set()
            release.wait(timeout=2)

        source = SimpleNamespace(healthy=healthy, blocks=queue.Queue(), forward=True)
        pcm.feed_stats = {'inserted_gap_events': 0, 'inserted_gap_frames': 0}
        source.blocks.put(bytes(960))
        pcm.source = source
        feeder = threading.Thread(target=pcm.feed)
        detach = threading.Thread(target=lambda: (pcm.set_source(None), detached.set()))
        feeder.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            detach.start()
            self.assertFalse(detached.wait(timeout=0.05))
            release.set()
            self.assertTrue(detached.wait(timeout=2))
            self.assertIsNone(pcm.source)
        finally:
            release.set()
            pcm.stop.set()
            feeder.join(timeout=2)
            detach.join(timeout=2)
            pcm.process.stdin.close()
            os.close(reader)
        self.assertFalse(feeder.is_alive())
        self.assertIsNone(pcm.error)

    def test_graph_cleanup_restores_overrides_despite_stop_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'pipewire.service.d'
            directory.mkdir()
            override = directory / 'zz-spx-desktop.conf'
            override.write_text('[Unit]\nConditionKernelCommandLine=\n')
            foreign = directory / 'user.conf'
            foreign.write_text('keep me')
            graph = audio.DesktopGraph.__new__(audio.DesktopGraph)
            graph.processes, graph.monitor, graph.module = [], None, None
            graph.overrides, graph.directories = [override], [directory]
            graph.started, graph.report = True, {}
            graph.run = Mock(side_effect=[RuntimeError('stop failed'), ''])
            with self.assertRaisesRegex(RuntimeError, 'stop failed'):
                graph.close()
            self.assertFalse(override.exists())
            self.assertEqual(foreign.read_text(), 'keep me')
            self.assertEqual(graph.run.call_args.args, ('systemctl', '--user', 'daemon-reload'))
            self.assertFalse(graph.report['graph_restored'])

    def test_desktop_requires_capture_permission_before_hardware(self):
        args = SimpleNamespace(action='desktop', allow_amp_power=True,
                               allow_playback=True, allow_capture=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'allow-capture'):
                audio.initialize(args, {})

    def test_desktop_teardown_waits_for_empty_fifo_with_slaves_attached(self):
        clean = {'SLV_STATUS': 0x14, 'GPIO_VAL': 0x1e, 'FIFO_STATUS': 0,
                 'DP1_B0': 0x107, 'DP1_B1': 0x107,
                 'DP4_B0': 0x607, 'DP4_B1': 0x607}
        codec = {'STREAM_CONFIGURED': 0, 'STREAM_ENABLED': 0,
                 'DAC_PREPARED': 0, 'SHADOW_PA_ENABLE': 0x7d}
        report = {}
        with patch.object(audio, 'state', side_effect=[dict(clean, FIFO_STATUS=0x100), clean]), \
                patch.object(audio, 'playback_state', return_value=codec), \
                patch.object(audio.time, 'sleep'), \
                patch.object(audio, 'assert_pcm_idle') as idle:
            audio.check_desktop_teardown({3: 'left', 4: 'right'}, report)
        self.assertTrue(report['teardown']['passed'])
        self.assertEqual(len(report['teardown']['samples']), 2)
        idle.assert_called_once()
        with patch.object(audio, 'state', return_value=dict(clean, FIFO_STATUS=0x100)), \
                patch.object(audio, 'playback_state', return_value=codec), \
                patch.object(audio.time, 'monotonic', side_effect=[0, 6]):
            with self.assertRaisesRegex(RuntimeError, 'did not close cleanly'):
                audio.check_desktop_teardown({3: 'left', 4: 'right'}, {})

    def test_desktop_uses_current_quiet_before_every_application(self):
        import acoustic

        # Model a continuous capture whose frame counter advances during both
        # silence and applications. A startup reference cannot satisfy this:
        # every scored reference must precede its own app by exactly two seconds.
        capture = Mock()
        counter = [150000]
        capture.mark.side_effect = lambda: counter[0]
        capture.wait_frames.side_effect = lambda frame: counter.__setitem__(0, max(frame, counter[0]))
        capture.samples.side_effect = lambda begin, end: (begin, end)
        pcm = Mock()
        pcm.settle.side_effect = lambda seconds: counter.__setitem__(0, counter[0] + round(seconds * 48000))
        graph = Mock()
        graph.monitor.peak = 1433
        starts = []

        def play(data, name):
            starts.append(counter[0])
            counter[0] += 96000

        graph.play.side_effect = play
        report = {}
        with patch.object(audio, 'DesktopGraph', return_value=graph), \
                patch.object(audio, 'check_stereo'), \
                patch.object(audio.threading, 'Timer'), \
                patch.object(audio, 'tone', return_value=b'finite audio'), \
                patch.object(acoustic, 'score_phase', return_value={'passed': True, 'reason': 'tones detected'}) as score:
            audio.desktop_playback(SimpleNamespace(desktop_user='test'), report,
                                   pcm, {}, {}, capture, [])
        self.assertEqual(len(starts), 4)
        self.assertEqual(report['desktop']['idle_seconds'], 5)
        for call, start, phase in zip(score.call_args_list, starts, report['desktop']['phases']):
            self.assertEqual(call.args[1], (start - 96000, start))
            self.assertEqual(phase['reference_end_frame'], phase['start_frame'])
            self.assertGreaterEqual(phase['reference_start_frame'], 150000)
        self.assertTrue(report['desktop']['acoustic_passed'])


class PlaybackReopenTests(unittest.TestCase):
    def test_failed_acoustic_cycle_keeps_its_own_pcm_and_phase(self):
        capture = Mock()
        capture.process.pid = 77
        capture.mark.return_value = 48000
        report = {'capture': {'phases': []}, 'after_playback': {'stale': True}}

        def fail(*args):
            report['pcm'] = {'pid': 88}
            report['capture']['phases'].append({'name': 'cycle-1-left', 'passed': False})
            raise RuntimeError('acoustic failure')

        with patch.object(audio, 'devices', return_value=[]), \
                patch.object(audio, 'listen', side_effect=fail), \
                patch.object(audio, 'check_desktop_teardown') as teardown:
            with self.assertRaisesRegex(RuntimeError, 'acoustic failure'):
                audio.playback_reopen(SimpleNamespace(action='reopen'), report, [], capture, [])
        cycle = report['reopen']['cycles'][0]
        self.assertEqual(cycle['pcm']['pid'], 88)
        self.assertEqual(cycle['acoustic_phases'][0]['name'], 'cycle-1-left')
        self.assertNotIn('after_playback', cycle)
        self.assertNotIn('after_playback', report)
        self.assertFalse(cycle['passed'])
        teardown.assert_not_called()
        capture.close.assert_not_called()

    def test_failed_attached_teardown_stops_before_second_pcm(self):
        # A failed hardware close must leave the microphone open for outer
        # park-first cleanup, and must never open another playback session.
        capture = Mock()
        capture.process.pid = 77
        capture.mark.return_value = 48000
        pcm = Mock()
        pcm.status = Path('/test/pcm/status')
        pcm.close.return_value = ''
        report = {'capture': {'phases': []}}
        holders = []

        def listen(*args):
            holders.append(pcm)
            report.update(pcm={'pid': 88}, reopen_reference={}, late_initialization=[])

        with patch.object(audio, 'devices', return_value=[]), \
                patch.object(audio, 'listen', side_effect=listen) as play, \
                patch.object(audio, 'read_text', return_value='closed'), \
                patch.object(audio, 'check_desktop_teardown',
                             side_effect=RuntimeError('teardown failed')):
            with self.assertRaisesRegex(RuntimeError, 'teardown failed'):
                audio.playback_reopen(SimpleNamespace(action='reopen'), report,
                                      holders, capture, [])
        play.assert_called_once()
        pcm.close.assert_called_once()
        capture.close.assert_not_called()
        self.assertEqual(holders, [])
        self.assertFalse(report['reopen']['passed'])
        self.assertEqual(len(report['reopen']['cycles']), 1)


class DesktopMicrophoneTests(unittest.TestCase):
    def test_actual_monitor_close_is_idempotent_without_recording_log(self):
        reader, writer = os.pipe()
        process = SimpleNamespace(stdout=os.fdopen(reader, 'rb', buffering=0),
                                  poll=lambda: 0)
        monitor = audio.DesktopMonitor(process)
        self.assertFalse(hasattr(monitor, 'log'))
        monitor.thread.start()
        try:
            monitor.close()
            monitor.close()
            self.assertTrue(monitor.closed)
            self.assertTrue(monitor.stop.is_set())
            self.assertFalse(monitor.thread.is_alive())
            self.assertTrue(process.stdout.closed)
        finally:
            monitor.stop.set()
            monitor.thread.join(timeout=1)
            process.stdout.close()
            os.close(writer)

    def test_unexpected_graph_failure_does_not_skip_capture_mixer_or_signal_cleanup(self):
        report, graph, capture, timer = {}, Mock(), Mock(), Mock()
        graph.close.side_effect = AttributeError('unexpected graph failure')
        saved = [('saved control', 'name')]
        with patch.object(audio, 'restore_microphone_mixer') as restore, \
                patch.object(audio.signal, 'signal') as reset:
            audio.cleanup_audio_consumers(report, [], [graph], capture, saved, {15: 'handler'}, timer)
        capture.close.assert_called_once()
        timer.cancel.assert_called_once()
        restore.assert_called_once_with(report, saved)
        reset.assert_called_once_with(15, 'handler')
        self.assertIn('AttributeError', report['cleanup_errors'][0])
        self.assertIn('unexpected graph failure', report['desktop']['cleanup_error'])

    def test_main_saves_partial_evidence_after_unexpected_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            def fail(args, report):
                report['desktop'] = {'clients': [{'passed': True}]}
                raise AttributeError('unexpected cleanup failure')
            argv = ['audio.py', 'desktop-mic', '--output', directory]
            with patch.object(audio.sys, 'argv', argv), \
                    patch.object(audio, 'initialize', side_effect=fail), \
                    patch.object(audio, 'open', return_value=io.StringIO(), create=True), \
                    patch.object(audio.fcntl, 'flock'), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audio.main(), 1)
            result = json.loads((Path(directory) / 'desktop-mic-result.json').read_text())
            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'], 'AttributeError')
            self.assertTrue(result['desktop']['clients'][0]['passed'])
            self.assertIn('unexpected cleanup failure', result['error'])

    def test_default_client_route_rejects_another_source(self):
        graph = Mock()
        report = {}
        source = audio.DesktopMicSource(graph, Mock(), report)
        source.source_id = 12
        output = {'index': 3, 'source': 19, 'properties': {'application.name': 'owned-client'}}
        graph.run.side_effect = [source.name, json.dumps([output])]
        with self.assertRaisesRegex(RuntimeError, 'another source'):
            source.require_client_route('owned-client')
        self.assertNotIn('routes', report)
        output['source'] = '12'
        graph.run.side_effect = [source.name, json.dumps([output])]
        self.assertTrue(source.require_client_route('owned-client'))
        self.assertEqual(report['routes'][0]['source_output'], 3)

    def test_source_restore_failure_still_unloads_owned_module_and_fifo(self):
        graph = Mock()
        report = {}
        source = audio.DesktopMicSource(graph, Mock(), report)
        with tempfile.TemporaryDirectory() as directory:
            source.directory = Path(directory) / 'owned'
            source.directory.mkdir()
            source.fifo = source.directory / 'capture'
            os.mkfifo(source.fifo, 0o600)
            source.previous, source.module = {'type': 'Spa:String:JSON', 'value': {'name': 'original'}}, '41'
            def run(*command):
                if command[0] == 'pw-metadata':
                    raise RuntimeError('restore failed')
            graph.run.side_effect = run
            with self.assertRaisesRegex(RuntimeError, 'restore failed'):
                source.close()
            self.assertEqual(graph.run.call_args_list[0].args,
                             ('pactl', 'unload-module', '41'))
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse(report['restored'])

    def test_configured_source_snapshot_preserves_absence_and_unavailable_preference(self):
        graph = Mock()
        def dump(entries):
            return json.dumps([{'type': 'PipeWire:Interface:Metadata',
                                'props': {'metadata.name': 'default'}, 'metadata': entries}])
        sink = {'subject': 0, 'key': 'default.configured.audio.sink',
                'type': 'Spa:String:JSON', 'value': {'name': 'existing_sink'}}
        graph.run.return_value = dump([sink])
        self.assertIsNone(audio.configured_default_source(graph))
        for name in ('existing_source', 'unavailable_source'):
            value = {'name': name, 'retained': 'exact preference'}
            graph.run.return_value = dump([sink, {'subject': 0,
                'key': audio.DEFAULT_SOURCE_KEY, 'type': 'Spa:String:JSON', 'value': value}])
            self.assertEqual(audio.configured_default_source(graph),
                             {'type': 'Spa:String:JSON', 'value': value})
        graph.run.assert_called_with('pw-dump')

    def test_source_cleanup_restores_metadata_after_unloading_without_effective_name_check(self):
        for previous in (None, {'type': 'Spa:String:JSON', 'value': {'name': 'existing'}},
                         {'type': 'Spa:String:JSON', 'value': {'name': 'unavailable'}}):
            with self.subTest(previous=previous):
                graph = Mock()
                entries = [] if previous is None else [dict(subject=0,
                    key=audio.DEFAULT_SOURCE_KEY, **previous)]
                dump = json.dumps([{'type': 'PipeWire:Interface:Metadata',
                    'props': {'metadata.name': 'default'}, 'metadata': entries}])
                graph.run.return_value = dump
                report = {}
                source = audio.DesktopMicSource(graph, Mock(), report, previous)
                source.module = '41'
                source.close()
                calls = [call.args for call in graph.run.call_args_list]
                self.assertEqual(calls[0], ('pactl', 'unload-module', '41'))
                if previous is None:
                    self.assertEqual(calls[1], ('pw-metadata', '-n', 'default', '-d',
                                               '0', audio.DEFAULT_SOURCE_KEY))
                else:
                    self.assertEqual(calls[1], ('pw-metadata', '-n', 'default', '0',
                        audio.DEFAULT_SOURCE_KEY, json.dumps(previous['value']), previous['type']))
                self.assertEqual(calls[2:], [('pw-dump',)])
                self.assertTrue(report['restored'])
                source.close()  # No second restoration after successful cleanup.
                self.assertEqual(len(graph.run.call_args_list), 3)

    def test_source_restore_waits_for_metadata_and_times_out_if_not_restored(self):
        graph = Mock()
        previous = {'type': 'Spa:String:JSON', 'value': {'name': 'unavailable'}}
        with patch.object(audio, 'configured_default_source', side_effect=[None, previous]), \
                patch.object(audio.time, 'sleep') as sleep:
            audio.restore_default_source(graph, previous)
        sleep.assert_called_once_with(0.05)
        with patch.object(audio, 'configured_default_source', return_value=None), \
                patch.object(audio.time, 'monotonic', side_effect=[0, 4]):
            with self.assertRaisesRegex(RuntimeError, 'not restored'):
                audio.restore_default_source(graph, previous)

    def test_two_clients_keep_hardware_owners_open_even_on_second_failure(self):
        import acoustic
        capture = Mock(status=Path('/unused-capture-status'))
        owners = 'state: RUNNING\nowner_pid: 123\ntrigger_time: 14.567\n'
        pcm = Mock()
        pcm.healthy.return_value = owners
        graph, source = Mock(), Mock()
        source.require_client_route.return_value = True
        clients = []
        def recording(*args):
            client = Mock()
            client.process.pid = 200 + len(clients)
            client.mark.return_value = 144000
            client.samples.return_value = []
            clients.append(client)
            return client
        report, holders = {}, []
        scores = [{'passed': True, 'reason': 'tone detected'},
                  {'passed': False, 'reason': 'missing tone'}]
        with patch.object(audio, 'DesktopGraph', return_value=graph), \
                patch.object(audio, 'DesktopMicSource', return_value=source), \
                patch.object(audio, 'DesktopRecording', side_effect=recording), \
                patch.object(audio, 'read_text', return_value=owners), \
                patch.object(audio, 'check_stereo'), \
                patch.object(audio.threading, 'Timer'), \
                patch.object(acoustic, 'score_phase', side_effect=scores):
            with self.assertRaisesRegex(RuntimeError, 'missing tone'):
                audio.desktop_microphone(SimpleNamespace(desktop_user='test'), report,
                                         pcm, {}, {}, capture, holders)
        self.assertEqual(holders, [graph])  # Outer initializer owns failure cleanup.
        self.assertEqual(len(clients), 2)
        for client in clients:
            client.close.assert_called_once()
        capture.close.assert_not_called()
        pcm.close.assert_not_called()
        self.assertFalse(report['desktop']['microphone_client_passed'])
        self.assertTrue(report['desktop']['clients'][0]['passed'])
        self.assertFalse(report['desktop']['clients'][1]['passed'])

    def test_capture_reopen_cli_rejects_other_actions_before_hardware(self):
        for action in ('plan', 'feedback', 'capture', 'reopen', 'serve'):
            with self.subTest(action=action), \
                    patch.object(audio.sys, 'argv', ['audio.py', action, '--capture-reopen']), \
                    patch.object(audio.sys, 'stderr', io.StringIO()), \
                    patch.object(audio, 'initialize') as initialize:
                with self.assertRaises(SystemExit) as stopped:
                    audio.main()
                self.assertEqual(stopped.exception.code, 2)
                initialize.assert_not_called()

    def test_owned_capture_reopen_keeps_identity_evidence_and_remaining_budget(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        old = {'pid': 123, 'closed_status': 'closed', 'log': '', 'error': None}
        capture.card, capture.directory = 0, Path('/unused')
        capture.report = {'capture': old}
        capture.maximum_seconds, capture.started, capture.retain_recording = 60, 100, False
        reopened = {'pid': 456}
        def initialize(same, card, report, directory, **kwargs):
            self.assertIs(same, capture)
            self.assertEqual(kwargs, dict(maximum_seconds=35, retain_recording=False))
            report['capture'] = reopened
        evidence = {}
        with patch.object(audio.time, 'monotonic', return_value=125), \
                patch.object(capture, 'close') as close, \
                patch.object(capture, 'baseline', side_effect=RuntimeError('silent baseline')), \
                patch.object(audio.OwnedCapture, '__init__', autospec=True, side_effect=initialize):
            with self.assertRaisesRegex(RuntimeError, 'silent baseline'):
                capture.reopen(evidence)
        close.assert_called_once()
        self.assertIs(evidence['original_capture'], old)
        self.assertIs(evidence['reopened_capture'], reopened)
        self.assertIs(capture.report['capture'], reopened)

    def test_reopen_start_failure_closes_log_without_reclosing_old_process(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        old_process = Mock()
        capture.process = old_process
        log = io.BytesIO()
        with patch.object(audio.tempfile, 'TemporaryFile', return_value=log), \
                patch.object(audio.subprocess, 'Popen', side_effect=OSError('arecord failed')):
            with self.assertRaisesRegex(OSError, 'arecord failed'):
                capture.__init__(0, {'microphone_source': 'DMIC1'}, Path('/unused'),
                                 maximum_seconds=20, retain_recording=False)
        self.assertTrue(log.closed)
        capture.close()
        old_process.terminate.assert_not_called()
        old_process.stdout.close.assert_not_called()

    def test_capture_close_is_idempotent_after_successful_stop(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        capture.closed = False
        capture.stop, capture.thread, capture.process = Mock(), Mock(), Mock()
        capture.process.poll.return_value = None
        capture.process.returncode = -15
        capture.log = io.BytesIO(b'')
        capture.report, capture.error = {'capture': {}}, None
        capture.mutex, capture.raw = threading.Lock(), bytearray()
        capture.samples = Mock(return_value=audio.array('h'))
        capture.retain_recording, capture.status = False, Path('/unused')
        with patch.object(audio, 'read_text', return_value='closed'):
            capture.close()
            capture.close()
        capture.process.terminate.assert_called_once()
        capture.process.stdout.close.assert_called_once()
        self.assertEqual(capture.report['capture']['frames'], 0)
        self.assertIsNone(capture.report['capture']['recording'])

    def test_third_default_client_reopens_capture_only_and_retains_failures(self):
        import acoustic
        old = 'state: RUNNING\nowner_pid: 123\ntrigger_time: 14.567\n'
        new = 'state: RUNNING\nowner_pid: 456\ntrigger_time: 44.567\n'
        for failure in (None, 'baseline', 'third-tone'):
            with self.subTest(failure=failure):
                state, events, clients = {'reopened': False}, [], []
                capture = Mock(status=Path('/unused-capture'))
                def reopen(evidence):
                    events.append('capture-reopen')
                    state['reopened'] = True
                    evidence['original_capture'] = {'pid': 123}
                    evidence['reopened_capture'] = {'pid': 456}
                    if failure == 'baseline':
                        raise RuntimeError('silent reopened capture')
                capture.reopen.side_effect = reopen
                pcm, graph, source, second = Mock(), Mock(), Mock(), Mock()
                pcm.healthy.return_value = old
                source.source_id, second.source_id = 79, 91
                source.require_client_route.return_value = True
                second.require_client_route.return_value = True
                source.close.side_effect = lambda: events.append('source-close')
                def recording(*args):
                    client = Mock()
                    client.process.pid = 200 + len(clients)
                    client.mark.return_value = 144000
                    client.samples.return_value = []
                    clients.append(client)
                    return client
                scores = [{'passed': True, 'reason': ''}] * 2 + [
                    {'passed': failure != 'third-tone', 'reason': 'missing third tone'}]
                report, holders = {}, []
                with patch.object(audio, 'DesktopGraph', return_value=graph), \
                        patch.object(audio, 'DesktopMicSource', side_effect=[source, second]), \
                        patch.object(audio, 'DesktopRecording', side_effect=recording), \
                        patch.object(audio, 'read_text', side_effect=lambda _: new if state['reopened'] else old), \
                        patch.object(audio, 'check_stereo'), \
                        patch.object(audio.threading, 'Timer'), \
                        patch.object(acoustic, 'score_phase', side_effect=scores):
                    args = SimpleNamespace(desktop_user='test', capture_reopen=True)
                    if failure:
                        with self.assertRaises(RuntimeError):
                            audio.desktop_microphone(args, report, pcm, {}, {}, capture, holders)
                    else:
                        audio.desktop_microphone(args, report, pcm, {}, {}, capture, holders)
                evidence = report['desktop']
                self.assertEqual(events, ['source-close', 'capture-reopen'])
                self.assertTrue(evidence['initial_clients_passed'])
                self.assertTrue(all(c['passed'] for c in evidence['clients'][:2]))
                self.assertEqual(evidence['capture_reopen']['passed'], failure is None)
                if failure:
                    self.assertIn('error', evidence['capture_reopen'])
                self.assertEqual(len(clients), 2 if failure == 'baseline' else 3)
                for client in clients:
                    client.close.assert_called_once()
                capture.close.assert_not_called()  # Same object is left to outer cleanup.
                pcm.close.assert_not_called()
                self.assertIs(graph.microphone, None if failure == 'baseline' else second)
                if failure != 'baseline':
                    self.assertEqual(evidence['clients'][2]['source_index'], 91)

    def test_desktop_mic_requires_capture_before_any_hardware(self):
        args = SimpleNamespace(action='desktop-mic', microphone_source='DMIC0',
                               allow_amp_power=True, allow_playback=True, allow_capture=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'allow-capture'):
                audio.initialize(args, {})


if __name__ == '__main__':
    unittest.main()
