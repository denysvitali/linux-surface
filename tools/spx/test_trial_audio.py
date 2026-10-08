#!/usr/bin/env python3
"""Exercise consumed-once audio requests and automatic return on failure."""
import importlib.util
import json
import io
import sys
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
        (self.out / 'installed.json').write_text(json.dumps(dict(boot_id='old-boot')))
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
    def test_prepare_trial_install_recovery_arm_and_consume_next_boot(self):
        storage = self.out / '20261004bq'
        storage.mkdir()
        (storage / 'prepared.json').write_text(json.dumps(dict(
            audio_mode='parked', preboot_id='prepared-trial', release='test-kernel')))
        (storage / 'installed.json').write_text(json.dumps(dict(boot_id='recovery-boot')))
        (self.proc / 'boot_id').write_text('recovery-boot')
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        def paths(value):
            return self.out if value == '/var/lib/spx-boot-diagnostics/functional' else self.path(value)
        argv = ['trial.py', 'arm-audio', '20261004bq', '--audio-action', 'desktop-mic',
                '--capture-reopen', '--allow-amp-power', '--allow-playback', '--allow-capture']
        with patch.object(trial, 'Path', side_effect=paths), patch.object(sys, 'argv', argv), \
                patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.os, 'uname', return_value=SimpleNamespace(release='6.18.3-1-surface+')), \
                patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.main()
        record = json.loads((storage / 'audio-request.json').read_text())
        self.assertEqual(record['preboot_id'], 'recovery-boot')
        (self.proc / 'boot_id').write_text('new-boot')
        with patch.object(trial, 'BOOT_ID', 'prepared-trial'), \
                patch.object(trial, 'audio_check') as hardware:
            trial.requested_audio(SimpleNamespace())
        self.assertTrue(hardware.call_args.args[0].capture_reopen)
        self.assertTrue((storage / 'audio-started.json').exists())

    def test_request_from_different_installation_boot_rejects_before_hardware(self):
        (self.out / 'installed.json').write_text(json.dumps(dict(boot_id='other-recovery')))
        self.write_request()
        with patch.object(trial, 'audio_check') as hardware:
            with self.assertRaises(AssertionError):
                trial.requested_audio(self.args)
            hardware.assert_not_called()
        self.assertTrue((self.out / 'audio-request.json').exists())

    def test_array_cli_rejects_wrong_actions_before_hardware(self):
        for command, action, source in (('prepare', 'feedback', 'DMIC1'),
                                        ('audio', 'desktop-mic', 'DMIC1'),
                                        ('arm-audio', 'feedback', 'DMIC0')):
            with self.subTest(command=command, action=action), \
                    patch.object(sys, 'argv', ['trial.py', command, '20261007dj',
                        '--audio-action', action, '--microphone-source', source, '--microphone-array']), \
                    patch.object(sys, 'stderr', io.StringIO()), \
                    patch.object(trial, 'audio_check') as check:
                with self.assertRaises(SystemExit) as stopped:
                    trial.main()
                self.assertEqual(stopped.exception.code, 2)
                check.assert_not_called()

    def test_array_recorded_and_forwarded_direct_and_armed(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        (self.out / 'installed.json').touch()
        args = SimpleNamespace(audio_action='feedback', microphone_source='DMIC1',
            microphone_array=True, allow_amp_power=True, allow_playback=True, allow_capture=True,
            desktop_user='dvitali', return_after_audio_seconds=None)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        self.assertTrue(json.loads((self.out / 'audio-request.json').read_text())['microphone_array'])
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=account), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertIn('--microphone-array', opened.call_args.args[0])
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(SimpleNamespace())
        self.assertTrue(check.call_args.args[0].microphone_array)

    def test_contract_cli_gate_and_request_gate_precede_hardware(self):
        for command, action, reopen in (('prepare', 'desktop-mic', True),
                                        ('audio', 'feedback', True), ('arm-audio', 'desktop-mic', False)):
            argv = ['trial.py', command, '20261007dl', '--audio-action', action,
                    '--capture-contract-check'] + (['--capture-reopen'] if reopen else [])
            with self.subTest(command=command, action=action), \
                    patch.object(sys, 'argv', argv), patch.object(sys, 'stderr', io.StringIO()), \
                    patch.object(trial, 'audio_check') as hardware:
                with self.assertRaises(SystemExit) as stopped:
                    trial.main()
                self.assertEqual(stopped.exception.code, 2)
                hardware.assert_not_called()
        self.request.update(capture_contract_check=True)
        self.write_request()
        with patch.object(trial, 'audio_check') as hardware:
            with self.assertRaisesRegex(AssertionError, 'requires desktop-mic --capture-reopen'):
                trial.requested_audio(self.args)
            hardware.assert_not_called()
        self.assertTrue((self.out / 'audio-request.json').exists())

    def test_contract_recorded_and_forwarded_direct_and_armed(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        (self.out / 'installed.json').touch()
        args = SimpleNamespace(audio_action='desktop-mic', capture_reopen=True,
            capture_contract_check=True, allow_amp_power=True, allow_playback=True, allow_capture=True,
            desktop_user='dvitali', return_after_audio_seconds=None)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        self.assertTrue(json.loads((self.out / 'audio-request.json').read_text())['capture_contract_check'])
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=account), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertIn('--capture-contract-check', opened.call_args.args[0])
        self.assertIn('--capture-reopen', opened.call_args.args[0])
        with patch.object(trial, 'audio_check') as hardware:
            trial.requested_audio(SimpleNamespace())
        self.assertTrue(hardware.call_args.args[0].capture_contract_check)

    def test_native_microphone_request_rejects_conflict_before_consumption(self):
        self.request.update(action='desktop-mic', native_mic_on_demand=True,
                            capture_reopen=True, playback=True, capture=True)
        self.write_request()
        with patch.object(trial, 'audio_check') as hardware:
            with self.assertRaisesRegex(AssertionError, 'native-mic-on-demand'):
                trial.requested_audio(self.args)
        hardware.assert_not_called()
        self.assertTrue((self.out / 'audio-request.json').exists())

    def test_native_microphone_recorded_and_forwarded_direct_and_armed(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        (self.out / 'installed.json').touch()
        args = SimpleNamespace(audio_action='desktop-mic', native_mic_on_demand=True,
            allow_amp_power=True, allow_playback=True, allow_capture=True,
            desktop_user='dvitali', return_after_audio_seconds=None)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        self.assertTrue(json.loads((self.out / 'audio-request.json').read_text())['native_mic_on_demand'])
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=account), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertIn('--native-mic-on-demand', opened.call_args.args[0])
        with patch.object(trial, 'audio_check') as hardware:
            trial.requested_audio(SimpleNamespace())
        self.assertTrue(hardware.call_args.args[0].native_mic_on_demand)

    def test_capture_reopen_cli_rejects_other_actions_before_lock(self):
        for command, action in (('prepare', 'desktop-mic'), ('audio', 'feedback'),
                                ('arm-audio', 'reopen'), ('check', 'desktop-mic')):
            with self.subTest(command=command, action=action), \
                    patch.object(sys, 'argv', ['trial.py', command, '20261007di',
                                               '--audio-action', action, '--capture-reopen']), \
                    patch.object(sys, 'stderr', io.StringIO()), \
                    patch.object(trial, 'audio_check') as check, \
                    patch.object(trial, 'require_source_boot') as boot:
                with self.assertRaises(SystemExit) as stopped:
                    trial.main()
                self.assertEqual(stopped.exception.code, 2)
                check.assert_not_called()
                boot.assert_not_called()

    def test_capture_reopen_is_recorded_and_passed_to_native_helper(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        (self.out / 'installed.json').touch()
        args = SimpleNamespace(audio_action='desktop-mic', microphone_source='DMIC1',
                               capture_reopen=True, allow_amp_power=True, allow_playback=True,
                               allow_capture=True, desktop_user='dvitali',
                               return_after_audio_seconds=None, serve_seconds=3600, desktop_peak=1433)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        self.assertTrue(json.loads((self.out / 'audio-request.json').read_text())['capture_reopen'])
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=account), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertIn('--capture-reopen', opened.call_args.args[0])
        args.audio_action = 'feedback'
        trial.subprocess.run.reset_mock()
        with self.assertRaisesRegex(AssertionError, 'requires desktop-mic'):
            trial.arm_audio(args)
        with self.assertRaisesRegex(AssertionError, 'requires desktop-mic'):
            trial.audio_check(args)
        trial.subprocess.run.assert_not_called()

    def test_capture_reopen_request_forwarded_and_invalid_action_rejected(self):
        self.request.update(action='desktop-mic', capture_reopen=True,
                            playback=True, capture=True, serve_seconds=None)
        self.write_request()
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(self.args)
        self.assertTrue(check.call_args.args[0].capture_reopen)
        for action in ('plan', 'feedback', 'capture', 'reopen', 'serve'):
            with self.subTest(action=action), self.assertRaisesRegex(AssertionError, 'requires desktop-mic'):
                trial.validate_capture_reopen(action, True)

    def test_serve_is_consumed_before_hardware_and_failure_keeps_return(self):
        self.write_request()

        def fail(args):
            self.assertFalse((self.out / 'audio-request.json').exists())
            self.assertTrue((self.out / 'audio-started.json').exists())
            self.assertEqual(args.serve_seconds, 3600)
            self.assertEqual(args.microphone_source, 'DMIC1')
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

    def test_desktop_mic_dmic0_request_is_bounded_and_consumed_once(self):
        self.request.update(action='desktop-mic', microphone_source='DMIC0',
                            return_after_audio_seconds=61)
        self.write_request()
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(self.args)
            self.assertEqual(self.args.audio_action, 'desktop-mic')
            self.assertEqual(self.args.microphone_source, 'DMIC0')
            self.assertTrue(self.args.allow_amp_power and self.args.allow_playback and
                            self.args.allow_capture)
            self.assertFalse((self.out / 'audio-request.json').exists())
            trial.requested_audio(self.args)
            check.assert_called_once()
        self.assertEqual(self.windows, [162])

    def test_missing_capture_authorization_is_rejected_before_consumption(self):
        self.request['capture'] = False
        self.write_request()
        with patch.object(trial, 'audio_check') as audio_check:
            with self.assertRaises(AssertionError):
                trial.requested_audio(self.args)
            audio_check.assert_not_called()
        self.assertTrue((self.out / 'audio-request.json').exists())
        self.assertEqual(self.windows, [])

    def test_dmic0_feedback_request_reaches_audio_once(self):
        self.request.update(action='feedback', microphone_source='DMIC0',
                            return_after_audio_seconds=61)
        self.write_request()
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(self.args)
            trial.requested_audio(self.args)
            check.assert_called_once()
            self.assertEqual(check.call_args.args[0].microphone_source, 'DMIC0')
        self.assertEqual(self.windows, [162])

    def test_invalid_or_unsupported_source_is_rejected_before_claim(self):
        for action, source in (('feedback', 'DMIC2'), ('feedback', None),
                               ('feedback', True), ('serve', 'DMIC0'),
                               ('desktop', 'DMIC0'), ('reopen', 'DMIC0'),
                               ('initialize', 'DMIC0')):
            with self.subTest(action=action, source=source):
                self.request.update(action=action, microphone_source=source)
                self.write_request()
                with patch.object(trial, 'claim_audio_boot') as claim, \
                        patch.object(trial, 'audio_check') as check:
                    with self.assertRaises(AssertionError):
                        trial.requested_audio(self.args)
                    claim.assert_not_called()
                    check.assert_not_called()
                self.assertTrue((self.out / 'audio-request.json').exists())
                self.assertFalse((self.out / 'audio-started.json').exists())
        self.assertEqual(self.windows, [])

    def test_arm_feedback_records_source(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        (self.out / 'installed.json').touch()
        self.args = SimpleNamespace(audio_action='feedback', microphone_source='DMIC0',
                                    allow_amp_power=True, allow_playback=True, allow_capture=True,
                                    serve_seconds=3600, desktop_peak=1433, desktop_user='dvitali',
                                    return_after_audio_seconds=61)
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_name='dvitali')):
            trial.arm_audio(self.args)
        record = json.loads((self.out / 'audio-request.json').read_text())
        self.assertEqual(record['microphone_source'], 'DMIC0')
        self.assertTrue(record['playback'] and record['capture'] and record['allow_amp_power'])

    def test_direct_audio_passes_source_and_rejects_invalid_source_before_lock(self):
        args = SimpleNamespace(audio_action='capture', microphone_source='DMIC0',
                               allow_capture=True, desktop_user='dvitali')
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_name='dvitali')), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        command = opened.call_args.args[0]
        self.assertEqual(command[command.index('--microphone-source') + 1], 'DMIC0')
        self.assertIn('--allow-capture', command)
        self.assertNotIn('--allow-amp-power', command)
        self.assertNotIn('--allow-playback', command)
        args.audio_action = 'serve'
        trial.subprocess.run.reset_mock()
        with self.assertRaisesRegex(AssertionError, 'requires capture or feedback'):
            trial.audio_check(args)
        trial.subprocess.run.assert_not_called()

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
