#!/usr/bin/env python3
"""Exercise consumed-once audio requests and automatic return on failure."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class AudioRequestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)
        self.proc = self.out / 'proc'
        self.proc.mkdir()
        (self.proc / 'cmdline').write_text('spx_attempt=20261004bq spx_audio=parked')
        (self.proc / 'boot_id').write_text('new-boot')
        (self.proc / 'uptime').write_text('100.0 0.0')
        self.request = dict(attempt='20261004bq', release='test-kernel',
                            preboot_id='old-boot', action='serve',
                            allow_amp_power=True, playback=True, capture=True,
                            desktop_user='dvitali', serve_seconds=3600,
                            return_after_audio_seconds=None)
        self.args = SimpleNamespace()
        self.windows = []
        self.start_patch(patch.multiple(trial, OUT=self.out, ATTEMPT='20261004bq',
                                       RELEASE='test-kernel', BOOT_ID='old-boot', create=True))
        self.start_patch(patch.object(trial.os, 'uname', return_value=SimpleNamespace(release='test-kernel')))
        self.start_patch(patch.object(trial, 'Path', side_effect=self.path))
        self.start_patch(patch.object(trial, 'extend_window',
                                     side_effect=lambda args: self.windows.append(args.return_seconds)))
        self.start_patch(patch.object(trial.subprocess, 'run'))

    def start_patch(self, p):
        self.addCleanup(p.stop)
        return p.start()

    def path(self, value):
        redirects = {'/proc/cmdline': 'cmdline', '/proc/sys/kernel/random/boot_id': 'boot_id',
                     '/proc/uptime': 'uptime'}
        return self.proc / redirects[value] if value in redirects else Path(value)

    def write_request(self):
        (self.out / 'audio-request.json').write_text(json.dumps(self.request))

    def test_serve_is_consumed_before_hardware_and_failure_keeps_return(self):
        self.write_request()

        def fail(args):
            self.assertFalse((self.out / 'audio-request.json').exists())
            self.assertTrue((self.out / 'audio-started.json').exists())
            self.assertEqual(args.serve_seconds, 3600)
            self.assertEqual(self.windows, [3880])
            raise RuntimeError('simulated initialization failure')

        with patch.object(trial, 'audio_check', side_effect=fail) as audio_check:
            with self.assertRaisesRegex(RuntimeError, 'initialization failure'):
                trial.requested_audio(self.args)
            self.assertEqual(self.windows, [3880, 162])
            trial.requested_audio(self.args)
            audio_check.assert_called_once()
        self.assertTrue((self.out / 'kernel.log').exists())
        self.assertTrue((self.out / 'journal.log').exists())

    def test_missing_capture_authorization_is_rejected_before_consumption(self):
        self.request['capture'] = False
        self.write_request()
        with patch.object(trial, 'audio_check') as audio_check:
            with self.assertRaises(AssertionError):
                trial.requested_audio(self.args)
            audio_check.assert_not_called()
        self.assertTrue((self.out / 'audio-request.json').exists())
        self.assertEqual(self.windows, [])

    def test_invalid_session_duration_is_rejected_before_consumption(self):
        for duration in (-1, 82801, True, '3600'):
            with self.subTest(duration=duration):
                self.request['serve_seconds'] = duration
                self.write_request()
                with self.assertRaises(AssertionError):
                    trial.requested_audio(self.args)
                self.assertTrue((self.out / 'audio-request.json').exists())
                self.assertEqual(self.windows, [])

    def test_untimed_audio_does_not_remove_boot_fallback(self):
        self.request['serve_seconds'] = 0
        self.write_request()

        def finish(args):
            self.assertEqual(args.serve_seconds, 0)
            self.assertEqual(self.windows, [])

        with patch.object(trial, 'audio_check', side_effect=finish):
            trial.requested_audio(self.args)
        self.assertEqual(self.windows, [162])

    def test_requested_desktop_peak_reaches_audio_check(self):
        self.request['desktop_peak'] = 4000
        self.write_request()
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(self.args)
            self.assertEqual(check.call_args.args[0].desktop_peak, 4000)

    def test_invalid_desktop_peak_is_rejected_before_consumption(self):
        for peak in (1432, 12001, True, '4000'):
            with self.subTest(peak=peak):
                self.request['desktop_peak'] = peak
                self.write_request()
                with self.assertRaises(AssertionError):
                    trial.requested_audio(self.args)
                self.assertTrue((self.out / 'audio-request.json').exists())
                self.assertEqual(self.windows, [])

    def test_existing_desktop_request_retains_short_test_behavior(self):
        self.request.update(action='desktop', serve_seconds=None, return_after_audio_seconds=61)
        self.write_request()
        with patch.object(trial, 'audio_check') as audio_check:
            trial.requested_audio(self.args)
            audio_check.assert_called_once()
        self.assertEqual(self.windows, [162])
        self.assertFalse(hasattr(self.args, 'serve_seconds'))


if __name__ == '__main__':
    unittest.main()
