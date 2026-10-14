#!/usr/bin/env python3
"""Offline checks only: generated samples, PCM pipe writes and permission gates."""
import importlib.util
import contextlib
import errno
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
from unittest.mock import ANY, Mock, patch

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

    def test_explicit_native_pair_quiet_peak_fades_and_channel_frequencies(self):
        import math
        frames = list(struct.iter_unpack('<hh', audio.tone({0, 1}, seconds=.1, frequencies=(880, 1320))))
        self.assertEqual(len(frames), 4800)
        self.assertEqual(frames[0], (0, 0)); self.assertEqual(frames[-1], (0, 0))
        for channel, expected in enumerate((880, 1320)):
            values = [frame[channel] for frame in frames]
            self.assertLessEqual(max(abs(value) for value in values), 1433)
            def magnitude(hz):
                return abs(sum(value * complex(math.cos(2*math.pi*hz*index/48000),
                    -math.sin(2*math.pi*hz*index/48000)) for index, value in enumerate(values)))
            self.assertGreater(magnitude(expected), 100 * max(magnitude(440), magnitude(660), 1))

    def test_default_tone_waveform_remains_byte_identical(self):
        import math
        reference = bytearray(); frames = 4800
        for frame in range(frames):
            envelope = min(1, frame/960, (frames-1-frame)/960)
            reference.extend(struct.pack('<hh', *[round(1433*envelope*math.sin(2*math.pi*hz*frame/48000))
                                                  for hz in (440, 660)]))
        self.assertEqual(audio.tone({0, 1}, seconds=.1), bytes(reference))

    def test_pair_and_digital_peak_validation_precedes_waveform(self):
        for pair in ((440,), (440, 440), (0, 660), (880, 24000), (True, 1320), (880.0, 1320), '880,1320'):
            with self.subTest(pair=pair), self.assertRaisesRegex(RuntimeError, 'tone frequencies'):
                audio.tone({0, 1}, frequencies=pair)
        for peak in (-1, 32768, True):
            with self.subTest(peak=peak), self.assertRaisesRegex(RuntimeError, 'S16_LE'):
                audio.tone({0, 1}, amplitude=peak)

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
        for limit in (1433, 4000, 12000, 32768):
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
                        self.assertEqual(monitor.phase_snapshot(), dict(
                            frames=240, input_peak=32768, output_peak=limit))
                        monitor.begin_phase()
                        self.assertEqual(monitor.phase_snapshot(), dict(
                            frames=0, input_peak=0, output_peak=0))
                        self.assertEqual(monitor.peak, limit)  # Global safety history survives reset.
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
                pcm.set_source(None)
                self.assertIsNone(pcm.source)
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
        self.assertEqual([call.args[0] for call in pcm.set_source.call_args_list], [monitor, None])
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
        held_monitor = graph.monitor
        microphone = Mock()
        starts = []

        def play(payload, name):
            starts.append(counter[0])
            graph.monitor.forward = True
            graph.monitor.input_peak = 32767
            counter[0] += 96000

        graph.play.side_effect = play
        report = {}
        pcm.set_source.side_effect = lambda source: setattr(pcm, 'source', source)
        microphone.tone_end.side_effect = lambda: self.assertIsNone(pcm.source)
        def score_public(*unused):
            self.assertFalse(graph.monitor.forward)
            self.assertIsNone(pcm.source)
            return {'passed': True, 'reason': 'detected'}

        with patch.object(audio.threading, 'Timer'), \
                patch.object(audio, 'tone', return_value=b'full-scale input') as tone, \
                patch.object(acoustic, 'score_phase', side_effect=score_public) as score:
            audio.verify_public_playback(report, pcm, graph, capture, desktop_peak=4000, microphone=microphone)
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
        pcm.set_source.assert_called_once_with(None)
        self.assertIs(graph.monitor, held_monitor)
        microphone.tone_end.assert_called_once_with()

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
        for value in (1432, 32769):
            with self.assertRaisesRegex(RuntimeError, 'between 1433 and 32768'):
                audio.DesktopMonitor(None, ordinary=True, desktop_peak=value)
        self.assertEqual(audio.desktop_peak_limit('1433'), 1433)
        self.assertEqual(audio.desktop_peak_limit('12000'), 12000)
        self.assertEqual(audio.desktop_peak_limit('32768', 32768), 32768)
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
            self.assertEqual(result['error_origin'][-1]['function'], 'fail')
            self.assertEqual(result['error_origin'][-1]['file'], Path(__file__).name)
            self.assertGreater(result['error_origin'][-1]['line'], 0)

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

    def test_contract_gate_precedes_hardware(self):
        for action, reopen in (('feedback', True), ('desktop-mic', False)):
            with self.subTest(action=action), patch.object(audio.os, 'geteuid') as hardware:
                with self.assertRaisesRegex(RuntimeError, 'requires desktop-mic --capture-reopen'):
                    audio.initialize(SimpleNamespace(action=action, capture_reopen=reopen,
                                                     capture_contract_check=True), {})
                hardware.assert_not_called()

    def test_contract_callback_runs_after_close_and_before_same_object_reopen(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        old = {'closed_status': 'closed', 'log': '', 'error': None}
        capture.card, capture.directory, capture.report = 0, Path('/unused'), {'capture': old}
        capture.maximum_seconds, capture.started, capture.retain_recording = 60, 100, False
        events = []
        def probes():
            events.append('probes')
        def initialize(same, card, report, directory, **kwargs):
            self.assertIs(same, capture)
            self.assertEqual(kwargs['maximum_seconds'], 20)
            report['capture'] = {}
            events.append('reopen')
        with patch.object(capture, 'close', side_effect=lambda: events.append('close')), \
                patch.object(audio.time, 'monotonic', side_effect=[132, 140]), \
                patch.object(audio.OwnedCapture, '__init__', autospec=True, side_effect=initialize), \
                patch.object(capture, 'baseline', side_effect=lambda: events.append('baseline')):
            capture.reopen({}, before_reopen=probes)
        self.assertEqual(events, ['close', 'probes', 'reopen', 'baseline'])

    def test_contract_callback_failure_and_short_budget_never_reopens(self):
        for elapsed, message in ((45, 'Insufficient original'), (30, 'probe failed')):
            capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
            capture.report = {'capture': {'closed_status': 'closed', 'log': '', 'error': None}}
            capture.maximum_seconds, capture.started, capture.retain_recording = 60, 100, False
            probe = Mock(side_effect=RuntimeError('probe failed'))
            with patch.object(capture, 'close'), \
                    patch.object(audio.time, 'monotonic', return_value=100 + elapsed), \
                    patch.object(audio.OwnedCapture, '__init__') as initialize:
                with self.assertRaisesRegex(RuntimeError, message):
                    capture.reopen({}, before_reopen=probe)
                initialize.assert_not_called()
            self.assertEqual(probe.call_count, 0 if elapsed == 45 else 1)

    def test_contract_probes_require_native_rejection_and_fresh_guard_repark(self):
        owners = 'owner_pid: 99\ntrigger_time: 1.0\n'
        capture = SimpleNamespace(card=0, status=Path('/unused'))
        pcm = Mock(); pcm.healthy.return_value = owners
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if command[0] == 'journalctl':
                if '--show-cursor' in command:
                    return SimpleNamespace(stdout='-- cursor: fixture\n')
                return SimpleNamespace(stdout=audio.CAPTURE_CONTRACT_MARKER +
                    '\nq6asm-dai 17300000.remoteproc: ASoC error (-22): at snd_soc_pcm_component_hw_params() on MultiMedia2\n' +
                    'SPX: parking ASM capture session for DAI 1 across close\n')
            self.assertEqual(kwargs['stdout'], audio.subprocess.DEVNULL)
            self.assertLessEqual(kwargs['timeout'], 2)
            self.assertIn('--fatal-errors', command)
            self.assertIn('hw:0,1', command)
            self.assertEqual(command[-2:], ['-d', '1'])
            return SimpleNamespace(returncode=1, stderr='arecord: set_params:1462: Unable to install hw params:\n'
                'FORMAT: S16_LE\nCHANNELS: 2\nRATE: 48000\n')
        evidence = {}
        with patch.object(audio, 'read_text', return_value='closed'), \
                patch.object(audio.subprocess, 'run', side_effect=run):
            audio.capture_contract_probes(capture, pcm, evidence)
        self.assertTrue(evidence['passed'])
        self.assertEqual([p['name'] for p in evidence['probes']], ['channels', 'rate', 'format', 'period'])
        self.assertTrue(all(p['rejected_before_data'] and p['repark_evidence'] and p['hw_params_einval_evidence'] for p in evidence['probes']))
        self.assertIsNone(evidence['recording'])
        self.assertEqual(len([c for c in commands if c[0] == 'arecord']), 4)

    def test_contract_probe_timeout_success_missing_guard_or_open_pcm_aborts(self):
        for failure in ('timeout', 'success', 'guard', 'einval', 'repark', 'open', 'stderr', 'xrun'):
            evidence, recordings, clock = {}, [], [100.0]
            def now():
                clock[0] += 0.1
                return clock[0]
            def run(command, **kwargs):
                if command[0] == 'journalctl':
                    if '--show-cursor' in command:
                        return SimpleNamespace(stdout='-- cursor: fixture\n')
                    return SimpleNamespace(stdout=(audio.CAPTURE_CONTRACT_MARKER if failure != 'guard' else '') +
                        ('\nq6asm-dai 17300000.remoteproc: ASoC error (-22): at snd_soc_pcm_component_hw_params() on MultiMedia2'
                         if failure != 'einval' else '') +
                        ('\nSPX: parking ASM capture session for DAI 1 across close' if failure != 'repark' else ''))
                recordings.append(command)
                if failure == 'timeout':
                    raise audio.subprocess.TimeoutExpired(command, 2, stderr=b'failure')
                return SimpleNamespace(returncode=0 if failure == 'success' else 1,
                    stderr=('unrecognized failure' if failure == 'stderr' else
                            'Unable to install hw params: XRUN' if failure == 'xrun' else 'Invalid argument'))
            with self.subTest(failure=failure), \
                    patch.object(audio, 'read_text', side_effect=['closed', 'RUNNING' if failure == 'open' else 'closed']), \
                    patch.object(audio.time, 'monotonic', side_effect=now), \
                    patch.object(audio.time, 'sleep'), \
                    patch.object(audio.subprocess, 'run', side_effect=run):
                with self.assertRaises(RuntimeError):
                    audio.capture_contract_probes(SimpleNamespace(card=0, status=Path('/unused')),
                        Mock(healthy=Mock(return_value='owner_pid: 99\ntrigger_time: 1.0\n')), evidence)
            self.assertFalse(evidence['passed'])
            self.assertEqual(len(recordings), 1)
            self.assertFalse(evidence['probes'][0]['passed'])
            if failure not in ('timeout', 'guard'):
                self.assertTrue(evidence['probes'][0]['kernel_evidence'])
            if failure == 'einval':
                self.assertFalse(evidence['probes'][0]['hw_params_einval_evidence'])
            if failure in ('stderr', 'xrun'):
                self.assertTrue(evidence['probes'][0]['hw_params_einval_evidence'])
                self.assertTrue(evidence['probes'][0]['repark_evidence'])

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
        capture.started_boottime = audio.time.clock_gettime(audio.time.CLOCK_BOOTTIME)
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

    def test_contract_probes_precede_third_default_client_and_retain_outer_cleanup(self):
        import acoustic
        old = 'state: RUNNING\nowner_pid: 123\ntrigger_time: 14.567\n'
        new = 'state: RUNNING\nowner_pid: 456\ntrigger_time: 44.567\n'
        for failure in (None, 'baseline', 'third-tone'):
            with self.subTest(failure=failure):
                state, events, clients = {'reopened': False}, [], []
                capture = Mock(status=Path('/unused-capture'))
                def reopen(evidence, before_reopen=None):
                    self.assertIsNotNone(before_reopen)
                    before_reopen()
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
                        patch.object(audio, 'capture_contract_probes',
                            side_effect=lambda *args: events.append('contract-probes')),  \
                        patch.object(audio.threading, 'Timer'), \
                        patch.object(acoustic, 'score_phase', side_effect=scores):
                    args = SimpleNamespace(desktop_user='test', capture_reopen=True, capture_contract_check=True)
                    if failure:
                        with self.assertRaises(RuntimeError):
                            audio.desktop_microphone(args, report, pcm, {}, {}, capture, holders)
                    else:
                        audio.desktop_microphone(args, report, pcm, {}, {}, capture, holders)
                evidence = report['desktop']
                self.assertEqual(events, ['source-close', 'contract-probes', 'capture-reopen'])
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


class DiscardedRecording(unittest.TestCase):
    def test_close_discards_samples_even_when_status_capture_fails(self):
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
                capture.closed, capture.retain_recording = False, False
                capture.started_boottime = audio.time.clock_gettime(audio.time.CLOCK_BOOTTIME)
                capture.raw = bytearray(struct.pack('<3h', 1, 2, 3))
                capture.mutex, capture.stop = threading.Lock(), threading.Event()
                capture.process = SimpleNamespace(poll=lambda: None, terminate=Mock(), wait=Mock(), stdout=SimpleNamespace(close=Mock()), returncode=1)
                capture.thread, capture.error = Mock(), None
                capture.log, capture.directory = tempfile.TemporaryFile(), Path(directory)
                capture.status, capture.report = Path('/unused/status'), {'capture': {}}
                with patch.object(audio, 'read_text', side_effect=OSError('status missing') if failed else None, return_value='closed'), patch.object(audio.wave, 'open') as wav:
                    if failed:
                        with self.assertRaises(OSError): capture.close()
                    else:
                        capture.close()
                    wav.assert_not_called()
                self.assertFalse(capture.raw)
                self.assertIsNone(capture.report['capture']['recording'])
                self.assertTrue(capture.closed)
                self.assertEqual(capture.report['capture']['frames'], 3)
                self.assertFalse(list(Path(directory).glob('*.wav')))



class NativeMicOnDemandTests(unittest.TestCase):
    def make_source(self):
        graph = Mock()
        source = audio.NativeMicSource(graph, 0, {}, 60, None)
        source.cursor = 'cursor'
        return source

    def test_admission_rejects_wrong_action_and_conflicting_modes_before_hardware(self):
        for action, reopen, contract in [('feedback', False, False),
                                          ('desktop-mic', True, False),
                                          ('desktop-mic', False, True)]:
            with self.subTest(action=action, reopen=reopen, contract=contract):
                with patch.object(audio, 'parameter') as parameter, \
                        self.assertRaisesRegex(RuntimeError, 'native-mic-on-demand'):
                    audio.initialize(SimpleNamespace(action=action, native_mic_on_demand=True,
                        capture_reopen=reopen, capture_contract_check=contract), {})
                parameter.assert_not_called()

    def test_stock_module_properties_remain_one_quoted_nested_argument(self):
        import shlex
        source = self.make_source()
        source.endpoint = Mock()
        source.require_closed = Mock()
        source.journal = Mock(return_value='-- cursor: cursor')
        source.process_start = Mock(return_value='ticks')
        def run(*argv):
            if argv == ('pactl', '--format=json', 'list', 'sources'):
                return '[]'
            if argv == ('pactl', '--format=text', 'list', 'short', 'modules'):
                return ''
            if argv[:2] == ('pactl', 'get-default-source'):
                return source.name
            return '100'
        source.graph.run.side_effect = run
        with patch.object(audio.time, 'clock_gettime', return_value=0):
            source.start()
        argv = next(call.args for call in source.graph.run.call_args_list if call.args[:2] == ('pactl', 'load-module'))
        nested = next(arg for arg in argv if arg.startswith('source_properties='))
        parsed = dict(word.split('=', 1) for word in shlex.split(' '.join(argv[3:])))
        self.assertIn('api.alsa.disable-tsched=true', parsed['source_properties'])
        self.assertIn('api.alsa.disable-batch=true', parsed['source_properties'])
        self.assertIn('node.suspend-on-idle=true', parsed['source_properties'])
        self.assertNotIn('api.alsa.disable-tsched', parsed)
        self.assertTrue(nested.startswith("source_properties='") and nested.endswith("'"))

    def test_kernel_close_timeout_rejects_before_recovery(self):
        source = self.make_source()
        source.journal = Mock(return_value='q6asm CMD 10bcd timeout\n-- cursor: next')
        with self.assertRaisesRegex(RuntimeError, 'CMD 10bcd timeout'):
            source.check_kernel()
        self.assertEqual(source.report['kernel_errors'], ['q6asm CMD 10bcd timeout'])

    def test_module_recovery_ignores_other_modules_but_rejects_duplicate_owned_name(self):
        source = self.make_source()
        owned = '42\tmodule-alsa-source\tsource_name=' + source.name + ' device=hw:0,1\n'
        source.graph.run.return_value = ('unowned diagnostic\n'
            '4\tmodule-alsa-source\tsource_name=another device=hw:0,1\n' + owned)
        self.assertEqual(source.modules()[0]['index'], '42')
        source.graph.run.return_value = owned + owned.replace('42\t', '43\t')
        with self.assertRaisesRegex(RuntimeError, 'Duplicate owned'):
            source.modules()

    def test_native_owner_accepts_service_tid_and_rejects_wrong_tgid_or_geometry(self):
        source = self.make_source()
        source.services = {'100': {'unit': 'pipewire.service', 'start_ticks': '123'}}
        paths = {str(source.status): 'state: RUNNING\nowner_pid : 101\ntrigger_time : 1.0',
                 str(source.status.with_name('hw_params')): 'access: RW_INTERLEAVED\nformat: S16_LE\n'
                    'channels: 1\nrate: 48000 (48000/1)\nperiod_size: 1920\nbuffer_size: 7680',
                 '/proc/101/status': 'Tgid:\t100',
                 '/proc/100/stat': '100 (pipewire) ' + ' '.join(['0'] * 19 + ['123'])}
        with patch.object(audio, 'read_text', side_effect=lambda path: paths[str(path)]):
            self.assertEqual(source.native_owner()['tgid'], '100')
            paths['/proc/101/status'] = 'Tgid:\t999'
            with self.assertRaisesRegex(RuntimeError, 'owned PipeWire task'):
                source.native_owner()
            paths['/proc/101/status'] = 'Tgid:\t100'
            paths[str(source.status.with_name('hw_params'))] = paths[str(source.status.with_name('hw_params'))].replace('1920', '960')
            with self.assertRaisesRegex(RuntimeError, 'hardware contract'):
                source.native_owner()

    def test_idle_does_not_accept_prepared_pcm_or_wait_past_three_seconds(self):
        source = self.make_source()
        with patch.object(audio, 'read_text', return_value='state: PREPARED'), \
                patch.object(audio.time, 'monotonic', side_effect=[0, 3]), \
                patch.object(audio.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'close within3s'):
                source.require_closed('idle')
        sleep.assert_not_called()
        self.assertNotIn('idle_checks', source.report)

    def test_failed_unload_still_closes_clients_restores_preference_and_checks_pcm(self):
        source = self.make_source()
        source.graph.recordings = [Mock()]
        source.modules = Mock(return_value=[{'index': '42'}])
        source.load_started = True
        source.graph.run.side_effect = RuntimeError('unload failed')
        source.require_closed = Mock()
        with patch.object(audio, 'restore_default_source') as restore:
            with self.assertRaisesRegex(RuntimeError, 'unload failed'):
                source.close()
        source.graph.recordings[0].close.assert_called_once()
        restore.assert_called_once_with(source.graph, None)
        source.require_closed.assert_called_once_with('after-source-unload')
        self.assertFalse(source.report['restored'])
        self.assertFalse(source.closed)

    def test_wrong_route_rejects_but_invalid_sentinel_may_wait(self):
        source = self.make_source()
        source.source_id = 12
        row = dict(index=3, source=19, properties={'application.name': 'test'})
        source.graph.run.side_effect = [source.name, json.dumps([row])]
        with self.assertRaisesRegex(RuntimeError, 'another source'):
            source.require_client_route('test')
        row['source'] = 4294967295
        source.graph.run.side_effect = [source.name, json.dumps([row])]
        self.assertFalse(source.require_client_route('test'))

class ColdNativeMicTests(unittest.TestCase):
    def setUp(self):
        self.report, self.holders = {}, []
        self.args = SimpleNamespace(desktop_user='test-user')
        self.graph, self.source, self.client = Mock(), Mock(), Mock()
        self.graph.default_source_before_test = None
        self.graph.close.side_effect = lambda: self.report['native_mic_cold_start'].update(graph_restored=True)
        self.source.cursor, self.source.closed = 'cold-cursor', True
        self.source.journal.return_value = 'SPX ASM stream 1: bits=16 submitted=0 write_done=75 fallback=0'
        self.client.samples.return_value = [1] * 96000
        self.client.process.pid = 42
        patches = [patch.object(audio.time, 'clock_gettime', return_value=10),
            patch.object(audio, 'Path'), patch.object(audio, 'read_text', return_value='closed'),
            patch.object(audio.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='')),
            patch.object(audio, 'DesktopGraph', return_value=self.graph),
            patch.object(audio, 'NativeMicSource', return_value=self.source),
            patch.object(audio, 'DesktopRecording', return_value=self.client),
            patch.object(audio, 'assert_desktop_paused')]
        (self.clock, self.paths, self.read, self.journal, self.graph_factory,
         self.source_factory, self.client_factory, self.paused) = [self.start_patch(p) for p in patches]
        self.paths.return_value.glob.return_value = ['/unused/pcm1c/status']

    def start_patch(self, p):
        self.addCleanup(p.stop)
        return p.start()

    def test_invalid_modes_reject_before_hardware(self):
        for action, on_demand, reopen, contract in [('desktop-mic', False, False, False),
                ('feedback', True, False, False), ('desktop-mic', True, True, False),
                ('desktop-mic', True, False, True)]:
            with self.subTest(action=action, on_demand=on_demand, reopen=reopen, contract=contract), \
                    patch.object(audio, 'parameter') as hardware:
                with self.assertRaisesRegex(RuntimeError, 'native-mic-cold-start'):
                    audio.initialize(SimpleNamespace(action=action, native_mic_cold_start=True,
                        native_mic_on_demand=on_demand, capture_reopen=reopen,
                        capture_contract_check=contract), {})
                hardware.assert_not_called()

    def test_expired_budget_rejects_before_source_and_history(self):
        self.clock.return_value = 60
        with self.assertRaisesRegex(RuntimeError, 'budget expired'):
            audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.graph_factory.assert_not_called()
        self.journal.assert_not_called()

    def test_open_native_pcm_rejects_before_graph_or_history(self):
        self.read.return_value = 'state: PREPARED'
        with self.assertRaisesRegex(RuntimeError, 'already open'):
            audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.graph_factory.assert_not_called()
        self.journal.assert_not_called()

    def test_prior_retained_capture_rejects_before_graph(self):
        for marker in ('parking ASM capture', 'reusing parked ASM capture',
                       'preserving capture COPP/matrix', 'reusing retained capture COPP/matrix'):
            with self.subTest(marker=marker):
                self.journal.return_value = SimpleNamespace(returncode=0, stdout=marker, stderr='')
                with self.assertRaisesRegex(RuntimeError, 'no prior parked'):
                    audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.graph_factory.assert_not_called()

    def test_history_error_cannot_be_mistaken_for_clean_boot(self):
        for result in (SimpleNamespace(returncode=2, stdout='', stderr=''),
                       SimpleNamespace(returncode=1, stdout='', stderr='denied'),
                       SimpleNamespace(returncode=1, stdout='truncated', stderr='')):
            with self.subTest(result=result):
                self.journal.return_value = result
                with self.assertRaisesRegex(RuntimeError, 'history query failed'):
                    audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.graph_factory.assert_not_called()

    def test_no_match_exit_one_admitted_but_original_budget_never_restarted(self):
        self.clock.side_effect = [10, 60]
        with self.assertRaisesRegex(RuntimeError, 'exhausted original capture budget'):
            audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.source_factory.assert_called_once_with(self.graph, 0,
            self.report['native_mic_cold_start'], 60, None)
        self.assertEqual(self.client_factory.call_args.kwargs['wall_deadline'], 60)
        self.source.require_closed.assert_called_once_with('cold-after-client')
        self.client.close.assert_called_once()
        self.source.close.assert_called_once()
        self.graph.close.assert_called_once()
        self.paused.assert_called_once_with('test-user')
        self.assertFalse(self.holders)
        self.assertFalse(self.report['native_mic_cold_start']['passed'])

    def test_owner_failure_closes_client_and_source_without_reading(self):
        self.source.begin_client.side_effect = RuntimeError('native owner changed')
        with self.assertRaisesRegex(RuntimeError, 'native owner changed'):
            audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.client.wait_frames.assert_not_called()
        self.client.close.assert_called_once()
        self.source.require_closed.assert_called_once_with('cold-after-client')
        self.source.close.assert_called_once()
        self.graph.close.assert_called_once()

    def test_silence_error_survives_watchdog_and_client_cleanup_failures(self):
        self.client.samples.return_value = [0] * 96000
        self.source.end_client.side_effect = RuntimeError('watchdog failed')
        self.client.close.side_effect = RuntimeError('client close failed')
        with self.assertRaisesRegex(RuntimeError, 'silence or incomplete'):
            audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
        self.client.close.assert_called_once()
        self.source.close.assert_called_once()
        self.graph.close.assert_called_once()
        self.assertEqual(len(self.report['native_mic_cold_start']['cleanup_errors']), 2)
        self.assertFalse(self.report['native_mic_cold_start']['passed'])

    def test_partial_graph_and_source_start_both_restore_graph(self):
        for phase in ('graph', 'source'):
            with self.subTest(phase=phase):
                self.graph.start.side_effect = RuntimeError('graph failed') if phase == 'graph' else None
                self.source.start.side_effect = RuntimeError('source failed')
                self.graph.close.reset_mock()
                self.source.close.reset_mock()
                with self.assertRaisesRegex(RuntimeError, phase + ' failed'):
                    audio.cold_native_microphone_start(self.args, self.report, 0, 60, self.holders)
                self.graph.close.assert_called_once()
                if phase == 'source':
                    self.source.close.assert_called_once()
                else:
                    self.source.close.assert_not_called()
                self.assertFalse(self.holders)

    def test_oracle_rejects_expired_or_extended_wall_budget_before_open(self):
        for deadline in (10, 71):
            with self.subTest(deadline=deadline), patch.object(audio.subprocess, 'Popen') as opened:
                with self.assertRaisesRegex(RuntimeError, 'wall budget expired or extended'):
                    audio.OwnedCapture(0, {}, '/unused', maximum_seconds=60,
                                       retain_recording=False, wall_deadline=deadline)
                opened.assert_not_called()


class DesktopMicrophoneServingTests(unittest.TestCase):
    def make_source(self, previous=None):
        graph = Mock()
        graph.recordings = []
        source = audio.NativeMicSource(graph, 0, {}, 60, previous, desktop=True)
        source.endpoint = Mock()
        source.require_closed = Mock()
        source.journal = Mock(return_value='-- cursor: cursor')
        source.process_start = Mock(return_value='ticks')
        def run(*argv):
            if argv == ('pactl', '--format=json', 'list', 'sources'):
                return '[]'
            if argv == ('pactl', '--format=text', 'list', 'short', 'modules'):
                return ''
            if argv[:2] == ('pactl', 'get-default-source'):
                return source.name
            return '100'
        graph.run.side_effect = run
        return source

    def test_direct_and_parser_admission_precede_hardware(self):
        for value in (True, 1, 'yes'):
            with self.subTest(enabled=value), patch.object(audio, 'parameter') as hardware:
                with self.assertRaisesRegex(RuntimeError, 'desktop-microphone'):
                    audio.initialize(SimpleNamespace(action='feedback', desktop_microphone=value), {})
                hardware.assert_not_called()
        with patch.object(audio.sys, 'argv', ['audio.py', 'inspect', '--desktop-microphone']), \
                patch.object(audio, 'inventory') as hardware, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                audio.main()
        hardware.assert_not_called()

    def test_source_start_rejects_unbounded_or_expired_recording_budget(self):
        for deadline in (0, 61, float('inf')):
            source = self.make_source()
            source.wall_deadline = deadline
            with patch.object(audio.time, 'clock_gettime', return_value=0):
                with self.assertRaisesRegex(RuntimeError, 'budget expired or exceeds60s'):
                    source.start()
            source.graph.run.assert_not_called()

    def test_stable_source_collision_never_loads_or_unloads_another_owner(self):
        for collision in ('source', 'module'):
            source = self.make_source()
            old_run = source.graph.run.side_effect
            def run(*argv):
                if collision == 'source' and argv == ('pactl', '--format=json', 'list', 'sources'):
                    return json.dumps([dict(name='spx_microphone', owner_module='99')])
                if collision == 'module' and argv == ('pactl', '--format=text', 'list', 'short', 'modules'):
                    return '99\tmodule-alsa-source\tsource_name=spx_microphone device=hw:0,1'
                return old_run(*argv)
            source.graph.run.side_effect = run
            with self.subTest(collision=collision), patch.object(audio.time, 'clock_gettime', return_value=0), \
                    patch.object(audio, 'restore_default_source') as restore:
                with self.assertRaisesRegex(RuntimeError, 'name already exists'):
                    source.start()
                source.close()
            self.assertFalse(source.load_started)
            calls = [call.args[:2] for call in source.graph.run.call_args_list]
            self.assertNotIn(('pactl', 'load-module'), calls)
            self.assertNotIn(('pactl', 'unload-module'), calls)
            restore.assert_not_called()

    def test_partial_load_recovers_only_after_absence_and_refuses_replaced_module(self):
        source = self.make_source()
        source.load_started = True
        source.module = '42'
        source.modules = Mock(return_value=[dict(index='43', name='module-alsa-source', argument='replaced')])
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):
            source.close()
        self.assertNotIn(('pactl', 'unload-module'), [call.args[:2] for call in source.graph.run.call_args_list])
        source.require_closed.assert_called_once_with('after-source-unload')
        source = self.make_source()
        source.load_started = True
        source.modules = Mock(side_effect=[[dict(index='42')], []])
        source.close()
        source.graph.run.assert_called_once_with('pactl', 'unload-module', '42')

    def test_default_policy_preserves_other_named_or_unavailable_choices(self):
        for name in (None, 'spx_microphone', 'usb_microphone', 'unavailable-source'):
            previous = None if name is None else dict(type='Spa:String:JSON', value=dict(name=name))
            source = self.make_source(previous)
            with self.subTest(previous=name), patch.object(audio.time, 'clock_gettime', return_value=0):
                source.start()
            defaults = [call.args for call in source.graph.run.call_args_list if call.args[:2] == ('pactl', 'set-default-source')]
            self.assertEqual(bool(defaults), name in (None, 'spx_microphone'))
            self.assertEqual(source.name, 'spx_microphone')
            self.assertEqual(source.report['source_lifetime'], 'serve-owner')
            self.assertTrue(source.report['all_automated_recordings_bounded'])

    def test_stop_restores_only_our_unchanged_preference_even_if_unload_fails(self):
        for current in ('spx_microphone', 'user-new-choice', None):
            source = self.make_source()
            source.default_selected = source.load_started = True
            source.modules = Mock(return_value=[dict(index='42')])
            source.graph.run.side_effect = RuntimeError('unload failed')
            preference = None if current is None else dict(type='Spa:String:JSON', value=dict(name=current))
            with self.subTest(current=current), patch.object(audio, 'configured_default_source', return_value=preference), \
                    patch.object(audio, 'restore_default_source') as restore:
                with self.assertRaisesRegex(RuntimeError, 'unload failed'):
                    source.close()
            self.assertEqual(restore.called, current == 'spx_microphone')
            source.require_closed.assert_called_once_with('after-source-unload')

    def test_mixer_lease_survives_oracle_close_and_restores_after_source_cleanup(self):
        events = []
        capture = Mock()
        capture.close.side_effect = lambda: events.append('oracle-close')
        capture.process.poll.return_value = 0
        report = dict(capture=dict(error=None, log=''))
        saved = [(['amixer', 'first'], 'first'), (['amixer', 'second'], 'second')]
        def restore(command, **kwargs):
            events.append(command[-1])
            return SimpleNamespace(returncode=0, stderr='')
        graph = Mock()
        graph.close.side_effect = lambda: events.append('source-unload')
        with patch.object(audio, 'read_text', return_value='closed'), \
                patch.object(audio.subprocess, 'run', side_effect=restore):
            audio.finish_recording(capture, report, saved, retain_mixer=True)
            self.assertEqual(len(saved), 2)
            self.assertEqual(events, ['oracle-close'])
            audio.cleanup_audio_consumers(report, [], [graph], None, saved, {}, None)
        self.assertEqual(events, ['oracle-close', 'source-unload', 'second', 'first'])
        self.assertTrue(report['recording_closed'])

    def test_metadata_monitor_survives_deadline_without_recording_and_bounds_transition(self):
        source = self.make_source()
        source.services = {}
        source.check_kernel = Mock()
        source.healthy = Mock(side_effect=AssertionError('recording monitor must not run'))
        with patch.object(audio, 'read_text', return_value='closed'), \
                patch.object(audio.time, 'clock_gettime', return_value=1000):
            source.serve_healthy()
        source.healthy.assert_not_called()
        self.assertEqual(source.report['serve_observation']['status'], 'closed')
        with patch.object(audio, 'read_text', return_value='state: PREPARED'), \
                patch.object(audio.time, 'monotonic', side_effect=[0, 0, 3]):
            source.serve_healthy()
            with self.assertRaisesRegex(RuntimeError, 'transition exceeded3s'):
                source.serve_healthy()
        with patch.object(audio, 'read_text', return_value='state: XRUN'):
            with self.assertRaisesRegex(RuntimeError, 'PCM fault'):
                source.serve_healthy()

    def test_native_owner_accepts_confirmed_idle_race_but_rejects_wrong_contract(self):
        source = self.make_source()
        source.services = {'100': dict(unit='pipewire.service', start_ticks='ticks')}
        source.endpoint = Mock()
        source.check_kernel = Mock()
        running = 'state: RUNNING\nowner_pid : 101\ntrigger_time : 1.0'
        with patch.object(audio, 'read_text', side_effect=[running, 'Tgid: 100', 'closed', 'closed']):
            self.assertIsNone(source.native_owner(allow_idle_race=True))
        with patch.object(audio, 'read_text', side_effect=[running, 'Tgid: 999']):
            with self.assertRaisesRegex(RuntimeError, 'owned PipeWire task'):
                source.native_owner(allow_idle_race=True)
        with patch.object(audio, 'read_text', side_effect=[running, 'Tgid: 100', 'access: MMAP_INTERLEAVED']):
            with self.assertRaisesRegex(RuntimeError, 'hardware contract'):
                source.native_owner(allow_idle_race=True)

    def test_shared_verifier_uses_two_bounded_clients_and_real_idle_checks(self):
        import acoustic
        source, graph, pcm = Mock(), Mock(), Mock()
        source.wall_deadline = 60
        source.begin_client.side_effect = [dict(trigger_time='1'), dict(trigger_time='2')]
        pcm.healthy.return_value = 'owner_pid : 42\ntrigger_time : same'
        clients = [Mock(), Mock()]
        for index, client in enumerate(clients):
            client.process.pid = index + 1
            client.mark.side_effect = [144000, 144000, 288000]
            client.samples.return_value = [1] * 96000
        evidence = dict(clients=[])
        with patch.object(audio.time, 'clock_gettime', return_value=0), \
                patch.object(audio, 'DesktopRecording', side_effect=clients) as recording, \
                patch.object(audio, 'check_stereo'), \
                patch.object(acoustic, 'score_phase', return_value=dict(passed=True, reason='passed')):
            audio.verify_native_microphone_clients(source, graph, evidence, pcm, {}, {})
        self.assertTrue(evidence['microphone_client_passed'])
        self.assertEqual([call.kwargs['wall_deadline'] for call in recording.call_args_list], [60, 60])
        self.assertEqual([call.args[0] for call in source.require_closed.call_args_list], ['between-clients', 'after-second-client'])
        for client in clients:
            client.close.assert_called_once()
        self.assertEqual(source.endpoint.call_count, 4)

    def test_shared_verifier_scores_and_records_explicit_pair_at_quiet_peak(self):
        import acoustic
        source, graph, pcm = Mock(), Mock(), Mock()
        source.wall_deadline = 60
        source.begin_client.side_effect = [dict(trigger_time='1'), dict(trigger_time='2')]
        pcm.healthy.return_value = 'owner_pid : 42\ntrigger_time : same'
        clients = [Mock(), Mock()]
        for index, client in enumerate(clients):
            client.process.pid = index + 1
            client.mark.side_effect = [144000, 144000, 288000]
            client.samples.return_value = [1] * 96000
        evidence = dict(clients=[])
        pcm.set_source.side_effect = lambda source: setattr(pcm, 'source', source)
        def actual_score(*arguments):
            self.assertIsNone(pcm.source)
            return dict(passed=True, reason='passed')
        with patch.object(audio.time, 'clock_gettime', return_value=0), \
                patch.object(audio, 'DesktopRecording', side_effect=clients) as recording, \
                patch.object(audio, 'check_stereo'), \
                patch.object(acoustic, 'score_phase', side_effect=actual_score) as score, \
                patch.object(audio, 'tone', return_value=b'quiet-pair') as waveform:
            audio.verify_native_microphone_clients(source, graph, evidence, pcm, {}, {}, frequencies=(880, 1320))
        self.assertTrue(evidence['microphone_client_passed'])
        self.assertEqual([call.kwargs['wall_deadline'] for call in recording.call_args_list], [60, 60])
        self.assertEqual([call.args[0] for call in source.require_closed.call_args_list], ['between-clients', 'after-second-client'])
        for client in clients:
            client.close.assert_called_once()
        self.assertEqual(source.endpoint.call_count, 4)

        self.assertEqual([call.args[2] for call in score.call_args_list], [[880, 1320], [880, 1320]])
        self.assertEqual([row['frequencies_hz'] for row in evidence['clients']], [[880, 1320], [880, 1320]])
        for call in waveform.call_args_list:
            self.assertEqual(call.kwargs, {'frequencies': (880, 1320)})
        self.assertEqual(pcm.play.call_count, 2)

    def test_shared_verifier_expiry_and_first_cleanup_failure_cannot_leave_client_open(self):
        source, graph, pcm, client = Mock(), Mock(), Mock(), Mock()
        source.wall_deadline = 60
        with patch.object(audio.time, 'clock_gettime', return_value=60), \
                patch.object(audio, 'DesktopRecording') as recording:
            with self.assertRaisesRegex(RuntimeError, 'deadline exceeds60s or expired'):
                audio.verify_native_microphone_clients(source, graph, {}, pcm, {}, {})
            recording.assert_not_called()
        pcm.healthy.return_value = 'owner_pid : 42\ntrigger_time : same'
        source.begin_client.side_effect = RuntimeError('first capture failed')
        source.end_client.side_effect = RuntimeError('watchdog cleanup failed')
        with patch.object(audio.time, 'clock_gettime', return_value=0), \
                patch.object(audio, 'DesktopRecording', return_value=client):
            with self.assertRaisesRegex(RuntimeError, 'first capture failed'):
                audio.verify_native_microphone_clients(source, graph, dict(clients=[]), pcm, {}, {})
        client.close.assert_called_once()

    def test_failed_client_stop_attempts_remaining_cleanup_and_discards_raw(self):
        client = audio.DesktopRecording.__new__(audio.DesktopRecording)
        client.log = tempfile.TemporaryFile()
        client.stop, client.mutex = threading.Event(), threading.Lock()
        client.process, client.thread = Mock(), Mock()
        client.started_boottime = 0
        client.process.poll.return_value = None
        client.thread.is_alive.return_value = False
        client.error = None
        client.raw = bytearray(b'incidental samples')
        with patch.object(audio, 'stop_desktop_process', side_effect=RuntimeError('first stop error')):
            with self.assertRaisesRegex(RuntimeError, 'first stop error'):
                client.close()
        client.thread.join.assert_called_once_with(timeout=2)
        client.process.stdout.close.assert_called_once()
        self.assertTrue(client.log.closed)
        self.assertFalse(client.raw)
        self.assertFalse(client.process_reaped)
        self.assertIsNone(client.ownership_wall_seconds)

    def run_serve(self, *, default_selected=True):
        report = dict(action='serve', desktop=dict(acoustic_passed=True),
            public_desktop=dict(acoustic_passed=True), recording_closed=True,
            before=dict(boot_id='boot', release='release'))
        pcm, graph = Mock(), Mock()
        source = graph.microphone
        source.name, source.module, source.source_id = 'spx_microphone', '42', 79
        source.default_selected = default_selected
        source.report = dict(microphone_client_passed=default_selected)
        pcm.process.pid, pcm.feed_stats = 42, {}
        pcm.healthy.return_value = 'trigger_time : same'
        graph.monitor.input_peak, graph.monitor.peak = 0, 0
        graph.monitor.max_interarrival_seconds = 0
        events = []
        source.close.side_effect = lambda: events.append('source-unload')
        graph.monitor.close.side_effect = lambda: events.append('monitor-close')
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(output=Path(temporary), serve_seconds=120, desktop_peak=1433,
                                   desktop_microphone=True)
            with patch.object(audio, 'verify_native_microphone_clients') as verify, \
                    patch.object(audio, 'check_stereo'), patch.object(audio.signal, 'signal'), \
                    patch.object(audio.threading, 'Event') as event, \
                    patch.object(audio.time, 'monotonic', side_effect=[0, 120, 120.5]):
                event.return_value.wait.return_value = False
                event.return_value.is_set.return_value = False
                audio.serve_desktop(args, report, pcm, graph, {}, {})
        self.assertEqual(verify.called, default_selected)
        self.assertTrue(report['serve']['microphone_identity_retained_120s'])
        self.assertEqual(source.serve_healthy.call_count, 2)
        self.assertEqual(events, ['source-unload', 'monitor-close'])
        pcm.close.assert_not_called()
        self.assertIsNone(graph.microphone)
        return source, report

    def test_120_second_serve_checks_final_identity_and_closes_source_before_monitor(self):
        self.run_serve()

    def test_explicit_other_default_keeps_serve_available_without_forcing_capture(self):
        source, report = self.run_serve(default_selected=False)
        self.assertIn('verification_fixture_rejected', source.report)
        self.assertFalse(report['serve']['microphone']['bounded_clients_passed'])



class CaptureOwnershipWallClockTests(unittest.TestCase):
    def test_real_helper_process_close_reports_elapsed_ownership_without_deadline(self):
        import sys
        original_popen = audio.subprocess.Popen
        def helper_process(*arguments, **keywords):
            return original_popen([sys.executable, '-c',
                "import os,time; os.write(1, bytes([1,0])*1920); time.sleep(10)"],
                stdout=audio.subprocess.PIPE, stderr=keywords['stderr'], bufsize=0)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(audio.subprocess, 'Popen', side_effect=helper_process), \
             patch.object(audio, 'read_text', return_value='closed'):
            report = {'microphone_source': 'DMIC1'}
            capture = audio.OwnedCapture(0, report, Path(directory), retain_recording=False)
            try:
                deadline = time.monotonic() + 2
                while not capture.raw and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(capture.raw)
                before = audio.time.clock_gettime(audio.time.CLOCK_BOOTTIME)
            finally:
                capture.close()
            after = audio.time.clock_gettime(audio.time.CLOCK_BOOTTIME)
            self.assertIsNone(capture.wall_deadline)
            self.assertIsNotNone(capture.process.poll())
            duration = report['capture']['ownership_wall_seconds']
            self.assertGreaterEqual(duration, before - capture.started_boottime)
            self.assertLessEqual(duration, after - capture.started_boottime)
            self.assertIsNone(report['capture']['recording']); self.assertFalse(capture.raw)
            self.assertFalse(list(Path(directory).glob('*.wav')))
            capture.close()
            self.assertEqual(report['capture']['ownership_wall_seconds'], duration)

    def test_reporting_measures_reaping_instead_of_frame_duration(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        capture.closed, capture.started_boottime, capture.wall_deadline = False, 100, None
        capture.stop, capture.thread, capture.process = Mock(), Mock(), Mock()
        capture.process.poll.return_value = None; capture.process.returncode = -15
        capture.log = io.BytesIO(); capture.report, capture.error = {'capture': {}}, None
        capture.mutex, capture.raw = threading.Lock(), bytearray()
        capture.samples = Mock(return_value=audio.array('h', [1, 2, 3]))
        capture.retain_recording, capture.status = False, Path('/unused')
        events = []
        capture.process.wait.side_effect = lambda **keywords: events.append('reaped')
        def clock(which):
            self.assertEqual(events, ['reaped']); self.assertEqual(which, audio.time.CLOCK_BOOTTIME)
            return 137
        with patch.object(audio.time, 'clock_gettime', side_effect=clock), patch.object(audio, 'read_text', return_value='closed'):
            capture.close()
        self.assertEqual(capture.report['capture']['ownership_wall_seconds'], 37)
        self.assertEqual(capture.report['capture']['frames'], 3)

    def test_native_oracle_fixed_deadline_expires_without_renewal(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        capture.stop = threading.Event(); capture.wall_deadline = 190; capture.error = None
        with patch.object(audio.time, 'clock_gettime', return_value=190), \
             patch.object(audio.time, 'monotonic', return_value=100), patch.object(audio.os, 'kill') as abort:
            capture.consume()
        self.assertIn('wall-clock deadline', capture.error); abort.assert_called_once()
        self.assertEqual(capture.wall_deadline, 190)
        for deadline in (100, 190.01):
            with patch.object(audio.time, 'clock_gettime', return_value=100), \
                 patch.object(audio.subprocess, 'Popen') as process, \
                 self.assertRaisesRegex(RuntimeError, 'wall budget expired or extended'):
                audio.OwnedCapture(0, {}, Path('/unused'), maximum_seconds=90, wall_deadline=deadline)
            process.assert_not_called()


class MicrophoneApplicationFormatTests(unittest.TestCase):
    client_class = audio.DesktopRecording
    def test_admission_rejects_wrong_modes_and_types_before_hardware(self):
        cases = [('feedback', True, True), ('serve', False, True),
                 ('serve', 1, True), ('serve', True, 1), ('serve', True, 'yes')]
        for action, microphone, enabled in cases:
            with self.subTest(case=(action, microphone, enabled)), patch.object(audio, 'parameter') as hardware:
                with self.assertRaisesRegex(RuntimeError, 'native-mic-app-formats'):
                    audio.initialize(SimpleNamespace(action=action, desktop_microphone=microphone,
                        native_mic_app_formats=enabled), {})
                hardware.assert_not_called()
        for arguments in (['inspect', '--native-mic-app-formats'], ['serve', '--native-mic-app-formats']):
            with patch.object(audio.sys, 'argv', ['audio.py', *arguments]), \
                 patch.object(audio, 'inventory') as hardware, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    audio.main()
                hardware.assert_not_called()

    def make_client(self, graph, rate, channels, name='client'):
        process = Mock(pid=100 + len(graph.recordings))
        process.poll.return_value = -15
        with patch.object(audio.subprocess, 'Popen', return_value=process) as opened, \
             patch.object(audio.threading, 'Thread') as thread, \
             patch.object(audio.time, 'clock_gettime', return_value=0):
            thread.return_value.is_alive.return_value = False
            client = self.client_class(graph, name, wall_deadline=60, rate=rate, channels=channels)
        self.addCleanup(lambda: client.close() if not client.log.closed else None)
        return client, opened.call_args.args[0]

    def graph(self):
        graph = Mock(command=['user-env'])
        graph.processes, graph.recordings = [], []
        return graph

    def test_exact_client_arguments_default_unchanged_and_partial_frame_decode(self):
        graph = self.graph()
        for rate, channels, channel_map in ((44100, 1, 'mono'), (48000, 2, 'front-left,front-right'),
                                            (48000, 1, None)):
            client, command = self.make_client(graph, rate, channels)
            with self.subTest(rate=rate, channels=channels):
                self.assertIn(f'--rate={rate}', command); self.assertIn(f'--channels={channels}', command)
                self.assertIn('--format=s16le', command); self.assertIn('--raw', command)
                self.assertFalse(any(value.startswith(('--device', '--fix-', '--no-remix')) for value in command))
                self.assertEqual([value for value in command if value.startswith('--channel-map=')],
                                 [] if channel_map is None else ['--channel-map=' + channel_map])
                samples = [1, 11, 2, 12, 3, 13] if channels == 2 else [1, 2, 3]
                client.raw = bytearray(struct.pack('<' + 'h' * len(samples), *samples) + b'\x00')
                client.healthy = Mock()
                self.assertEqual(client.mark(), 3)
                self.assertEqual(list(client.samples(1, 3)), samples[channels:])
                with patch.object(audio, 'stop_desktop_process'), \
                     patch.object(audio.time, 'clock_gettime', return_value=6):
                    client.close()
                self.assertEqual(client.closed_frames, 3); self.assertEqual(client.closed_partial_bytes, 1)
                self.assertEqual(client.ownership_wall_seconds, 6)
                self.assertFalse(client.raw); self.assertTrue(client.recording_discarded)

    def test_invalid_profile_budget_or_spawn_failure_never_leaves_a_log_or_process(self):
        graph = self.graph()
        for options in (dict(rate=True), dict(channels=True), dict(rate=96000),
                        dict(rate=44100, wall_deadline=61), dict(channels=2, wall_deadline=None)):
            with self.subTest(options=options), patch.object(audio.time, 'clock_gettime', return_value=0), \
                 patch.object(audio.subprocess, 'Popen') as opened:
                with self.assertRaises(RuntimeError):
                    audio.DesktopRecording(graph, 'client', **options)
                opened.assert_not_called()
        log = tempfile.TemporaryFile()
        with patch.object(audio.tempfile, 'TemporaryFile', return_value=log), \
             patch.object(audio.subprocess, 'Popen', side_effect=OSError('spawn failed')):
            with self.assertRaisesRegex(OSError, 'spawn failed'):
                audio.DesktopRecording(graph, 'client')
        self.assertTrue(log.closed); self.assertFalse(graph.processes); self.assertFalse(graph.recordings)

    def test_client_wait_timeout_uses_requested_rate(self):
        client = audio.DesktopRecording.__new__(audio.DesktopRecording)
        client.rate, client.channels = 44100, 1
        client.raw, client.mutex, client.healthy = bytearray(), threading.Lock(), Mock()
        with patch.object(audio.time, 'monotonic', side_effect=[0, 8.95, 9.1]), patch.object(audio.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'did not deliver'):
                client.wait_frames(44100)
        self.assertEqual(client.healthy.call_count, 2)

    def test_actual_consumer_enforces_client_rate_byte_cap_and_each_stereo_channel(self):
        for rate, channels, maximum, block, message in (
            (44100, 1, 1, bytes(44100 * 2 + 2), 'duration limit'),
            (48000, 2, 60, struct.pack('<hh', 1, 32767) * 4800, 'clipping')):
            client = audio.DesktopRecording.__new__(audio.DesktopRecording)
            client.rate, client.channels, client.maximum_seconds = rate, channels, maximum
            client.raw, client.mutex, client.stop = bytearray(), threading.Lock(), threading.Event()
            client.error, client.limit = None, None
            client.process = Mock()
            with self.subTest(rate=rate, channels=channels), \
                 patch.object(audio.select, 'select', return_value=([client.process.stdout], [], [])), \
                 patch.object(audio.os, 'read', return_value=block), patch.object(audio.os, 'kill') as abort:
                client.consume()
            self.assertIn(message, client.error); abort.assert_called_once()
            self.assertEqual(client.raw, block)

    def test_source_output_contract_mismatch_is_recorded_and_rejected(self):
        graph = self.graph()
        source = audio.NativeMicSource(graph, 0, {}, 60, None, desktop=True)
        source.source_id = 99
        requested = dict(sample_specification='s16le 2ch 48000Hz', channel_map='front-left,front-right')
        original = dict(source=99, index=7, sample_specification=requested['sample_specification'],
                        channel_map=requested['channel_map'], properties={'application.name': 'client'})
        for mutation in ({}, dict(sample_specification='s16le 1ch 48000Hz'),
                         dict(sample_specification='s16le 2ch 44100Hz'), dict(channel_map='mono'),
                         dict(source=12)):
            observed = dict(original, **mutation)
            graph.run.side_effect = [source.name, json.dumps([observed])]
            with self.subTest(mutation=mutation):
                if mutation:
                    with self.assertRaisesRegex(RuntimeError, 'another source|format or channel map'):
                        source.require_client_route('client', requested)
                else:
                    self.assertTrue(source.require_client_route('client', requested))
        self.assertTrue(source.report['routes'])
        self.assertEqual(source.report['routes'][-1]['channel_map'], 'mono')

    def test_start_failure_survives_an_early_close_failure_without_fabricated_observations(self):
        source, pcm = Mock(), Mock()
        source.wall_deadline = 60
        source.begin_client.side_effect = RuntimeError('original start failure')
        source.end_client.side_effect = RuntimeError('watcher close failure')
        pcm.healthy.return_value = 'owner_pid : 42\ntrigger_time : stable'
        client = SimpleNamespace(process=SimpleNamespace(pid=1),
            requested_contract=dict(sample_specification='s16le 1ch 44100Hz', channel_map='mono'),
            close=Mock(side_effect=RuntimeError('early close failure')))
        evidence = dict(clients=[])
        with patch.object(audio, 'DesktopRecording', return_value=client), \
             patch.object(audio.time, 'clock_gettime', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'original start failure'):
                audio.verify_native_microphone_clients(source, self.graph(), evidence, pcm, {}, {}, app_formats=True)
        client.close.assert_called_once()
        self.assertFalse(evidence['clients'][0]['passed'])
        self.assertIsNone(evidence['clients'][0]['ownership_wall_seconds'])
        self.assertFalse(evidence['clients'][0]['recording_discarded'])
        self.assertEqual(len(evidence['clients'][0]['cleanup_errors']), 2)

    def verify_waveforms(self, defect=None):
        import math
        from array import array
        graph, pcm, source = self.graph(), Mock(), Mock()
        source.wall_deadline, source.report = 60, dict(routes=[])
        pcm.healthy.return_value = 'owner_pid : 42\ntrigger_time : stable'
        clients, commands = [], []
        def recording(graph, name, **options):
            rate, channels = options['rate'], options['channels']
            client, command = self.make_client(graph, rate, channels, name)
            quiet = [int(3 * math.sin(2 * math.pi * 130 * i / rate)) for i in range(3 * rate)]
            phase = [int(25 * math.sin(2 * math.pi * 440 * i / rate) +
                         45 * math.sin(2 * math.pi * 660 * i / rate) + quiet[i]) for i in range(3 * rate)]
            inputs = [phase[:] for _ in range(channels)]
            if channels == 2 and defect == 'missing-tone':
                inputs[1] = quiet[:]
            if channels == 2 and defect == 'clipped-channel':
                inputs[1][0] = 32767
            client.raw = bytearray(array('h', [value for v in quiet for value in [v] * channels]).tobytes() +
                                   array('h', [value for frame in zip(*inputs) for value in frame]).tobytes())
            client.mark = Mock(side_effect=[3 * rate, 3 * rate, 6 * rate])
            client.wait_frames = Mock()
            clients.append(client); commands.append(command)
            return client
        def begin(client, name, contract):
            source.report['routes'].append(dict(client=name, source=99, source_output=len(clients),
                sample_specification=contract['sample_specification'], channel_map=contract['channel_map']))
            return dict(trigger_time=str(client.process.pid), hw_params='unchanged native mono contract')
        source.begin_client.side_effect = begin
        evidence = dict(clients=[])
        with patch.object(audio, 'DesktopRecording', side_effect=recording), \
             patch.object(audio, 'check_stereo'), patch.object(audio, 'stop_desktop_process'), \
             patch.object(audio.time, 'clock_gettime', return_value=0):
            if defect:
                with self.assertRaisesRegex(RuntimeError, 'acoustic test failed'):
                    audio.verify_native_microphone_clients(source, graph, evidence, pcm, {}, {}, app_formats=True)
            else:
                audio.verify_native_microphone_clients(source, graph, evidence, pcm, {}, {}, app_formats=True)
        for client in clients:
            self.assertFalse(client.raw); self.assertTrue(client.log.closed)
            client.thread.join.assert_called_once_with(timeout=2)
        self.assertEqual(source.end_client.call_count, 2)
        return evidence, clients

    def test_real_decoder_and_scores_accept_both_formats_and_duplicated_mono(self):
        evidence, clients = self.verify_waveforms()
        self.assertTrue(evidence['application_formats_passed'])
        self.assertEqual([(entry['requested_contract']['rate'], entry['requested_contract']['channels'])
                          for entry in evidence['clients']], [(44100, 1), (48000, 2)])
        self.assertEqual([entry['frames'] for entry in evidence['clients']], [6 * 44100, 6 * 48000])
        self.assertTrue(all(entry['recording_discarded'] for entry in evidence['clients']))
        self.assertTrue(all(score['passed'] for score in evidence['clients'][1]['score']['inputs']))
        self.assertEqual(clients[0].wait_frames.call_args_list[0].args, (3 * 44100,))

    def test_stereo_missing_tone_or_clipping_one_channel_cannot_pass(self):
        for defect in ('missing-tone', 'clipped-channel'):
            with self.subTest(defect=defect):
                evidence, clients = self.verify_waveforms(defect)
                self.assertNotIn('application_formats_passed', evidence)
                self.assertTrue(evidence['clients'][0]['passed'])
                self.assertFalse(evidence['clients'][1]['passed'])

    def test_44100_waveform_requires_the_actual_client_rate(self):
        import math
        from acoustic import score_phase
        rate = 44100
        quiet = [int(3 * math.sin(2 * math.pi * 130 * i / rate)) for i in range(rate)]
        phase = [int(25 * math.sin(2 * math.pi * 440 * i / rate) +
                     45 * math.sin(2 * math.pi * 660 * i / rate) + quiet[i]) for i in range(rate)]
        self.assertTrue(score_phase(phase, quiet, [440, 660], rate=rate)['passed'])
        self.assertFalse(score_phase(phase, quiet, [440, 660])['passed'])


class OrdinaryDesktopPlaybackTests(unittest.TestCase):
    def test_handoff_keeps_pcm_and_does_not_claim_acoustic_verification(self):
        report = dict(action='play-desktop', playback_ready=True,
                      microphone_capture=False, desktop={},
                      before=dict(boot_id='boot', release='kernel'))
        pcm, graph = Mock(), Mock()
        pcm.process.pid, pcm.feed_stats = 42, {}
        graph.monitor.input_peak, graph.monitor.peak = 0, 0
        graph.monitor.max_interarrival_seconds = 0
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output=Path(directory), serve_seconds=0,
                                   desktop_peak=1433, desktop_microphone=False)
            with patch.object(audio, 'check_stereo'), patch.object(audio.signal, 'signal'), \
                    patch.object(audio.threading, 'Event') as event, \
                    patch.object(audio, 'OwnedCapture') as capture:
                event.return_value.wait.return_value = True
                audio.serve_desktop(args, report, pcm, graph, {}, {})
            capture.assert_not_called()
            self.assertIsNone(report['serve']['acoustic_passed'])
            self.assertIsNone(report['serve']['public_acoustic_passed'])
            self.assertEqual(report['serve']['peak_limit'], 1433)
            self.assertTrue(report['serve']['stopped'])
            pcm.close.assert_not_called()

    def test_gain_change_keeps_pcm_and_checks_exact_new_gain(self):
        report = dict(action='play-desktop', playback_ready=True,
                      microphone_capture=False, desktop={}, pcm=dict(card='1'),
                      before=dict(boot_id='boot', release='kernel'))
        pcm, graph = Mock(), Mock()
        pcm.process.pid, pcm.feed_stats = 42, {}
        graph.monitor.input_peak, graph.monitor.peak = 0, 0
        graph.monitor.max_interarrival_seconds = 0
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output=Path(directory), serve_seconds=0,
                                   desktop_peak=32768, desktop_microphone=False,
                                   pa_gain_step=1)
            calls = []
            def wait(_):
                if calls:
                    return True
                calls.append(True)
                (args.output / 'pa-gain-step').write_text('2\n')
                return False
            with patch.object(audio, 'check_stereo') as check, \
                    patch.object(audio, 'set_desktop_pa_gain') as change, \
                    patch.object(audio.signal, 'signal'), \
                    patch.object(audio.threading, 'Event') as event:
                event.return_value.wait.side_effect = wait
                audio.serve_desktop(args, report, pcm, graph, {}, {})
            change.assert_called_once_with('1', 2)
            self.assertEqual(report['serve']['pa_gain_db'], 3)
            self.assertEqual(report['serve']['gain_changes'][0]['pcm_pid'], 42)
            check.assert_called_with({}, {}, initialized=True, observations=ANY, pa_gain_step=2)
            pcm.close.assert_not_called()

    def test_saved_gain_survives_startup_and_applies_on_same_pcm_after_settling(self):
        report = dict(action='play-desktop', playback_ready=True,
                      microphone_capture=False, desktop={}, pcm=dict(card='1'),
                      before=dict(boot_id='boot', release='kernel'))
        pcm, graph = Mock(), Mock()
        pcm.process.pid, pcm.feed_stats = 42, {}
        graph.monitor.input_peak, graph.monitor.peak = 0, 0
        graph.monitor.max_interarrival_seconds = 0
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / 'saved-gain'
            saved.write_text('2\n')
            args = SimpleNamespace(output=Path(directory), serve_seconds=0,
                                   desktop_peak=32768, desktop_microphone=False,
                                   pa_gain_step=1, pa_gain_file=saved)
            with patch.object(audio, 'check_stereo'), \
                    patch.object(audio, 'set_desktop_pa_gain') as change, \
                    patch.object(audio.signal, 'signal'), \
                    patch.object(audio.time, 'monotonic', side_effect=[0, 0, 6, 7]), \
                    patch.object(audio.threading, 'Event') as event:
                event.return_value.wait.side_effect = [False, False, True]
                audio.serve_desktop(args, report, pcm, graph, {}, {})
            self.assertEqual(saved.read_text(), '2\n')
            change.assert_called_once_with('1', 2)
            self.assertEqual(report['serve']['gain_changes'][0]['monotonic'], 6)
            self.assertEqual(report['serve']['gain_changes'][0]['pcm_pid'], 42)
            pcm.close.assert_not_called()

    def test_ordinary_connection_preserves_user_volume_balance_and_mute(self):
        graph = audio.DesktopGraph.__new__(audio.DesktopGraph)
        graph.monitor, graph.public_restore, graph.command, graph.report = None, [], [], {}
        sink = dict(name='spx_speakers', index=1, mute=True,
                    volume={'front-left': {'value': 20000}, 'front-right': {'value': 30000}})
        source = dict(sink, name='spx_speakers.monitor', index=2)
        def run(*args):
            if args[-2:] == ('list', 'sinks'):
                return json.dumps([sink])
            if args[-2:] == ('list', 'sources'):
                return json.dumps([source])
            if args[-1] == 'get-default-sink':
                return sink['name']
            return ''
        graph.run = Mock(side_effect=run)
        with patch.object(audio.subprocess, 'Popen'), patch.object(audio, 'DesktopMonitor'):
            graph.connect_public(Mock(), 32768, preserve_volume=True)
        commands = [c.args for c in graph.run.call_args_list]
        self.assertFalse(any(c[1] in ('set-sink-volume', 'set-sink-mute') for c in commands))
        self.assertIn(('pactl', 'set-source-volume', source['name'], '65536'), commands)
        self.assertFalse(any(c[1] in ('set-sink-volume', 'set-sink-mute', 'set-default-sink')
                             for c in graph.public_restore))

    def test_handoff_rejects_uninitialized_or_capturing_state(self):
        for ready, capturing in ((False, False), (True, True)):
            report = dict(action='play-desktop', playback_ready=ready,
                          microphone_capture=capturing)
            with self.assertRaisesRegex(RuntimeError, 'native initialization'):
                audio.serve_desktop(None, report, None, None, {}, {})


class PeriodicStereoHealthTests(unittest.TestCase):
    """Fresh synthetic sysfs snapshots; no device, PCM or sound access."""

    def setUp(self):
        self.mapping = {3: 1, 4: 2}
        self.paths = {unit: Path(f'/stub/unit{unit}') for unit in self.mapping}
        self.good = dict(COMP_PARAMS=0x016840c6, SLV_STATUS=0x14, MCP_STATUS=0,
                         GPIO_DIR=0x1e, GPIO_VAL=0x1e, FORCED_ATTACH=0,
                         DEV1_ID1=0x21170213, DEV1_ID2=0x10,
                         DEV2_ID1=0x21170214, DEV2_ID2=0x10,
                         FRAME_B0=7, FRAME_B1=7, DP1_B0=0x01000107,
                         DP4_B0=0x01000607, RX7_PATH_CFG0=0, RX8_PATH_CFG0=0,
                         RX7_VOLUME=0, RX8_VOLUME=0)
        self.slaves = [dict(unit=unit, address=address, status='Attached',
                            driver='wsa881x-codec', initialized=True)
                       for unit, address in self.mapping.items()]
        self.codecs = {unit: dict(UNIT=unit, DEV_NUM=address, ATTACHED=1,
                         STREAM_CONFIGURED=1, STREAM_ENABLED=1, DAC_PREPARED=1,
                         DAC_MASTER_PORT=1 if unit == 3 else 4, SHADOW_PA_GAIN=0xc9,
                         SHADOW_COMP_ENABLE=0, SHADOW_VISENSE_ENABLE=0,
                         LATE_INIT_RESULT=0, LATE_INIT_COUNT=1, SHADOW_PA_ENABLE=0x80,
                         SHADOW_OCP=0xb4, SHADOW_BOOST=0x98)
                       for unit, address in self.mapping.items()}
        self.bad_identity = dict(self.good, DEV2_ID1=0x36170214)

    @contextlib.contextmanager
    def snapshots(self, samples):
        samples = iter(samples)
        self.reads = 0

        def read(path):
            if path == audio.AUDIO_STATE:
                self.reads += 1
                values = next(samples)
                if isinstance(values, BaseException):
                    raise values
            else:
                values = next(self.codecs[unit] for unit, base in self.paths.items()
                              if path == base / 'spx_playback_state')
            return '\n'.join(f'{key}={value:#x}' for key, value in values.items())

        with patch.object(audio, 'read_text', side_effect=read), \
                patch.object(audio, 'devices', return_value=self.slaves), \
                patch.object(audio.time, 'sleep') as sleep, \
                contextlib.redirect_stderr(io.StringIO()) as journal:
            yield sleep, journal

    def run_periodic(self):
        status = {}
        health = audio.PeriodicStereoHealth(status)
        health.check(self.mapping, self.paths, healthy=Mock())
        return status['periodic_health']

    def test_transient_bad_identity_then_good_continues_and_counts_one(self):
        with self.snapshots([self.bad_identity, self.good]) as (sleep, journal):
            stats = self.run_periodic()
        self.assertEqual(self.reads, 2)
        sleep.assert_called_once_with(0.05)
        self.assertEqual(stats['transient_events'], 1)
        self.assertEqual(stats['failed_samples'], 1)
        self.assertEqual(stats['first_failure'], stats['last_failure'])
        self.assertEqual(stats['first_failure']['category'], 'identity')
        self.assertIn('Unknown physical identity at address 2', journal.getvalue())
        self.assertTrue(stats['last_event']['samples'][-1]['passed'])
        self.assertEqual(stats['first_failure']['observation'][0]['master']['DEV2_ID1'], 0x36170214)

    def test_persistent_bad_identity_is_fatal_after_two_confirmations(self):
        status = {}
        health = audio.PeriodicStereoHealth(status)
        with self.snapshots([self.bad_identity] * 3) as (sleep, journal):
            with self.assertRaisesRegex(RuntimeError, 'Unknown physical identity'):
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(self.reads, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(health.stats['confirmed_events'], 1)
        self.assertEqual(health.stats['transient_events'], 0)
        self.assertEqual(len(health.stats['last_event']['samples']), 3)
        self.assertIn('confirmed', journal.getvalue())

    def test_eio_once_then_good_keeps_errno_and_origin(self):
        with self.snapshots([OSError(errno.EIO, 'bridge read failed'), self.good]):
            stats = self.run_periodic()
        self.assertEqual(stats['transient_events'], 1)
        self.assertEqual(stats['failed_samples'], 1)
        self.assertEqual(stats['first_failure']['errno'], errno.EIO)
        self.assertIn('state', [frame['function'] for frame in stats['first_failure']['origin']])
        self.assertIsNone(stats['first_failure']['observation'][0]['master'])

    def test_persistent_eio_is_fatal_and_preserves_oserror(self):
        health = audio.PeriodicStereoHealth({})
        with self.snapshots([OSError(errno.EIO, 'bridge read failed') for _ in range(3)]):
            with self.assertRaises(OSError) as raised:
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(raised.exception.errno, errno.EIO)
        self.assertEqual(self.reads, 3)
        self.assertEqual(health.stats['failures_by_class'], {'read-oserror-5': 3})
        self.assertEqual(health.stats['confirmed_events'], 1)

    def test_persistent_power_state_change_stays_fatal(self):
        health = audio.PeriodicStereoHealth({})
        with self.snapshots([dict(self.good, GPIO_VAL=0x18)] * 3):
            with self.assertRaisesRegex(RuntimeError, 'Amplifier power state changed'):
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(self.reads, 3)
        self.assertEqual(health.stats['failures_by_class'], {'power': 3})
        self.assertEqual(health.stats['confirmed_events'], 1)

    def test_invalid_canary_or_attached_id_is_not_amplifier_state_change(self):
        for bad in (dict(self.good, COMP_PARAMS=0x361840c6),
                    dict(self.good, DEV2_ID1=0, DEV2_ID2=0),
                    dict(self.good, DEV2_ID1=0xffffffff, DEV2_ID2=0xffffffff)):
            with self.subTest(bad=bad), self.snapshots([bad, self.good]):
                stats = self.run_periodic()
            self.assertEqual(stats['first_failure']['category'], 'invalid-sample')
            self.assertEqual(stats['first_failure']['observation'][0]['master'], bad)
            self.assertEqual(stats['transient_events'], 1)

    def test_persistent_invalid_canary_is_fatal(self):
        health = audio.PeriodicStereoHealth({})
        with self.snapshots([dict(self.good, COMP_PARAMS=0)] * 3):
            with self.assertRaisesRegex(audio.InvalidAudioSample, 'canary mismatch'):
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(health.stats['confirmed_events'], 1)
        self.assertEqual(health.stats['failures_by_class'], {'invalid-sample': 3})

    def test_different_failures_do_not_confirm_each_other(self):
        with self.snapshots([self.bad_identity, dict(self.good, GPIO_VAL=0x18)]):
            stats = self.run_periodic()
        self.assertEqual(stats['confirmed_events'], 0)
        self.assertEqual(stats['transient_events'], 1)
        self.assertEqual(stats['transient_samples'], 2)
        self.assertEqual(stats['failures_by_class'], {'identity': 1, 'power': 1})
        self.assertEqual(stats['last_failure']['category'], 'power')

    def test_live_pcm_fault_during_confirmation_is_immediately_fatal(self):
        health = audio.PeriodicStereoHealth({})
        with self.snapshots([self.bad_identity]):
            with self.assertRaisesRegex(RuntimeError, 'PCM died'):
                health.check(self.mapping, self.paths, healthy=Mock(side_effect=RuntimeError('PCM died')))
        self.assertEqual(self.reads, 1)
        self.assertEqual(health.stats['aborted_events'], 1)

    def test_signal_interruption_is_never_retried(self):
        health = audio.PeriodicStereoHealth({})
        with self.snapshots([InterruptedError('service stop'), self.good]):
            with self.assertRaises(InterruptedError):
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(self.reads, 1)
        self.assertEqual(health.stats['failed_samples'], 0)

    def test_successful_periodic_check_never_arms_timer_or_sleeps(self):
        with self.snapshots([self.good]) as (sleep, _), \
                patch.object(audio.signal, 'setitimer') as timer:
            stats = self.run_periodic()
        sleep.assert_not_called()
        timer.assert_not_called()
        self.assertEqual(stats['failed_samples'], 0)

    def test_confirmation_timeout_is_immediately_fatal_and_restores_alarm(self):
        health = audio.PeriodicStereoHealth({})
        previous = audio.signal.getsignal(audio.signal.SIGALRM)

        def expired(_):
            # Invoke the installed deadline handler without waiting in real time.
            audio.signal.getsignal(audio.signal.SIGALRM)(audio.signal.SIGALRM, None)

        with self.snapshots([self.bad_identity]), patch.object(audio.time, 'sleep', side_effect=expired):
            with self.assertRaises(audio.HealthConfirmationTimeout):
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(self.reads, 1)
        self.assertEqual(health.stats['aborted_events'], 1)
        self.assertEqual(audio.signal.getsignal(audio.signal.SIGALRM), previous)
        self.assertEqual(audio.signal.getitimer(audio.signal.ITIMER_REAL), (0, 0))

    def test_journal_rate_limit_preserves_every_transient_in_counters(self):
        health = audio.PeriodicStereoHealth({})
        with self.snapshots([self.bad_identity, self.good] * 3) as (_, journal), \
                patch.object(audio.time, 'monotonic', side_effect=[0, 1, 31]):
            for _ in range(3):
                health.check(self.mapping, self.paths, healthy=Mock())
        self.assertEqual(health.stats['transient_events'], 3)
        self.assertEqual(health.stats['failed_samples'], 3)
        self.assertEqual(health.stats['journal_suppressed_events'], 1)
        self.assertEqual(len(journal.getvalue().splitlines()), 2)
        self.assertIn('"journal_suppressed_events": 1', journal.getvalue())

    def serve(self, samples, *, periodic=True, gain_change=False):
        report = dict(action='play-desktop', playback_ready=True, microphone_capture=False,
                      pcm=dict(card='stub-card'), before=dict(boot_id='stub-boot', release='stub-kernel'))
        pcm, graph = Mock(), Mock()
        pcm.process.pid, pcm.feed_stats = 42, {}
        graph.monitor.input_peak, graph.monitor.peak = 0, 0
        graph.monitor.max_interarrival_seconds = 0
        with tempfile.TemporaryDirectory() as directory, self.snapshots(samples) as (_, journal):
            args = SimpleNamespace(output=Path(directory), serve_seconds=0, desktop_peak=1433)
            with patch.object(audio.signal, 'signal', wraps=audio.signal.signal), \
                    patch.object(audio.threading, 'Event') as event, \
                    patch.object(audio, 'set_desktop_pa_gain') as gain:
                waits = iter([False, True] if periodic else [True])

                def wait(_):
                    if gain_change:
                        (args.output / 'pa-gain-step').write_text('1\n')
                    return next(waits)

                event.return_value.wait.side_effect = wait
                try:
                    audio.serve_desktop(args, report, pcm, graph, self.paths, self.mapping)
                finally:
                    if periodic and 'serve' in report:
                        status = json.loads((args.output / 'serve-ready.json').read_text())
                        result = json.loads((args.output / 'play-desktop-result.json').read_text())
                        expected = json.loads(json.dumps(report['serve']['periodic_health']))
                        self.assertEqual(status['periodic_health'], expected)
                        self.assertEqual(result['serve']['periodic_health'], expected)
                        if gain_change:
                            gain.assert_called_once_with('stub-card', 1)
                            self.assertEqual(expected['failed_samples'], 0)
        return report, pcm, graph, journal.getvalue()

    def test_serve_continues_and_persists_transient_without_graph_teardown(self):
        report, pcm, graph, journal = self.serve([self.good, self.bad_identity, self.good])
        self.assertEqual(report['serve']['periodic_health']['transient_events'], 1)
        self.assertTrue(report['serve']['stopped'])
        graph.close.assert_not_called()
        pcm.close.assert_not_called()
        self.assertIn('transient', journal)

    def test_serve_fatal_record_contains_confirmation_samples(self):
        with self.assertRaisesRegex(RuntimeError, 'Unknown physical identity'):
            self.serve([self.good] + [self.bad_identity] * 3)
        self.assertEqual(self.reads, 4)

    def test_startup_check_stays_single_shot(self):
        for bad in (self.bad_identity, OSError(errno.EIO, 'startup read failed')):
            with self.subTest(bad=bad):
                with self.assertRaises((RuntimeError, OSError)):
                    self.serve([bad, self.good], periodic=False)
                self.assertEqual(self.reads, 1)

    def test_post_gain_write_check_stays_single_shot(self):
        with self.assertRaisesRegex(RuntimeError, 'Unknown physical identity'):
            self.serve([self.good, self.bad_identity, self.good], gain_change=True)
        self.assertEqual(self.reads, 2)  # Startup + strict post-write check only.


if __name__ == '__main__':
    unittest.main()
