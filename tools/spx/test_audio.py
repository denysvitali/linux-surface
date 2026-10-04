#!/usr/bin/env python3
"""Offline checks only: generated samples, PCM pipe writes and permission gates."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('spx_audio', Path(__file__).with_name('audio.py'))
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class AudioTests(unittest.TestCase):
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
        reader, writer = os.pipe()
        monitor = audio.DesktopMonitor(SimpleNamespace(
            stdout=os.fdopen(reader, 'rb', buffering=0), poll=lambda: None), ordinary=True)
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
                expected = [(int(left * 1433 / 32768), int(right * 1433 / 32768))
                            for left, right in frames]
                self.assertEqual(list(struct.iter_unpack('<hh', received)), expected)
                self.assertEqual(monitor.input_peak, 32768)
                self.assertEqual(monitor.peak, 1433)
                self.assertIsNone(monitor.error)
                abort.assert_not_called()
            finally:
                monitor.stop.set()
                producer.join(timeout=2)
                monitor.thread.join(timeout=2)
                monitor.process.stdout.close()
                os.close(writer)

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

    def test_serve_ready_precedes_signal_stop_and_retains_the_pcm(self):
        report = {'action': 'serve', 'desktop': {'acoustic_passed': True},
                  'public_desktop': {'acoustic_passed': True}, 'recording_closed': True,
                  'before': {'boot_id': 'test-boot', 'release': 'test-kernel'}}
        pcm, graph = Mock(), Mock()
        pcm.process.pid = 123
        monitor = graph.monitor
        monitor.input_peak, monitor.peak = 32768, 1433
        handlers = {}

        def handler(signum, callback):
            previous = handlers.get(signum)
            handlers[signum] = callback
            return previous

        class StopAfterReady:
            stopped = False

            def wait(self, seconds):
                ready = json.loads((output / 'serve-ready.json').read_text())
                self_test.assertTrue(ready['recording_closed'])
                self_test.assertTrue(ready['public_acoustic_passed'])
                self_test.assertEqual(ready['pcm_pid'], 123)
                handlers[audio.signal.SIGTERM](audio.signal.SIGTERM, None)
                return self.stopped

            def set(self):
                self.stopped = True

            def is_set(self):
                return self.stopped

        self_test = self
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            args = SimpleNamespace(output=output, serve_seconds=3600)
            with patch.object(audio.threading, 'Event', StopAfterReady), \
                    patch.object(audio.signal, 'signal', side_effect=handler), \
                    patch.object(audio, 'check_stereo'):
                audio.serve_desktop(args, report, pcm, graph, {}, {})
        self.assertEqual(report['serve']['stop_reason'], 'SIGTERM')
        self.assertEqual(report['serve']['output_peak'], 1433)
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
        graph.monitor.peak = 1433
        starts = []

        def play(payload, name):
            starts.append(counter[0])
            graph.monitor.input_peak = 32767
            counter[0] += 96000

        graph.play.side_effect = play
        report = {}
        with patch.object(audio.threading, 'Timer'), \
                patch.object(audio, 'tone', return_value=b'full-scale input') as tone, \
                patch.object(acoustic, 'score_phase', return_value={'passed': True, 'reason': 'detected'}) as score:
            audio.verify_public_playback(report, pcm, graph, capture)
        tone.assert_called_once_with({0, 1}, amplitude=32767)
        graph.connect_public.assert_called_once_with(pcm)
        self.assertEqual(score.call_args.args[1], (starts[0] - 96000, starts[0]))
        self.assertEqual(score.call_args.args[2], [440, 660])
        self.assertEqual(graph.require_public_idle.call_count, 3)
        self.assertTrue(report['public_desktop']['acoustic_passed'])
        self.assertEqual(report['public_desktop']['public_volume']['current'], [65536, 65536])
        self.assertEqual(report['public_desktop']['public_volume']['prior'], ['25559', '25559'])
        capture.close.assert_not_called()  # Caller closes only after this score succeeds.

    def test_serve_permission_and_duration_bounds(self):
        args = SimpleNamespace(action='serve', allow_amp_power=True,
                               allow_playback=True, allow_capture=False)
        with patch.object(audio.os, 'geteuid', return_value=0), \
                patch.object(audio, 'parameter', side_effect=AssertionError('hardware read')):
            with self.assertRaisesRegex(RuntimeError, 'allow-capture'):
                audio.initialize(args, {})
        self.assertEqual(audio.serve_duration('1'), 1)
        self.assertEqual(audio.serve_duration('86400'), 86400)
        for value in ('0', '86401'):
            with self.assertRaises(audio.argparse.ArgumentTypeError):
                audio.serve_duration(value)

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

        source = SimpleNamespace(healthy=healthy, blocks=queue.Queue())
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


if __name__ == '__main__':
    unittest.main()
