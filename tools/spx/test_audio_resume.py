#!/usr/bin/python3
"""Offline safety contracts for the owned live-audio sleep window."""
import copy
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import audio
import audio_resume as resume
import trial


def args():
    return SimpleNamespace(parked_audio=False, verify_sleep_return=False,
                           allow_amp_power=True, allow_playback=True, allow_capture=True,
                           desktop_peak=1433, desktop_controls=False, desktop_user='dvitali')


def prepared():
    return dict(live_audio_resume=True, audio_mode='parked', slim_s2idle_retain=True,
                pmic_rtc=True, sensors_startup=True)


class Admission(unittest.TestCase):
    def test_explicit_opt_in_permissions_quiet_limit(self):
        resume.admission(prepared(), args())
        for name, value in (('live_audio_resume', False), ('pmic_rtc', False),
                            ('slim_s2idle_retain', False), ('sensors_startup', False),
                            ('audio_mode', 'blocked')):
            with self.subTest(name=name):
                changed = prepared(); changed[name] = value
                with self.assertRaises(AssertionError): resume.admission(changed, args())
        for name, value in (('allow_playback', False), ('allow_capture', False),
                            ('allow_amp_power', False), ('desktop_peak', 4000),
                            ('parked_audio', True), ('verify_sleep_return', True)):
            with self.subTest(name=name):
                changed = args(); setattr(changed, name, value)
                with self.assertRaises(AssertionError): resume.admission(prepared(), changed)

    def test_callback_admission_precedes_hardware(self):
        with patch.object(audio.os, 'geteuid') as hardware:
            with self.assertRaisesRegex(RuntimeError, 'quiet serve initialization'):
                audio.initialize(SimpleNamespace(action='serve', desktop_peak=4000), {}, live_resume=lambda *a: None)
        hardware.assert_not_called()


class Suspension(unittest.TestCase):
    def monitor(self):
        process = Mock(); process.poll.return_value = None
        result = audio.DesktopMonitor(process, ordinary=True); result.forward = False
        return result

    def test_finite_window_relaxes_only_delivery_stall(self):
        m = self.monitor()
        with patch.object(audio.time, 'clock_gettime', return_value=100), patch.object(audio.time, 'monotonic', return_value=50):
            m.begin_suspend(60); m.check_stall(0)
            m.forward = True
            with self.assertRaisesRegex(RuntimeError, 'forwarding enabled'): m.check_stall(0)
            m.forward = False; m.process.poll.return_value = 1
            with self.assertRaisesRegex(RuntimeError, 'process exited'): m.check_stall(0)
        m.process.poll.return_value = None
        with patch.object(audio.time, 'clock_gettime', return_value=161):
            with self.assertRaisesRegex(RuntimeError, 'window expired'): m.check_stall(0)
            with self.assertRaisesRegex(RuntimeError, 'window expired'): m.end_suspend()
        self.assertIsNone(m.suspend_until)

    def test_end_restores_two_second_deadline_and_retains_errors(self):
        m = self.monitor()
        with patch.object(audio.time, 'clock_gettime', return_value=100), patch.object(audio.time, 'monotonic', return_value=50):
            m.begin_suspend(); m.end_suspend(); m.check_stall(0)
        with patch.object(audio.time, 'monotonic', return_value=53):
            with self.assertRaisesRegex(RuntimeError, 'monitor stalled'): m.check_stall(0)
        m.error = 'level error'
        with self.assertRaisesRegex(RuntimeError, 'level error'): m.begin_suspend()

    def test_window_requires_drained_silence_and_valid_bound(self):
        m = self.monitor()
        for seconds in (0, 61):
            with self.assertRaisesRegex(RuntimeError, 'Invalid'): m.begin_suspend(seconds)
        m.blocks.put(b'queued')
        with self.assertRaisesRegex(RuntimeError, 'drained digital silence'): m.begin_suspend()

    def test_capture_wall_deadline_fails_after_real_sleep_even_if_monotonic_paused(self):
        capture = audio.OwnedCapture.__new__(audio.OwnedCapture)
        capture.stop = threading.Event(); capture.wall_deadline = 120; capture.error = None
        with patch.object(audio.time, 'clock_gettime', return_value=121), \
             patch.object(audio.time, 'monotonic', return_value=10), patch.object(audio.os, 'kill') as kill:
            capture.consume()
        self.assertIn('wall-clock deadline', capture.error)
        kill.assert_called_once()


class RetainedOwner(unittest.TestCase):
    def test_native_identity_geometry_initialization_must_survive(self):
        owner = resume.LiveOwnedAudio.__new__(resume.LiveOwnedAudio); owner.report = {}
        before = dict(processes={'capture': 10}, native_owners={'capture': {'pid': 10}},
                      geometry={'capture': 'unchanged'}, initialized_counts={'3': 1})
        for name in before:
            after = copy.deepcopy(before); after[name] = {'changed': True}
            owner.check = lambda: after
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, name): owner.retained(before)
        owner.check = lambda: copy.deepcopy(before)
        self.assertEqual(owner.retained(before), before)
        self.assertTrue(owner.report['same_native_owners'])

    def test_sleep_failure_ends_window_preserves_original_error(self):
        graph = Mock(); graph.monitor.end_suspend.side_effect = RuntimeError('cleanup failure')
        ops = Mock(); ops.sleep.side_effect = RuntimeError('normal sleep failed')
        contract = Mock(report={'held': {}}); result = {'before': {}}
        with patch.object(resume, 'quiet'), patch.object(resume, 'LiveOwnedAudio', return_value=contract):
            with self.assertRaisesRegex(RuntimeError, 'normal sleep failed'):
                resume.retained_window(ops, result, {'public_desktop': {'acoustic_passed': True}}, Mock(), graph, Mock(), {}, {})
        graph.monitor.end_suspend.assert_called_once()
        self.assertEqual(result['monitor_window_cleanup_error'], 'cleanup failure'); ops.post.assert_not_called()

    def test_failure_restores_parked_observer_before_cleanup(self):
        events = []; ops = Mock(); ops.output = Path('/private/audio-resume')
        lease = object(); ops.audio = lease; ops.gate.return_value = {}; ops.direct.return_value = {'complete': True}
        def initialize(*a, **kwargs):
            events.append('park-and-close-attempted'); ops.audio = object()
            raise RuntimeError('resume prepare rejected')
        def cleanup():
            self.assertIs(ops.audio, lease); events.append('closed-PCM-lease-check')
            return {'masks_restored': True}
        ops.cleanup.side_effect = cleanup
        with patch.object(Path, 'read_text', return_value='{}'), patch.object(resume, 'admission'), patch.object(audio, 'initialize', side_effect=initialize):
            result = resume.exercise(ops, args(), 'owned')
        self.assertFalse(result['complete']); self.assertIn('resume prepare rejected', result['error'])
        self.assertEqual(events, ['park-and-close-attempted', 'closed-PCM-lease-check']); ops.save.assert_called()


class Dispatch(unittest.TestCase):
    def test_no_default_or_repeated_failed_attempt_dispatch(self):
        with patch.object(trial, 'OUT', Path('/private'), create=True), patch.object(Path, 'exists', return_value=True), patch.object(trial.subprocess, 'run') as run:
            trial.dispatch_live_audio_resume(args(), {})
            trial.dispatch_live_audio_resume(args(), prepared())
        run.assert_not_called()

    def test_prepared_dispatch_only_after_same_boot_completed_baseline(self):
        import json
        with patch.object(trial, 'OUT', Path('/private'), create=True), \
             patch.object(trial, 'ATTEMPT', '20261007dw', create=True), \
             patch.object(trial, 'RELEASE', 'test-kernel', create=True), \
             patch.object(trial, 'BOOT_ID', 'boot-id', create=True), \
             patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'read_text', return_value=json.dumps(dict(complete=True, boot_id='boot-id', release='test-kernel'))), \
             patch.object(trial.subprocess, 'run') as run:
            trial.dispatch_live_audio_resume(args(), prepared())
        argv = run.call_args.args[0]
        self.assertIn('--unit=spx-systemd-suspend', argv); self.assertIn('--property=RuntimeMaxSec=200', argv)
        self.assertIn('--live-audio-resume', argv); self.assertIn('--allow-capture', argv)
        self.assertEqual(run.call_args.kwargs, dict(check=True, timeout=205))


if __name__ == '__main__': unittest.main()
