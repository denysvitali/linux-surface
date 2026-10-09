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


class AudioCmdlineTests(unittest.TestCase):
    def test_enable_removes_only_audio_blacklist_and_parks_amplifiers(self):
        original = ['root=/dev/spx/root', 'wcd934x.spx_wsa_en_pin=2',
                    'module_blacklist=wcd934x,soundwire_qcom,unrelated',
                    'module_blacklist=snd-soc-wsa881x,snd_soc_wcd934x']
        result = trial.audio_cmdline(original, True)
        self.assertIn('module_blacklist=unrelated', result)
        self.assertIn('root=/dev/spx/root', result)
        self.assertNotIn('wcd934x.spx_wsa_en_pin=2', result)
        self.assertIn('wcd934x.spx_wsa_en_pin=-1', result)
        self.assertIn('wcd934x.spx_wsa_gpio_val=0x18', result)
        self.assertIn('spx_audio=parked', result)
        self.assertEqual(trial.audio_cmdline(result, True), result)

    def test_enable_drops_empty_blacklist(self):
        result = trial.audio_cmdline(['module_blacklist=wcd934x'], True)
        self.assertFalse(any(w.startswith('module_blacklist=') for w in result))

    def test_disable_preserves_unrelated_blocks_and_removes_audio_marker(self):
        result = trial.audio_cmdline(['spx_audio=parked',
                                      'module_blacklist=unrelated'], False)
        self.assertNotIn('spx_audio=parked', result)
        block = [w for w in result if w.startswith('module_blacklist=')]
        self.assertEqual(len(block), 1)
        self.assertEqual(set(block[0].split('=', 1)[1].split(',')),
                         {'unrelated', 'wcd934x', 'soundwire_qcom',
                          'snd_soc_wsa881x', 'snd_soc_wcd934x'})


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

    def test_cold_native_request_rejects_missing_parent_mode_before_consumption(self):
        self.request.update(action='desktop-mic', native_mic_cold_start=True,
                            playback=True, capture=True)
        self.write_request()
        with patch.object(trial, 'audio_check') as hardware:
            with self.assertRaisesRegex(AssertionError, 'native-mic-cold-start'):
                trial.requested_audio(self.args)
        hardware.assert_not_called()
        self.assertTrue((self.out / 'audio-request.json').exists())

    def test_cold_native_flag_recorded_forwarded_and_consumed(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        args = SimpleNamespace(audio_action='desktop-mic', native_mic_on_demand=True,
            native_mic_cold_start=True, allow_amp_power=True, allow_playback=True,
            allow_capture=True, desktop_user='dvitali', return_after_audio_seconds=None)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        self.assertTrue(json.loads((self.out / 'audio-request.json').read_text())['native_mic_cold_start'])
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=account), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertIn('--native-mic-cold-start', opened.call_args.args[0])
        with patch.object(trial, 'audio_check') as hardware:
            trial.requested_audio(SimpleNamespace())
        self.assertTrue(hardware.call_args.args[0].native_mic_cold_start)
        self.assertFalse((self.out / 'audio-request.json').exists())

    def test_cold_native_cli_rejects_wrong_action_command_and_parent_before_boot(self):
        for command, action, extra in (('audio', 'desktop-mic', []),
                ('audio', 'feedback', ['--native-mic-on-demand']),
                ('check', 'desktop-mic', ['--native-mic-on-demand']),
                ('arm-audio', 'desktop-mic', ['--native-mic-on-demand', '--capture-reopen'])):
            with self.subTest(command=command, action=action), \
                    patch.object(sys, 'argv', ['trial.py', command, '20261008ei',
                        '--audio-action', action, '--native-mic-cold-start'] + extra), \
                    patch.object(sys, 'stderr', io.StringIO()), \
                    patch.object(trial, 'require_source_boot') as boot:
                with self.assertRaises(SystemExit) as stopped:
                    trial.main()
                self.assertEqual(stopped.exception.code, 2)
                boot.assert_not_called()

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
        self.start_patch(patch.object(trial.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_name='dvitali')))
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

    def microphone_fixture(self):
        """Extend the existing policy unit fixture; never accesses live hardware."""
        self.ready['microphone'] = dict(source='spx_microphone', source_index=131,
            module='536870917', default_selected=True, bounded_clients_passed=True,
            recording=None, source_lifetime='serve-owner', all_automated_recordings_bounded=True)
        self.microphone_identity = dict(index='536870917', name='module-alsa-source',
            argument='device=hw:0,1 source_name=spx_microphone format=s16le rate=48000 '
                     'channels=1 channel_map=mono fragments=4 fragment_size=1920 mmap=no')
        self.live_source = dict(index=131, name='spx_microphone', owner_module='536870917',
            monitor_source='', sample_specification='s16le 1ch 48000Hz', channel_map='mono')
        self.live_modules = ('536870917\tmodule-alsa-source\t' +
                             self.microphone_identity['argument'] + '\t\n')
        self.microphone_result()
        command = self.proc / '2276/cmdline'
        command.write_text(command.read_text() + '--desktop-microphone\0')

        def metadata(command, **options):
            self.assertEqual(command[:8], ['runuser', '-u', 'dvitali', '--', 'env',
                'XDG_RUNTIME_DIR=/run/user/1000',
                'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus', 'pactl'])
            self.assertEqual(options, dict(capture_output=True, text=True, check=True, timeout=5))
            if command[8:] == ['--format=json', 'list', 'sources']:
                return SimpleNamespace(stdout=json.dumps([self.live_source]))
            self.assertEqual(command[8:], ['--format=text', 'list', 'short', 'modules'])
            return SimpleNamespace(stdout=self.live_modules)

        trial.subprocess.run.side_effect = metadata

    def microphone_result(self, completed=False):
        self.save('audio/serve-ready.json', self.ready)
        microphone = dict(self.ready['microphone'], microphone_client_passed=True,
                          module_identity=self.microphone_identity)
        if completed:
            microphone.update(restored=True, adapter_error=None, kernel_errors=[], cleanup_errors=[])
        self.save('audio/serve-result.json', dict(serve=self.ready, desktop_microphone=microphone,
                                                success=completed, cleanup_errors=[]))

    def test_prior_stop_archived_before_policy_starts_new_owner(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        self.microphone_result(completed=True)
        previous = dict(boot_id='new-boot', complete=True)
        self.save('audio-stop.json', previous)
        original = (self.out / 'audio-stop.json').read_bytes()
        self.next_boot()

        def started(args):
            self.assertFalse((self.out / 'audio-stop.json').exists())
            self.assertEqual((self.out / 'audio/boots/new-boot/audio-stop.json').read_bytes(), original)

        self.audio.side_effect = started
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()

    def test_current_boot_stop_is_preserved_for_idempotent_reuse(self):
        self.save('audio-stop.json', dict(boot_id='new-boot', complete=False))
        original = (self.out / 'audio-stop.json').read_bytes()
        trial.archive_audio_result('new-boot')
        self.assertEqual((self.out / 'audio-stop.json').read_bytes(), original)
        self.assertFalse((self.out / 'audio/boots/new-boot/audio-stop.json').exists())

    def test_conflicting_prior_stop_archive_preserves_both_records(self):
        self.save('audio-stop.json', dict(boot_id='old-boot', complete=False))
        self.save('audio/boots/old-boot/audio-stop.json', dict(boot_id='old-boot', complete=True))
        original = (self.out / 'audio-stop.json').read_bytes()
        archived = (self.out / 'audio/boots/old-boot/audio-stop.json').read_bytes()
        with self.assertRaisesRegex(AssertionError, 'Conflicting archived stop evidence'):
            trial.archive_audio_result('new-boot')
        self.assertEqual((self.out / 'audio-stop.json').read_bytes(), original)
        self.assertEqual((self.out / 'audio/boots/old-boot/audio-stop.json').read_bytes(), archived)

    def test_microphone_enable_requires_live_identity_and_persists_exact_boolean(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        policy = json.loads((self.out / 'desktop-audio.json').read_text())
        self.assertIs(policy['desktop_microphone'], True)
        self.assertEqual(policy['verified_boot_id'], 'new-boot')
        self.assertEqual(trial.subprocess.run.call_count, 2)
        trial.dispatch_audio(self.args)
        self.audio.assert_not_called()
        self.assertEqual(self.windows, [])

    def test_microphone_enable_rejects_unverified_or_malformed_readiness(self):
        self.microphone_fixture()
        original = dict(self.ready['microphone'])
        mutations = [None, {}, dict(original, source='other'), dict(original, source_index=True),
                     dict(original, module=536870917), dict(original, default_selected=False),
                     dict(original, bounded_clients_passed=1), dict(original, recording='active'),
                     dict(original, source_lifetime='bounded-test'),
                     dict(original, all_automated_recordings_bounded='yes')]
        for microphone in mutations:
            with self.subTest(microphone=microphone):
                self.ready['microphone'] = microphone
                self.save('audio/serve-ready.json', self.ready)
                with self.assertRaisesRegex(AssertionError, 'Unverified desktop microphone'):
                    trial.enable_desktop_audio(self.args)
                self.assertFalse((self.out / 'desktop-audio.json').exists())
        trial.subprocess.run.assert_not_called()

    def test_microphone_enable_rejects_owner_flag_disagreement_and_duplicate(self):
        self.microphone_fixture()
        command = self.proc / '2276/cmdline'
        original = command.read_text()
        for changed in (original.replace('--desktop-microphone\0', ''),
                        original + '--desktop-microphone\0'):
            with self.subTest(command=changed):
                command.write_text(changed)
                with self.assertRaises(AssertionError):
                    trial.enable_desktop_audio(self.args)
                self.assertFalse((self.out / 'desktop-audio.json').exists())
        command.write_text(original)
        self.ready.pop('microphone')
        self.save('audio/serve-ready.json', self.ready)
        with self.assertRaisesRegex(AssertionError, 'Unverified desktop microphone'):
            trial.enable_desktop_audio(self.args)
        trial.subprocess.run.assert_not_called()

    def test_microphone_enable_rejects_changed_live_source_or_module(self):
        self.microphone_fixture()
        original = dict(self.live_source)
        for changed in (dict(original, name='other'), dict(original, index=132),
                        dict(original, index=True), dict(original, owner_module='other'),
                        dict(original, monitor_source='1'),
                        dict(original, sample_specification='s16le 2ch 48000Hz'),
                        dict(original, channel_map='stereo')):
            with self.subTest(source=changed):
                self.live_source = changed
                with self.assertRaises(AssertionError):
                    trial.enable_desktop_audio(self.args)
                self.assertFalse((self.out / 'desktop-audio.json').exists())
        self.live_source = original
        modules = self.live_modules
        for changed in ('', modules + modules, modules.replace('mmap=no', 'mmap=yes'),
                        modules.replace('536870917', '536870918')):
            with self.subTest(modules=changed):
                self.live_modules = changed
                with self.assertRaisesRegex(AssertionError, 'module identity changed'):
                    trial.enable_desktop_audio(self.args)
                self.assertFalse((self.out / 'desktop-audio.json').exists())

    def test_microphone_policy_runs_each_boot_once_with_fresh_identity_and_archive(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        self.args.native_mic_app_formats = True
        self.microphone_result(completed=True)  # Orderly stop before the next boot.
        self.next_boot()
        trial.subprocess.run.reset_mock()

        def started(args):
            self.assertIs(args.desktop_microphone, True)
            self.assertIs(args.native_mic_app_formats, False)
            self.assertEqual((args.audio_action, args.serve_seconds), ('serve', 0))
            self.assertFalse((self.out / 'audio/serve-ready.json').exists())
            self.assertTrue((self.out / ('audio-started-boots/' +
                            (self.proc / 'boot_id').read_text() + '.json')).exists())
            self.ready['boot_id'] = (self.proc / 'boot_id').read_text()
            self.ready['microphone']['source_index'] += 1
            self.ready['microphone']['module'] = str(int(self.ready['microphone']['module']) + 1)
            self.microphone_identity['index'] = self.ready['microphone']['module']
            self.microphone_result(completed=True)

        self.audio.side_effect = started
        trial.dispatch_audio(self.args)
        trial.dispatch_audio(self.args)
        self.next_boot('third-boot')
        trial.dispatch_audio(self.args)
        trial.dispatch_audio(self.args)
        self.assertEqual(self.audio.call_count, 2)
        for boot in ('new-boot', 'next-boot'):
            for name in ('serve-ready.json', 'serve-result.json'):
                self.assertTrue((self.out / 'audio/boots' / boot / name).exists())
        self.assertEqual(self.windows, [])
        trial.subprocess.run.assert_not_called()

    def test_microphone_policy_quarantines_failed_missing_or_mismatched_previous_proof(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        self.microphone_result(completed=True)
        policy = json.loads((self.out / 'desktop-audio.json').read_text())
        result = json.loads((self.out / 'audio/serve-result.json').read_text())
        self.next_boot()
        mutations = [dict(result, success=False), dict(result, success=1),
                     dict(result, error='failed after publication'), dict(result, cleanup_errors=['failed']),
                     dict(result, serve=dict(self.ready, boot_id='unrelated')),
                     dict(result, serve=dict(self.ready, microphone=dict(self.ready['microphone'], module='other')))]
        for key, value in (('restored', False), ('adapter_error', 'failed'),
                           ('kernel_errors', ['fault']), ('cleanup_errors', ['failed']),
                           ('module', 'other'), ('source_index', 132), ('microphone_client_passed', False)):
            mutations.append(dict(result, desktop_microphone=dict(result['desktop_microphone'], **{key: value})))
        for changed in mutations + [[], 'malformed', None]:
            with self.subTest(result=changed):
                self.save('desktop-audio.json', policy)
                if changed is None:
                    (self.out / 'audio/serve-result.json').unlink()
                else:
                    self.save('audio/serve-result.json', changed)
                trial.dispatch_audio(self.args)
                self.assertFalse((self.out / 'desktop-audio.json').exists())
                self.assertTrue((self.out / 'desktop-audio-failed-new-boot.json').exists())
                self.assertFalse((self.out / 'audio-started-boots/next-boot.json').exists())
        self.audio.assert_not_called()

    def test_microphone_policy_quarantines_missing_previous_readiness(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        self.microphone_result(completed=True)
        (self.out / 'audio/serve-ready.json').unlink()
        self.next_boot()
        trial.dispatch_audio(self.args)
        self.assertFalse((self.out / 'desktop-audio.json').exists())
        self.audio.assert_not_called()

    def test_microphone_failure_after_new_readiness_quarantines_without_retry(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        self.microphone_result(completed=True)
        self.next_boot()

        def failed(args):
            self.ready['boot_id'] = 'next-boot'
            self.microphone_result()
            raise RuntimeError('failed after microphone publication')

        self.audio.side_effect = failed
        with self.assertRaisesRegex(RuntimeError, 'failed after microphone publication'):
            trial.dispatch_audio(self.args)
        self.assertTrue((self.out / 'desktop-audio-failed-next-boot.json').exists())
        trial.dispatch_audio(self.args)
        self.next_boot('third-boot')
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()
        self.assertEqual(self.windows, [])

    def test_microphone_policy_rejects_malformed_boolean_before_consumption(self):
        trial.enable_desktop_audio(self.args)
        policy = json.loads((self.out / 'desktop-audio.json').read_text())
        self.next_boot()
        for value in (None, 1, 'yes'):
            with self.subTest(value=value):
                self.save('desktop-audio.json', dict(policy, desktop_microphone=value))
                with self.assertRaisesRegex(AssertionError, 'desktop-microphone'):
                    trial.dispatch_audio(self.args)
                self.assertFalse((self.out / 'audio-started-boots/next-boot.json').exists())
        self.audio.assert_not_called()

    def test_old_speaker_policy_does_not_inherit_microphone_flag_from_args(self):
        trial.enable_desktop_audio(self.args)
        policy = json.loads((self.out / 'desktop-audio.json').read_text())
        policy.pop('desktop_microphone')
        self.save('desktop-audio.json', policy)
        self.args.desktop_microphone = True
        self.args.native_mic_app_formats = True
        self.next_boot()
        trial.dispatch_audio(self.args)
        self.assertIs(self.audio.call_args.args[0].desktop_microphone, False)
        self.assertIs(self.audio.call_args.args[0].native_mic_app_formats, False)

    def test_microphone_policy_queued_request_wins_and_restart_does_not_fall_through(self):
        self.microphone_fixture()
        trial.enable_desktop_audio(self.args)
        self.microphone_result(completed=True)
        self.next_boot()
        self.request.update(serve_seconds=0, desktop_microphone=False)
        self.write_request()
        # The shared fixture mocks journal capture after request completion.
        trial.subprocess.run.side_effect = None
        trial.dispatch_audio(self.args)
        trial.dispatch_audio(self.args)
        self.audio.assert_called_once()
        self.assertIs(self.audio.call_args.args[0].desktop_microphone, False)
        self.assertTrue((self.out / 'audio-started.json').exists())
        self.assertEqual(self.windows, [])

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


class DesktopMicrophoneRequestTests(TrialAudioFixture):
    def test_wrong_mode_and_malformed_flag_reject_before_arm_lock_or_request_consumption(self):
        for enabled in (True, 1, 'yes'):
            args = SimpleNamespace(audio_action='feedback', desktop_microphone=enabled)
            with self.subTest(enabled=enabled), patch.object(trial, 'require_source_boot') as boot:
                with self.assertRaisesRegex(AssertionError, 'desktop-microphone'):
                    trial.arm_audio(args)
                boot.assert_not_called()
                trial.subprocess.run.reset_mock()
                with self.assertRaisesRegex(AssertionError, 'desktop-microphone'):
                    trial.audio_check(args)
                trial.subprocess.run.assert_not_called()
                self.request.update(action='feedback', desktop_microphone=enabled)
                self.write_request()
                with self.assertRaisesRegex(AssertionError, 'desktop-microphone'):
                    trial.requested_audio(self.args)
                self.assertTrue((self.out / 'audio-request.json').exists())
                self.assertFalse((self.out / 'audio-started.json').exists())

    def test_flag_is_armed_consumed_and_forwarded_to_direct_helper(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        args = SimpleNamespace(audio_action='serve', desktop_microphone=True,
            allow_amp_power=True, allow_playback=True, allow_capture=True,
            desktop_user='dvitali', return_after_audio_seconds=None,
            serve_seconds=150, desktop_peak=1433)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        self.assertTrue(json.loads((self.out / 'audio-request.json').read_text())['desktop_microphone'])
        with patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial.pwd, 'getpwnam', return_value=account), \
                patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertIn('--desktop-microphone', opened.call_args.args[0])
        with patch.object(trial, 'audio_check') as hardware:
            trial.requested_audio(SimpleNamespace())
        self.assertTrue(hardware.call_args.args[0].desktop_microphone)
        self.assertFalse((self.out / 'audio-request.json').exists())

    def test_parser_rejects_flag_on_non_serve_command_before_dispatch(self):
        with patch.object(sys, 'argv', ['trial.py', 'arm-audio', '20261004bq',
                                      '--audio-action', 'feedback', '--desktop-microphone']), \
                patch.object(trial, 'arm_audio') as hardware, \
                patch.object(sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit):
                trial.main()
        hardware.assert_not_called()


class NativeMicrophoneAppFormatRequestTests(TrialAudioFixture):
    def test_invalid_flag_types_or_modes_reject_before_hardware_and_consumption(self):
        for action, microphone, enabled in [('feedback', True, True), ('serve', False, True),
                                            ('serve', 1, True), ('serve', True, 1), ('serve', True, 'yes')]:
            args = SimpleNamespace(audio_action=action, desktop_microphone=microphone,
                                   native_mic_app_formats=enabled)
            with self.subTest(case=(action, microphone, enabled)), \
                 patch.object(trial, 'require_source_boot') as boot:
                with self.assertRaisesRegex(AssertionError, 'native-mic-app-formats'):
                    trial.arm_audio(args)
                boot.assert_not_called()
                trial.subprocess.run.reset_mock()
                with self.assertRaisesRegex(AssertionError, 'native-mic-app-formats'):
                    trial.audio_check(args)
                trial.subprocess.run.assert_not_called()
                self.request.update(action=action, desktop_microphone=microphone,
                                    native_mic_app_formats=enabled)
                self.write_request()
                with self.assertRaisesRegex(AssertionError, 'native-mic-app-formats'):
                    trial.requested_audio(self.args)
                self.assertTrue((self.out / 'audio-request.json').exists())
                self.assertFalse((self.out / 'audio-started.json').exists())

    def test_parser_rejects_non_audio_or_missing_microphone_before_dispatch(self):
        for command, action, microphone in [('prepare', 'serve', True), ('audio', 'serve', False),
                                             ('arm-audio', 'feedback', False)]:
            argv = ['trial.py', command, '20261004bq', '--audio-action', action, '--native-mic-app-formats']
            if microphone:
                argv.append('--desktop-microphone')
            with self.subTest(command=command), patch.object(sys, 'argv', argv), \
                 patch.object(sys, 'stderr', io.StringIO()), patch.object(trial, 'arm_audio') as arm, \
                 patch.object(trial, 'audio_check') as check, patch.object(trial, 'prepare') as prepare:
                with self.assertRaises(SystemExit):
                    trial.main()
                arm.assert_not_called(); check.assert_not_called(); prepare.assert_not_called()

    def test_app_formats_flag_is_armed_consumed_once_and_forwarded_directly(self):
        (self.out / 'prepared.json').write_text(json.dumps(dict(audio_mode='parked')))
        args = SimpleNamespace(audio_action='serve', desktop_microphone=True, native_mic_app_formats=True,
            allow_amp_power=True, allow_playback=True, allow_capture=True, desktop_user='dvitali',
            return_after_audio_seconds=None, serve_seconds=30, desktop_peak=1433)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
             patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        record = json.loads((self.out / 'audio-request.json').read_text())
        self.assertIs(record['native_mic_app_formats'], True)
        with patch.object(trial.os, 'geteuid', return_value=0), \
             patch.object(trial.pwd, 'getpwnam', return_value=account), \
             patch.object(trial.subprocess, 'Popen') as opened:
            opened.return_value.wait.return_value = 0
            trial.audio_check(args)
        self.assertEqual(opened.call_args.args[0].count('--native-mic-app-formats'), 1)
        self.assertIn('--desktop-microphone', opened.call_args.args[0])
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(SimpleNamespace())
            trial.requested_audio(SimpleNamespace())
        check.assert_called_once()
        self.assertIs(check.call_args.args[0].native_mic_app_formats, True)

    def test_missing_legacy_flag_defaults_to_false_when_request_is_consumed(self):
        self.write_request()
        args = SimpleNamespace(native_mic_app_formats=True)
        with patch.object(trial, 'audio_check') as check:
            trial.requested_audio(args)
        self.assertIs(check.call_args.args[0].native_mic_app_formats, False)


if __name__ == '__main__':
    unittest.main()
