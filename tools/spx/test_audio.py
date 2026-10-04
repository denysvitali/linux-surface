#!/usr/bin/env python3
"""Offline checks only: generated samples, PCM pipe writes and permission gates."""
import importlib.util
import os
from pathlib import Path
import queue
import struct
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
