#!/usr/bin/env python3
"""Offline checks only: generated samples, PCM pipe writes and permission gates."""
import importlib.util
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
