#!/usr/bin/env python3
"""Offline acoustic/control validation; never opens audio hardware."""
import io
import json
import math
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import audio
from acoustic import score_phase
import desktop_controls as controls
from test_trial_audio import TrialAudioFixture, trial


class AcousticControls(unittest.TestCase):
    rate = 4000

    @classmethod
    def signal(cls, amplitude, seconds=1.2):
        return [round(amplitude * (math.sin(2 * math.pi * 440 * n / cls.rate) +
                                   math.sin(2 * math.pi * 660 * n / cls.rate)))
                for n in range(round(cls.rate * seconds))]

    def setUp(self):
        self.quiet = [0] * round(self.rate * 1.2)
        self.original = score_phase(self.signal(32), self.quiet, [440, 660], self.rate)
        self.reduced = score_phase(self.signal(16), self.quiet, [440, 660], self.rate)
        self.digital = dict(frames=2 * self.rate, input_peak=0, output_peak=0)

    def check(self, reduced=None, restored=None, muted=None, digital=None):
        return controls.score_controls(self.original, reduced or self.reduced,
            restored or self.original, self.quiet if muted is None else muted,
            self.quiet, self.digital if digital is None else digital, self.rate)

    def test_reduction_mute_and_restoration_pass(self):
        result = self.check()
        self.assertTrue(result['passed'], result)
        self.assertAlmostEqual(result['targets']['440']['reduced_to_original_db'], -6, delta=.2)

    def test_unchanged_gain_fails(self):
        self.assertFalse(self.check(reduced=self.original)['passed'])

    def test_mute_cannot_pass_on_audible_or_brief_leakage(self):
        for leak in (self.signal(32), self.quiet[:1600] + self.signal(32, .1) + self.quiet[2000:]):
            with self.subTest(samples=len(leak)):
                self.assertFalse(self.check(muted=leak)['passed'])

    def test_failed_digital_mute_fails_despite_acoustic_silence(self):
        self.assertFalse(self.check(digital=dict(self.digital, input_peak=100))['passed'])
        self.assertFalse(self.check(digital=dict(self.digital, frames=100))['passed'])

    def test_restoration_failure_fails(self):
        self.assertFalse(self.check(restored=self.reduced)['passed'])

    def test_audible_failure_and_noise_floor_are_inconclusive(self):
        self.assertFalse(self.check(reduced={'passed': False})['passed'])
        weak = dict(self.original, targets={key: dict(value, rms=.8)
                    for key, value in self.original['targets'].items()})
        result = controls.score_controls(weak, weak, weak, self.quiet, self.quiet,
                                         self.digital, self.rate)
        self.assertFalse(result['passed'])
        self.assertTrue(any('noise-floor' in reason for reason in result['reasons']))


class NativeAndRoutingTests(unittest.TestCase):
    def test_native_owner_state_and_trigger_are_checked(self):
        valid = 'state: RUNNING\nowner_pid: 12\ntrigger_time: 10.002\n'
        identity = controls.native_identity(valid, 12, audio.need)
        self.assertEqual(identity['trigger_time'], '10.002')
        for invalid in (valid.replace('12', '13'), valid.replace('RUNNING', 'SETUP'),
                        valid.replace('trigger_time', 'missing')):
            with self.subTest(status=invalid), self.assertRaises(RuntimeError):
                controls.native_identity(invalid, 12, audio.need)
        self.assertNotEqual(identity, controls.native_identity(valid.replace('10.002', '10.003'),
                                                               12, audio.need))

    def test_default_client_uses_no_device_and_checks_actual_routing(self):
        for sink, expected_success in ((31, True), (22, False)):
            with self.subTest(sink=sink):
                graph = audio.DesktopGraph.__new__(audio.DesktopGraph)
                graph.sink = 'spx_speakers'
                graph.public_sink_id = 31
                graph.monitor = Mock()
                graph.processes = []
                graph.command = ['runuser', '-u', 'fixture', '--']
                graph.report = {'applications': []}
                graph.run = Mock(side_effect=['spx_speakers', json.dumps([dict(index=6, sink=sink,
                    properties={'application.name': 'spx-desktop-controls-muted'})])])
                process = Mock(pid=44, returncode=0)
                process.communicate.return_value = (None, b'')
                with patch.object(audio.subprocess, 'Popen', return_value=process) as opened:
                    if expected_success:
                        graph.play(b'finite fixture', 'controls-muted', default_sink=True)
                        self.assertEqual(graph.report['applications'][0]['routing']['sink_index'], 31)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'different sink'):
                            graph.play(b'finite fixture', 'controls-muted', default_sink=True)
                        process.communicate.assert_not_called()
                    self.assertFalse(any(arg.startswith('--device=') for arg in opened.call_args.args[0]))

    def test_control_readback_rejects_muted_or_missing_volume_monitor(self):
        sink = dict(name='spx_speakers', mute=False, volume={side: {'value': 52016}
                    for side in ('front-left', 'front-right')})
        node = dict(type='PipeWire:Interface:Node', info={'props': {
            'node.name': 'spx_speakers', 'monitor.channel-volumes': True}})
        for actual_muted, monitor_volume, passed in ((False, True, True), (True, True, False),
                                                    (False, False, False)):
            with self.subTest(muted=actual_muted, monitor=monitor_volume):
                sink['mute'] = actual_muted
                node['info']['props']['monitor.channel-volumes'] = monitor_volume
                graph = Mock()
                graph.run.side_effect = ['spx_speakers', json.dumps([sink]), json.dumps([node])]
                if passed:
                    self.assertFalse(controls.read_controls(graph, 52016, False, audio.need)['mute'])
                else:
                    with self.assertRaises(RuntimeError):
                        controls.read_controls(graph, 52016, False, audio.need)


class ControlsRequestTests(TrialAudioFixture):
    def test_opt_in_reaches_consumed_request_and_old_requests_default_false(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                (self.out / 'audio-started.json').unlink(missing_ok=True)
                if enabled:
                    self.request['desktop_controls'] = True
                else:
                    self.request.pop('desktop_controls', None)
                self.write_request()
                with patch.object(trial, 'claim_audio_boot', return_value=True), \
                        patch.object(trial, 'audio_check') as check:
                    trial.requested_audio(self.args)
                    self.assertIs(check.call_args.args[0].desktop_controls, enabled)

    def test_invalid_flag_type_and_action_rejected_before_consumption(self):
        for action, enabled in (('desktop', True), ('serve', 1), ('serve', 'false')):
            with self.subTest(action=action, enabled=enabled):
                self.request.update(action=action, desktop_controls=enabled)
                self.write_request()
                with patch.object(trial, 'claim_audio_boot') as claim:
                    with self.assertRaises(AssertionError):
                        trial.requested_audio(self.args)
                    claim.assert_not_called()
                self.assertTrue((self.out / 'audio-request.json').exists())

    def test_cli_rejects_wrong_actions_before_hardware(self):
        with patch.object(sys, 'argv', ['audio.py', 'desktop', '--desktop-controls']), \
                patch.object(sys, 'stderr', io.StringIO()), patch.object(audio, 'initialize') as init:
            with self.assertRaises(SystemExit) as stopped:
                audio.main()
            self.assertEqual(stopped.exception.code, 2)
            init.assert_not_called()
        for command, action in (('prepare', 'serve'), ('audio', 'feedback'), ('arm-audio', 'desktop')):
            with self.subTest(command=command), \
                    patch.object(sys, 'argv', ['trial.py', command, '20261007dq',
                        '--audio-action', action, '--desktop-controls']), \
                    patch.object(sys, 'stderr', io.StringIO()), patch.object(trial, 'audio_check') as check:
                with self.assertRaises(SystemExit) as stopped:
                    trial.main()
                self.assertEqual(stopped.exception.code, 2)
                check.assert_not_called()

    def test_arm_records_boolean_and_command_passes_only_when_enabled(self):
        (self.out / 'prepared.json').write_text('{"audio_mode":"parked"}')
        (self.out / 'installed.json').touch()
        args = SimpleNamespace(audio_action='serve', desktop_controls=True,
            desktop_user='dvitali', allow_amp_power=True, allow_playback=True,
            allow_capture=True, serve_seconds=60, desktop_peak=1433,
            return_after_audio_seconds=None)
        account = SimpleNamespace(pw_uid=1000, pw_name='dvitali')
        with patch.object(trial, 'require_source_boot'), patch.object(trial, 'recovery'), \
                patch.object(trial.pwd, 'getpwnam', return_value=account):
            trial.arm_audio(args)
        import json
        self.assertIs(json.loads((self.out / 'audio-request.json').read_text())['desktop_controls'], True)
        for enabled in (False, True):
            args.desktop_controls = enabled
            with patch.object(trial.os, 'geteuid', return_value=0), \
                    patch.object(trial.pwd, 'getpwnam', return_value=account), \
                    patch.object(trial.subprocess, 'Popen') as opened:
                opened.return_value.wait.return_value = 0
                trial.audio_check(args)
            command = opened.call_args.args[0]
            self.assertEqual('--desktop-controls' in command, enabled)
            self.assertEqual(opened.return_value.wait.call_args.kwargs['timeout'], 240 if enabled else 180)


if __name__ == '__main__':
    unittest.main()
