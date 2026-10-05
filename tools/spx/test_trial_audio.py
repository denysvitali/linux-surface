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


class TrialAudioFixture(unittest.TestCase):
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


class AudioRequestTests(TrialAudioFixture):
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
        self.assertEqual(self.windows, [])

    def test_untimed_failure_preserves_hardware_trial_window(self):
        self.request['serve_seconds'] = 0
        self.write_request()
        with patch.object(trial, 'audio_check', side_effect=RuntimeError('failed')) as audio_check:
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                trial.requested_audio(self.args)
            trial.requested_audio(self.args)
            audio_check.assert_called_once()
        self.assertEqual(self.windows, [])
        self.assertTrue((self.out / 'journal.log').exists())

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

    def test_reopen_request_is_consumed_once_and_keeps_return_timer(self):
        self.request.update(action='reopen', serve_seconds=None, return_after_audio_seconds=120)
        self.write_request()
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(self.args)
            trial.requested_audio(self.args)
            check.assert_called_once()
            self.assertEqual(check.call_args.args[0].audio_action, 'reopen')
            self.assertTrue(check.call_args.args[0].allow_capture)
        self.assertEqual(self.windows, [221])

    def test_existing_desktop_request_retains_short_test_behavior(self):
        self.request.update(action='desktop', serve_seconds=None, return_after_audio_seconds=61)
        self.write_request()
        with patch.object(trial, 'audio_check') as audio_check:
            trial.requested_audio(self.args)
            audio_check.assert_called_once()
        self.assertEqual(self.windows, [162])
        self.assertFalse(hasattr(self.args, 'serve_seconds'))


class DesktopOptInTests(TrialAudioFixture):
    def setUp(self):
        super().setUp()
        self.args = SimpleNamespace(desktop_user='dvitali', desktop_peak=4000)
        (self.proc / 'cmdline').write_text(
            'spx_attempt=20261004bq spx_audio=parked spx_boot=mainline-functional')
        self.save('functional.json', dict(complete=True, boot_id='new-boot', release='test-kernel'))
        self.ready = dict(boot_id='new-boot', release='test-kernel', acoustic_passed=True,
                          public_acoustic_passed=True, recording_closed=True,
                          sink='spx_speakers', owner_pid=2276, pcm_pid=2343,
                          peak_limit=4000, pa_gain=0)
        self.save('audio/serve-ready.json', self.ready)
        self.save('audio/serve-result.json', dict(serve=self.ready))
        command = ['python3', '/usr/local/lib/spx-boot-diagnostics/audio.py', 'serve',
                   '--output', str(self.out / 'audio'), '--owner', 'audio-20261004bq',
                   '--desktop-user', 'dvitali', '--desktop-peak', '4000']
        for name, value in {
                '2276/cmdline': '\0'.join(command) + '\0',
                '2276/status': 'Uid:\t0\t0\t0\t0\n',
                '2343/comm': 'aplay\n', '2343/status': 'PPid:\t2276\n',
                'asound/card0/pcm0p/sub0/status': 'state: RUNNING\nowner_pid : 2343\n',
                'asound/card0/pcm1c/sub0/status': 'closed\n'}.items():
            target = self.proc / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)
        (self.out / 'lock-owner').write_text('audio-20261004bq\n')
        self.start_patch(patch.object(trial.os, 'geteuid', return_value=0))
        self.start_patch(patch.object(trial.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)))
        # The suite is unprivileged; emulate only policy ownership, retaining
        # real regular-file and permission checks on its actual on-disk mode.
        original_lstat = Path.lstat
        self.policy_uid = 0

        def lstat(path):
            result = original_lstat(path)
            if path == self.out / 'desktop-audio.json':
                return SimpleNamespace(st_uid=self.policy_uid, st_mode=result.st_mode)
            return result

        self.start_patch(patch.object(Path, 'lstat', autospec=True, side_effect=lstat))
        self.audio = self.start_patch(patch.object(trial, 'audio_check'))

    def path(self, value):
        value = str(value)
        if value == '/tmp/spx-locks/spx-device.lock/owner':
            return self.out / 'lock-owner'
        if value.startswith('/proc/') and value not in (
                '/proc/cmdline', '/proc/sys/kernel/random/boot_id', '/proc/uptime'):
            return self.proc / value.removeprefix('/proc/')
        return super().path(value)

    def save(self, name, value):
        target = self.out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))

    def next_boot(self, boot='next-boot'):
        (self.proc / 'boot_id').write_text(boot)
        self.save('functional.json', dict(complete=True, boot_id=boot, release='test-kernel'))

    def test_enable_checks_live_ownership_and_does_not_restart_current_stream(self):
        trial.enable_desktop_audio(self.args)
        self.assertEqual((self.out / 'desktop-audio.json').stat().st_mode & 0o777, 0o600)
        trial.dispatch_audio(self.args)
        self.audio.assert_not_called()
        self.assertTrue((self.out / 'audio/serve-ready.json').exists())
        self.assertEqual(self.windows, [])
        trial.subprocess.run.assert_not_called()

    def test_stale_ready_wrong_owner_open_capture_and_failed_check_cannot_enable(self):
        mutations = [('audio/serve-ready.json', json.dumps(dict(self.ready, boot_id='old-boot'))),
                     ('proc/asound/card0/pcm0p/sub0/status', 'state: RUNNING\nowner_pid : 1111\n'),
                     ('proc/asound/card0/pcm1c/sub0/status', 'state: RUNNING\nowner_pid : 2000\n'),
                     ('proc/2276/cmdline', 'python3\0unrelated.py\0'),
                     ('lock-owner', 'someone-else'),
                     ('functional.json', json.dumps(dict(complete=False, boot_id='new-boot', release='test-kernel')))]
        for name, content in mutations:
            with self.subTest(name=name):
                path = self.out / name
                original = path.read_text()
                path.write_text(content)
                try:
                    with self.assertRaises(AssertionError):
                        trial.enable_desktop_audio(self.args)
                    self.assertFalse((self.out / 'desktop-audio.json').exists())
                finally:
                    path.write_text(original)
        self.audio.assert_not_called()

    def test_next_boot_consumes_once_archives_proof_and_never_changes_return(self):
        trial.enable_desktop_audio(self.args)
        self.next_boot()

        def started(args):
            self.assertFalse((self.out / 'audio/serve-ready.json').exists())
            self.assertTrue((self.out / 'audio-started-boots/next-boot.json').exists())
            self.assertEqual((args.audio_action, args.serve_seconds, args.desktop_peak), ('serve', 0, 4000))
            self.assertTrue(args.allow_capture and args.allow_playback and args.allow_amp_power)

        self.audio.side_effect = started
        trial.dispatch_audio(self.args)
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()
        for name in ('serve-ready.json', 'serve-result.json'):
            self.assertTrue((self.out / 'audio/boots/new-boot' / name).exists())
        self.assertEqual(self.windows, [])
        trial.subprocess.run.assert_not_called()

    def test_startup_failure_quarantines_and_never_repeats_on_later_boot(self):
        trial.enable_desktop_audio(self.args)
        self.next_boot()
        self.audio.side_effect = RuntimeError('acoustic verification failed')
        with self.assertRaisesRegex(RuntimeError, 'acoustic verification failed'):
            trial.dispatch_audio(self.args)
        self.assertFalse((self.out / 'desktop-audio.json').exists())
        self.assertTrue((self.out / 'desktop-audio-failed-next-boot.json').exists())
        trial.dispatch_audio(self.args)
        self.next_boot('third-boot')
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()
        self.assertEqual(self.windows, [])

    def test_interrupted_start_without_matching_ready_is_quarantined_next_boot(self):
        trial.enable_desktop_audio(self.args)
        self.next_boot()
        # Returning without a readiness file models the on-disk state after a
        # hard kill before initialization could report success or failure.
        trial.dispatch_audio(self.args)
        self.next_boot('third-boot')
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()
        self.assertFalse((self.out / 'desktop-audio.json').exists())
        self.assertEqual(self.windows, [])

    def test_verified_previous_start_can_run_once_on_another_boot(self):
        trial.enable_desktop_audio(self.args)
        self.next_boot()

        def ready(args):
            self.ready['boot_id'] = (self.proc / 'boot_id').read_text()
            self.save('audio/serve-ready.json', self.ready)
            self.save('audio/serve-result.json', dict(serve=self.ready))

        self.audio.side_effect = ready
        trial.dispatch_audio(self.args)
        self.next_boot('third-boot')
        trial.dispatch_audio(self.args)
        self.assertEqual(self.audio.call_count, 2)
        self.assertEqual(self.windows, [])

    def test_one_shot_wins_and_restart_cannot_fall_through_to_policy(self):
        trial.enable_desktop_audio(self.args)
        self.next_boot()
        self.request['serve_seconds'] = 0
        self.write_request()
        trial.dispatch_audio(self.args)
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()
        self.assertTrue((self.out / 'audio-started.json').exists())
        self.assertEqual(self.windows, [])  # Untimed restore keeps the trial window.

    def test_mismatched_or_untrusted_policy_cannot_start_audio(self):
        trial.enable_desktop_audio(self.args)
        self.next_boot()
        policy = self.out / 'desktop-audio.json'
        record = json.loads(policy.read_text())
        for changed in (dict(record, attempt='20261004wrong'),
                        dict(record, release='different'), dict(record, desktop_peak=12001)):
            self.save('desktop-audio.json', changed)
            with self.assertRaises(AssertionError):
                trial.dispatch_audio(self.args)
        self.save('desktop-audio.json', record)
        policy.chmod(0o666)
        with self.assertRaises(AssertionError):
            trial.dispatch_audio(self.args)
        policy.chmod(0o600)
        self.policy_uid = 1000
        with self.assertRaises(AssertionError):
            trial.dispatch_audio(self.args)
        self.audio.assert_not_called()


if __name__ == '__main__':
    unittest.main()
