#!/usr/bin/python3
"""Offline native discovery, sleep proof, identity and owned cleanup checks."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import bluetooth_resume as resume
from test_bluetooth_power import Fake as PowerFake, ADDRESS
from test_systemd_sleep import evidence


class Radio(PowerFake):
    def __init__(self, output, events, failure=None):
        super().__init__(output)
        self.events, self.failure = events, failure
        self.soft, self.hard = '0', '0'
        self.identity_value = dict(pid=17, process_start_ticks=123, service_start_monotonic_us=456)

    def identity(self):
        return copy.deepcopy(self.identity_value)

    def set_power(self, powered):
        raise AssertionError('resume test attempted power mutation')

    def original(self):
        assert self.hard == '0', 'fitted radio hardblocked'
        state = self.snapshot()
        state['rfkill'] = {'bluetooth:hci0': dict(name='hci0', type='bluetooth', soft=self.soft, hard=self.hard)}
        return state

    def prepare_fixture(self, original, authorized):
        assert authorized is True
        self.events.append('fixture-enable')
        self.writes.append(True)
        self.soft = '0'
        self.data[resume.power.ADAPTER][resume.power.INTERFACE].update(Powered=True, PowerState='on')
        if self.failure == 'fixture-enable': raise RuntimeError('fixture setup write uncertain')

    def restore_fixture(self, original):
        self.events.append('fixture-restore')
        self.writes.append(original['powered'])
        self.soft = original['rfkill']['bluetooth:hci0']['soft']
        self.data[resume.power.ADAPTER][resume.power.INTERFACE].update(Powered=original['powered'], PowerState=original['power_state'])
        if self.failure == 'fixture-restore': raise RuntimeError('fixture restoration failed')

    def scan(self):
        self.scans += 1
        self.events.append('scan' + str(self.scans))
        if self.failure in ('scanner', 'scanner-cleanup'):
            self.client = Mock()
            def close():
                self.events.append('scanner-close')
                if self.failure == 'scanner-cleanup':
                    raise RuntimeError('owned scanner could not reap')
            self.client.close.side_effect = close
            raise RuntimeError('scan failed')
        no_peer = self.failure == 'no-before' or (self.failure == 'no-after' and self.scans == 2)
        return dict(observation_seconds=5, discovery_start_confirmed=True,
                    discovery_stop_confirmed=True, fresh_peer_count=0 if no_peer else 2,
                    fresh_new_events=0, fresh_rssi_events=0 if no_peer else 3)


class Sleep:
    def __init__(self, output, failure=None):
        self.output, self.failure = Path(output), failure
        self.attempt, self.release, self.boot = '20261007test', 'test-kernel', 'test-boot'
        self.started, self.handlers, self.parked_audio = time.monotonic(), {}, True
        self.events, self.saved = [], None
        self.radio = Radio(output, self.events, failure)

    def action(self, name, result=None):
        self.events.append(name)
        if self.failure == name:
            raise RuntimeError(name + ' failed')
        return result

    def gate(self): return self.action('gate', {})
    def direct(self): return self.action('direct', dict(complete=True))
    def inhibit_idle(self): return self.action('idle')
    def open_shadows(self): return self.action('shadows')
    def save(self, result): self.saved = copy.deepcopy(result)

    def sleep(self):
        self.sleep_result = evidence()
        if self.failure == 'proof': self.sleep_result['service_completed'] = False
        if self.failure == 'pid': self.radio.identity_value['pid'] += 1
        if self.failure == 'start': self.radio.identity_value['process_start_ticks'] += 1
        if self.failure == 'policy': self.radio.data[resume.power.ADAPTER][resume.power.INTERFACE]['Pairable'] = False
        if self.failure == 'rfkill': self.radio.rfkill = lambda: {'changed': True}
        return self.action('sleep', self.sleep_result)

    def post(self, before): return self.action('post', {})

    def cleanup(self):
        result = dict(masks_restored=True, owned_files_removed=True, idle_inhibitor_reaped=True,
                      parked_audio=dict(restored=True))
        if self.failure == 'mask': result['masks_restored'] = False
        if self.failure == 'files': result['owned_files_removed'] = False
        if self.failure == 'inhibitor': result['idle_inhibitor_reaped'] = False
        if self.failure == 'parked': result['parked_audio']['restored'] = False
        return self.action('cleanup', result)


class Resume(unittest.TestCase):
    def run_case(self, failure=None):
        live = Sleep('/not-written', failure)
        with patch.object(resume.signal, 'setitimer'), patch.object(resume.power, 'exercise', side_effect=AssertionError('power exercise called')):
            result = resume.exercise(live, live.radio)
        self.assertEqual(live.saved, result)
        self.assertEqual(live.radio.writes, [])
        return live, result

    def test_fresh_discovery_surrounds_one_normal_sleep_without_power_writes(self):
        live, result = self.run_case()
        self.assertTrue(result['complete'])
        self.assertEqual(live.events, ['gate', 'direct', 'gate', 'scan1', 'idle', 'shadows', 'sleep', 'post', 'scan2', 'cleanup'])
        self.assertTrue(result['same_native_bluez_process'])
        self.assertFalse(result['pairing_reconnect_acceptance'])
        self.assertFalse(result['full_suspend_acceptance'])
        text = json.dumps(result)
        for private in (ADDRESS, 'PRIVATE-ALIAS', 'PRIVATE-NETWORK-UUID'):
            self.assertNotIn(private, text)

    def test_both_phases_need_fresh_reports(self):
        for phase in ('no-before', 'no-after'):
            with self.subTest(phase=phase):
                live, result = self.run_case(phase)
                self.assertFalse(result['complete'])
                self.assertTrue(result['fixture_inconclusive'])
                self.assertEqual(live.events[-1], 'cleanup')
                if phase == 'no-before': self.assertNotIn('sleep', live.events)
                else: self.assertTrue(result['sleep']['service_completed'])
        self.assertFalse(resume.scan_proven(dict(observation_seconds=5, fresh_peer_count=1,
                                                discovery_start_confirmed=True, discovery_stop_confirmed=True)))

    def test_changed_policy_rfkill_or_bluez_identity_cannot_pass(self):
        for failure in ('pid', 'start', 'policy', 'rfkill'):
            with self.subTest(failure=failure):
                live, result = self.run_case(failure)
                self.assertFalse(result['complete'])
                self.assertEqual(live.radio.scans, 1)
                self.assertEqual(live.events[-1], 'cleanup')

    def test_failed_scanner_is_reaped_before_sleep_cleanup_even_if_reap_fails(self):
        for failure in ('scanner', 'scanner-cleanup'):
            with self.subTest(failure=failure):
                live, result = self.run_case(failure)
                self.assertFalse(result['complete'])
                self.assertEqual(live.events[-2:], ['scanner-close', 'cleanup'])
                self.assertNotIn('sleep', live.events)
                if failure == 'scanner-cleanup': self.assertIn('scanner_cleanup_error', result)
                else: self.assertIsNone(live.radio.client)

    def test_sleep_failures_retain_proof_and_cleanup(self):
        for failure in ('gate', 'direct', 'idle', 'shadows', 'sleep', 'proof', 'post'):
            with self.subTest(failure=failure):
                live, result = self.run_case(failure)
                self.assertFalse(result['complete'])
                self.assertEqual(live.events[-1], 'cleanup')
                if failure in ('sleep', 'proof', 'post'):
                    self.assertIn('sleep', result)

    def test_all_cleanup_results_are_required(self):
        for failure in ('mask', 'files', 'inhibitor', 'parked', 'cleanup'):
            with self.subTest(failure=failure):
                live, result = self.run_case(failure)
                self.assertFalse(result['complete'])
                self.assertTrue(result['functional_pass'])

    def test_loaded_parked_audio_contract_required_before_mutation(self):
        live = Sleep('/not-written')
        live.parked_audio = False
        with patch.object(resume.signal, 'setitimer'):
            result = resume.exercise(live, live.radio)
        self.assertFalse(result['complete'])
        self.assertEqual(live.events, ['cleanup'])

    def test_off_fixture_requires_authorization_and_restores_after_owned_interval(self):
        for failure in (None, 'fixture-enable', 'no-before', 'no-after', 'sleep', 'scanner', 'fixture-restore'):
            with self.subTest(failure=failure):
                live = Sleep('/not-written', failure)
                live.radio.soft = '1'
                live.radio.data[resume.power.ADAPTER][resume.power.INTERFACE].update(Powered=False, PowerState='off-blocked')
                with patch.object(resume.signal, 'setitimer'):
                    result = resume.exercise(live, live.radio, allow_radio_on=True)
                self.assertEqual(live.radio.writes, [True, False])
                self.assertEqual(live.radio.soft, '1')
                self.assertFalse(live.radio.data[resume.power.ADAPTER][resume.power.INTERFACE]['Powered'])
                self.assertEqual(live.events[-2:], ['fixture-restore', 'cleanup'])
                self.assertEqual(result['complete'], failure is None)
                self.assertFalse(result['resume_radio_power_written'])
                if failure is None:
                    begin, end = live.events.index('scan1'), live.events.index('scan2')
                    self.assertFalse(any('fixture' in e for e in live.events[begin:end + 1]))
                    self.assertTrue(result['radio_fixture']['restored'])

    def test_off_default_and_hardblocked_fixtures_are_refused_without_writes(self):
        for hard in ('0', '1'):
            with self.subTest(hard=hard):
                live = Sleep('/not-written')
                live.radio.soft, live.radio.hard = '1', hard
                live.radio.data[resume.power.ADAPTER][resume.power.INTERFACE].update(Powered=False, PowerState='off-blocked')
                with patch.object(resume.signal, 'setitimer'):
                    result = resume.exercise(live, live.radio, allow_radio_on=hard == '1')
                self.assertFalse(result['complete'])
                self.assertEqual(live.radio.writes, [])
                self.assertNotIn('sleep', live.events)

    def test_observer_refuses_property_writes_before_external_command(self):
        radio = resume.Radio.__new__(resume.Radio)
        with patch.object(resume.power.Live, 'command') as command:
            with self.assertRaisesRegex(AssertionError, 'mutation'):
                radio.set_power(False)
            command.assert_not_called()

    def test_fixture_prepare_bounds_property_writes_and_preserves_unrelated_rfkill(self):
        radio = resume.Radio.__new__(resume.Radio)
        original = dict(address=ADDRESS, policy={}, network='private', powered=False,
                        power_state='off-blocked', rfkill={'bluetooth:hci0': dict(soft='1'), 'wlan': dict(soft='0')})
        current = copy.deepcopy(original)
        current.update(powered=True, power_state='on')
        current['rfkill']['bluetooth:hci0']['soft'] = '0'
        calls = []
        radio.write_soft = lambda value: calls.append(('rfkill', value, radio.fixture_window))
        radio.set_power = lambda value: calls.append(('power', value, radio.fixture_window))
        radio.settle = lambda value: calls.append(('settle', value, radio.fixture_window))
        radio.original = lambda: current
        radio.fixture_needs_power_request = lambda unblocked: True
        with self.assertRaises(AssertionError): radio.prepare_fixture(original, False)
        self.assertEqual(calls, [])
        radio.prepare_fixture(original, True)
        self.assertEqual(calls, [('rfkill', '0', True), ('power', True, True), ('settle', True, True)])
        self.assertFalse(radio.fixture_window)
        current['rfkill']['wlan']['soft'] = '1'
        with self.assertRaisesRegex(AssertionError, 'unrelated rfkill'):
            radio.prepare_fixture(original, True)
        self.assertFalse(radio.fixture_window)

    def test_rfkill_auto_start_is_observed_without_redundant_power_request(self):
        radio = resume.Radio.__new__(resume.Radio)
        original = dict(address=ADDRESS, policy={}, network='private', powered=False,
                        power_state='off-blocked', rfkill={'bluetooth:hci0': dict(soft='1')})
        current = copy.deepcopy(original)
        current.update(powered=True, power_state='on')
        current['rfkill']['bluetooth:hci0']['soft'] = '0'
        radio.write_soft = Mock()
        radio.set_power = Mock(side_effect=AssertionError('redundant Powered=true request'))
        radio.settle = Mock(side_effect=AssertionError('unnecessary settle'))
        radio.original = lambda: current
        observations = [dict(Powered=False, PowerState='off-enabling'),
                        dict(Powered=False, PowerState='off-enabling'),
                        dict(Powered=True, PowerState='on')]
        radio.objects = lambda: observations.pop(0)
        with patch.object(resume.power, 'idle', side_effect=lambda adapter: adapter), patch.object(resume.time, 'sleep'):
            radio.prepare_fixture(original, True)
        radio.write_soft.assert_called_once_with('0')
        radio.set_power.assert_not_called()
        self.assertFalse(radio.fixture_window)

    def test_fixture_stable_off_gets_one_request_and_transition_timeout_gets_none(self):
        radio = resume.Radio.__new__(resume.Radio)
        radio.objects = lambda: dict(Powered=False, PowerState='off')
        with patch.object(resume.power, 'idle', side_effect=lambda adapter: adapter), patch.object(resume.time, 'sleep'), patch.object(resume.time, 'monotonic', side_effect=[0, 0, 0, 0, .5, .5, 1.1, 1.1]):
            self.assertTrue(radio.fixture_needs_power_request(True))
        radio.objects = lambda: dict(Powered=False, PowerState='off-enabling')
        with patch.object(resume.power, 'idle', side_effect=lambda adapter: adapter), patch.object(resume.time, 'sleep'), patch.object(resume.time, 'monotonic', side_effect=[0, 0, 6]):
            with self.assertRaisesRegex(RuntimeError, 'did not settle'):
                radio.fixture_needs_power_request(True)

    def test_command_failures_preserve_only_safe_stage_and_exit_status(self):
        radio = resume.Radio.__new__(resume.Radio)
        radio.deadline, radio.fixture_window = None, True
        argv = ['busctl', 'set-property', 'org.bluez', resume.power.ADAPTER, resume.power.INTERFACE, 'Powered', 'b', 'true']
        private = 'PRIVATE-ADDRESS-OR-REPLY'
        with patch.object(resume.subprocess, 'run', return_value=Mock(returncode=1, stdout=private, stderr=private)):
            with self.assertRaises(resume.CommandFailure) as caught:
                radio.command(argv)
        self.assertEqual(caught.exception.status, dict(stage='fixture power request', returncode=1, timed_out=False))
        self.assertNotIn(private, str(caught.exception))
        with patch.object(resume.subprocess, 'run', side_effect=subprocess.TimeoutExpired(argv, 3, output=private)):
            with self.assertRaises(resume.CommandFailure) as caught:
                radio.command(argv)
        self.assertTrue(caught.exception.status['timed_out'])
        self.assertNotIn(private, str(caught.exception))

    def test_uncertain_fixture_enable_restores_already_blocked_original_without_waiting_for_off(self):
        radio = resume.Radio.__new__(resume.Radio)
        original = dict(powered=False, power_state='off-blocked')
        original['rfkill'] = {'bluetooth:hci0': dict(soft='1')}
        radio.objects = lambda: {resume.power.ADAPTER: {resume.power.INTERFACE: dict(Powered=False)}}
        radio.set_power = Mock(side_effect=AssertionError('unnecessary power write'))
        radio.settle = Mock(side_effect=AssertionError('off-blocked must not wait for off'))
        radio.write_soft = Mock()
        radio.original = lambda: original
        with patch.object(resume.power, 'idle', return_value=dict(Powered=False)):
            radio.restore_fixture(original)
        radio.set_power.assert_not_called()
        radio.settle.assert_not_called()
        radio.write_soft.assert_called_once_with('1')
        self.assertFalse(radio.fixture_window)

    def test_service_pid_reuse_detected_by_process_start_time(self):
        radio = resume.Radio.__new__(resume.Radio)
        radio.command = lambda argv: 'ActiveState=active\nSubState=running\nMainPID=17\nExecMainStartTimestampMonotonic=456'
        #19 fields before field22, after comm's closing ')'.
        stat = '17 (bluez name) ' + ' '.join(['S'] + ['0'] * 18 + ['123'] + ['0'] * 5)
        with patch.object(resume.Path, 'read_text', return_value=stat):
            self.assertEqual(radio.identity()['process_start_ticks'], 123)

    def test_cli_refuses_incompatible_modes_before_execution(self):
        trial = Path(__file__).with_name('trial.py')
        for command, extra in [('prepare', []), ('systemd-suspend', ['--live-audio-resume']),
                               ('systemd-suspend', ['--verify-sleep-return'])]:
            with self.subTest(command=command, extra=extra):
                proc = subprocess.run([sys.executable, '-B', str(trial), command, '20261007test',
                                       '--bluetooth-resume', *extra], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 2)
                self.assertIn('--bluetooth-resume requires', proc.stderr)


if __name__ == '__main__':
    unittest.main()
