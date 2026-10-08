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
    return dict(preboot_id='old-boot', live_audio_resume=True, audio_mode='parked', slim_s2idle_retain=True,
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
             patch.object(trial, 'BOOT_ID', 'old-boot', create=True), \
             patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'read_text', autospec=True, side_effect=lambda path: 'boot-id\n' if str(path) == '/proc/sys/kernel/random/boot_id' else json.dumps(dict(complete=True, boot_id='boot-id', release='test-kernel'))), \
             patch.object(trial.subprocess, 'run') as run:
            trial.dispatch_live_audio_resume(args(), prepared())
        argv = run.call_args.args[0]
        self.assertIn('--unit=spx-systemd-suspend', argv); self.assertIn('--property=RuntimeMaxSec=200', argv)
        self.assertIn('--live-audio-resume', argv); self.assertIn('--allow-capture', argv)
        self.assertEqual(run.call_args.kwargs, dict(check=True, timeout=205))


class DefaultMicResume(unittest.TestCase):
    def witness(self):
        graph = Mock()
        capture = Mock(wall_deadline=200, started_boottime=80)
        report = dict(phases=[])
        witness = resume.DefaultMicrophone(graph, capture, report)
        witness.source = Mock(name='source')
        witness.source.name = 'owned-microphone'
        witness.source.source_id = 17
        witness.source.module = '41'
        witness.source.report = {'restored': True}
        witness.client = Mock()
        witness.client.process.pid = 123
        witness.client.process.poll.return_value = None
        return witness

    def test_optin_must_match_preparation_and_cli_requires_live_mode(self):
        import io, sys
        changed = args(); changed.default_mic_resume = True
        with self.assertRaisesRegex(AssertionError, 'differs from preparation'):
            resume.admission(prepared(), changed)
        record = prepared(); record['default_mic_resume'] = True
        resume.admission(record, changed)
        with patch.object(sys, 'argv', ['trial.py', 'systemd-suspend', '20261008dy', '--default-mic-resume']), \
             patch.object(sys, 'stderr', io.StringIO()), patch.object(trial, 'systemd_suspend') as hardware:
            with self.assertRaises(SystemExit) as error: trial.main()
        self.assertEqual(error.exception.code, 2)
        hardware.assert_not_called()

    def test_prepared_flag_forwarded_only_when_explicit(self):
        import json
        for enabled in (False, True):
            record = prepared(); record['default_mic_resume'] = enabled
            with patch.object(trial, 'OUT', Path('/private'), create=True), \
                 patch.object(trial, 'ATTEMPT', '20261008dy', create=True), \
                 patch.object(trial, 'RELEASE', 'test-kernel', create=True), \
                 patch.object(Path, 'exists', return_value=False), \
                 patch.object(Path, 'read_text', autospec=True, side_effect=lambda path: 'boot-id\n' if str(path) == '/proc/sys/kernel/random/boot_id' else json.dumps(dict(complete=True, boot_id='boot-id', release='test-kernel'))), \
                 patch.object(trial.subprocess, 'run') as run:
                trial.dispatch_live_audio_resume(args(), record)
            self.assertEqual('--default-mic-resume' in run.call_args.args[0], enabled)

    def test_extended_client_budget_requires_same_bounded_wall_fence(self):
        graph = Mock()
        for seconds, deadline in ((121, 200), (120, None), (120, 221), (120, 99)):
            with self.subTest(seconds=seconds, deadline=deadline), \
                 patch.object(audio.time, 'clock_gettime', return_value=100), \
                 patch.object(audio.subprocess, 'Popen') as child:
                with self.assertRaises(RuntimeError):
                    audio.DesktopRecording(graph, 'owned', maximum_seconds=seconds, wall_deadline=deadline)
                child.assert_not_called()

    def test_actual_client_frames_score_same_tones_and_reject_failed_proof(self):
        witness = self.witness()
        witness.client.mark.side_effect = [100, 100 + 96000, 100 + 96000, 100 + 240000]
        witness.client.samples.side_effect = ['actual-reference', 'actual-client-tone']
        witness.reference_begin(); witness.reference_end(); witness.tone_begin()
        with patch('acoustic.score_phase', return_value={'passed': False, 'reason': 'missing tone'}) as score:
            with self.assertRaisesRegex(AssertionError, 'client acoustic proof failed'): witness.tone_end()
        score.assert_called_once_with('actual-client-tone', 'actual-reference', [440, 660])
        self.assertFalse(witness.report['phases'][0]['score']['passed'])
        self.assertIsNone(witness.reference)

    def test_identity_requires_single_owned_route_and_retained_services(self):
        import json
        witness = self.witness()
        source = dict(index=17, name='owned-microphone', owner_module=41,
                      monitor_source='', sample_specification='s16le 1ch 48000Hz', channel_map='mono')
        output = dict(index=29, source=17, client=52, corked=False,
                      properties={'application.name': witness.name, 'application.process.id': '124'})
        replies = {
            'get-default-source': witness.source.name,
            'sources': json.dumps([source]),
            'modules': '41\tmodule-pipe-source\towned fifo\t\n',
            'source-outputs': json.dumps([output]),
            'services': '\n\n'.join('Id='+unit+'\nActiveState=active\nSubState=running\nMainPID='+str(pid)+'\nExecMainStartTimestampMonotonic=10' for pid, unit in enumerate(('pipewire.service', 'pipewire-pulse.service', 'wireplumber.service'), 200))}
        def command(*argv):
            return replies['services' if argv[0] == 'systemctl' else argv[-1]]
        witness.graph.run.side_effect = command
        with patch.object(resume, 'process_identity', side_effect=lambda pid: dict(pid=int(pid), start_ticks='10')):
            witness.report['held'] = witness.identity(); witness.retained()
            witness.graph.run.assert_any_call('pactl', '--format=text', 'list', 'short', 'modules')
            replies['source-outputs'] = json.dumps([output, output])
            with self.assertRaisesRegex(AssertionError, 'Unexpected'): witness.identity()
            replies['source-outputs'] = json.dumps([{**output, 'index': 30}])
            with self.assertRaisesRegex(AssertionError, 'identity changed'): witness.retained()
            replies['source-outputs'] = json.dumps([output])
            replies['services'] = replies['services'].replace('Monotonic=10', 'Monotonic=11')
            with self.assertRaisesRegex(AssertionError, 'identity changed'): witness.retained()
            replies['services'] = replies['services'].replace('Monotonic=11', 'Monotonic=10')
            replies['sources'] = json.dumps([{**source, 'sample_specification': 's16le 2ch 48000Hz'}])
            with self.assertRaisesRegex(AssertionError, 'source geometry changed'): witness.retained()
            replies['sources'] = json.dumps([{**source, 'monitor_source': 'existing.monitor'}])
            with self.assertRaisesRegex(AssertionError, 'sink monitor'): witness.identity()
            replies['sources'] = json.dumps([{**source, 'owner_module': 42}])
            with self.assertRaisesRegex(AssertionError, 'module changed'): witness.identity()

    def test_dz_noisy_module_response_admits_only_exact_owned_row(self):
        # Exact owned row and diagnostic shapes from virtual-module-schema.json.
        owned = ('536870917\tmodule-pipe-source\tfile=/run/user/1000/spx-mic-usra8luo/capture '
                 'source_name=spx_microphone_test_5082 format=s16le rate=48000 channels=1 channel_map=mono')
        columns = [1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 1, 2, 1, 3]
        diagnostics = ['nonnumeric prefix' + '\tdiagnostic' * (count - 1) for count in columns]
        # Unrelated numeric rows can also lose empty argument columns to strip.
        reply = '\n'.join([*diagnostics, '7\tunrelated', owned, '8']).strip()
        module = resume.owned_module(reply, '536870917')
        self.assertEqual(module, dict(index=536870917, name='module-pipe-source', argument=owned.split('\t')[2]))
        for rejected in ('\n'.join(diagnostics), reply.replace('536870917\t', '536870918\t'),
                         reply + '\n' + owned, '536870917\tmodule-pipe-source',
                         '536870917\tmodule-pipe-source\t', '536870917\tmodule-pipe-source\t   ',
                         reply.replace('module-pipe-source\tfile=', 'module-null-sink\tfile=')):
            with self.subTest(reply=rejected), self.assertRaises(AssertionError):
                resume.owned_module(rejected, '536870917')

    def test_exact_dz_silent_fixture_source_metadata_admission(self):
        # Copied from DZ virtual-source-schema.json, with only emitted fields.
        source = dict(index=79, name='spx_microphone_test_3760', owner_module=536870917,
                      sample_specification='s16le 1ch 48000Hz', channel_map='mono',
                      monitor_source='')
        row = ('536870917\tmodule-pipe-source\tfile=/run/user/1000/spx-mic-_rcf206j/capture '
               'source_name=spx_microphone_test_3760 format=s16le rate=48000 channels=1 channel_map=mono')
        report = {}
        self.assertEqual(resume.source_admission(source, report), source)
        module = resume.owned_module(row, str(source['owner_module']))
        self.assertEqual(module['index'], source['owner_module'])
        self.assertEqual(module['name'], 'module-pipe-source')
        self.assertEqual(report['source_admission'], source)
        for value in (None, 'n/a', 'existing.monitor', 4294967295, False):
            changed = {**source, 'monitor_source': value}
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, 'sink monitor'):
                resume.source_admission(changed, report)
            self.assertEqual(report['source_admission']['monitor_source'], value)
        changed = {key: value for key, value in source.items() if key != 'monitor_source'}
        with self.assertRaisesRegex(AssertionError, 'sentinel'): resume.source_admission(changed, report)
        self.assertNotIn('monitor_source', report['source_admission'])
        for key, value in (('sample_specification', 's16le 2ch 48000Hz'), ('channel_map', 'front-left')):
            with self.subTest(key=key), self.assertRaisesRegex(AssertionError, 'geometry'):
                resume.source_admission({**source, key: value}, report)

    def test_failed_start_closes_public_client_source_before_native_unwind(self):
        for cleanup_failed in (False, True):
            result = {}; events = []
            witness = Mock()
            witness.start.side_effect = RuntimeError('module admission failed')
            def close():
                events.append('public-client-source-close')
                if cleanup_failed: raise RuntimeError('source restore failed')
            witness.close.side_effect = close
            window = resume.ResumeWindow(Mock(), result, True)
            with patch.object(resume, 'DefaultMicrophone', return_value=witness):
                with self.assertRaisesRegex(RuntimeError, 'module admission failed'):
                    window.prepare(Mock(), Mock(), Mock())
            events.append('native-unwind')
            self.assertEqual(events, ['public-client-source-close', 'native-unwind'])
            self.assertEqual('default_microphone_start_cleanup_error' in result, cleanup_failed)

    def test_installed_pactl_schema_uses_real_text_module_index(self):
        import json
        # Installed libpulse b096704c0 emits no index in module JSON.
        actual_json = json.dumps([dict(name='module-pipe-source', argument='owned fifo',
                                      usage_counter='n/a', properties={})])
        self.assertNotIn('index', json.loads(actual_json)[0])
        actual_text = '2\tmodule-always-sink\t\t\n41\tmodule-pipe-source\towned fifo\t\n'
        self.assertEqual(resume.owned_module(actual_text, '41'),
                         dict(index=41, name='module-pipe-source', argument='owned fifo'))
        for response in ('41\tmodule-pipe-source\n',
                         'n/a\tmodule-pipe-source\towned fifo\t\n',
                         '42\tmodule-pipe-source\towned fifo\t\n',
                         '41\tmodule-null-sink\towned fifo\t\n',
                         actual_text + '41\tmodule-pipe-source\tduplicate\t\n'):
            with self.subTest(response=response), self.assertRaises(AssertionError):
                resume.owned_module(response, '41')

    def test_cleanup_closes_client_then_restores_source_even_if_client_fails(self):
        for failed in (False, True):
            witness = self.witness(); events = []
            def close_client():
                self.assertFalse(witness.source.forward)
                events.append('client')
                witness.client.process.poll.return_value = 0
                if failed: raise RuntimeError('client close error')
            witness.client.close.side_effect = close_client
            witness.source.close.side_effect = lambda: events.append('source-exact-preference-restore')
            if failed:
                with self.assertRaisesRegex(AssertionError, 'client close error'): witness.close()
            else:
                witness.close()
                self.assertTrue(witness.report['default_source_restored'])
            self.assertEqual(events, ['client', 'source-exact-preference-restore'])
            self.assertIsNone(witness.graph.microphone)
            witness.close()
            self.assertEqual(len(events), 2)

    def test_resume_window_cleans_before_native_close_and_requires_restoration(self):
        events = []; result = {}; window = resume.ResumeWindow(Mock(), result, True)
        witness = window.microphone = Mock(report={'client_closed': True, 'default_source_restored': False})
        def retained(*a, **kwargs):
            result['functional_pass'] = True; events.append('proof')
        witness.close.side_effect = lambda: events.append('public-client-source-close')
        with patch.object(resume, 'retained_window', side_effect=retained): window()
        events.append('native-capture-close')
        self.assertEqual(events, ['proof', 'public-client-source-close', 'native-capture-close'])
        self.assertFalse(result['functional_pass'])
        witness.report['default_source_restored'] = True
        with patch.object(resume, 'retained_window', side_effect=retained): window()
        self.assertTrue(result['functional_pass'])


class MicrophoneQuiesce(unittest.TestCase):
    def source(self):
        source = audio.DesktopMicSource(Mock(), Mock(), {})
        source.capture.wall_deadline = 200
        source.thread = Mock(); source.thread.is_alive.return_value = True
        source.capture.mark.return_value = 0
        return source

    def test_stalled_writer_acknowledges_pause_and_discards_paused_frames(self):
        import os, time
        from array import array
        source = self.source()
        reader, writer = os.pipe2(os.O_NONBLOCK)
        self.addCleanup(os.close, reader); self.addCleanup(os.close, writer)
        try:
            while True: os.write(writer, bytes(4096))
        except BlockingIOError: pass
        source.fd = writer
        source.capture.wall_deadline = time.clock_gettime(time.CLOCK_BOOTTIME) + 120
        clock = time.monotonic()
        source.capture.mark.side_effect = lambda: int((time.monotonic() - clock) * 48000)
        source.capture.samples.side_effect = lambda begin, end: array('h', [0] * (end - begin))
        source.forward = True
        source.thread = threading.Thread(target=source.feed)
        source.thread.start()
        try:
            time.sleep(.04)  # The real writer is blocked on the full pipe.
            pause = source.pause_forwarding(60)
            self.assertTrue(pause['quiesced']); self.assertTrue(source.paused.is_set())
            self.assertFalse(source.forward); self.assertIsNone(source.error)
            time.sleep(.06)
            resumed = source.resume_forwarding()
            self.assertTrue(resumed['discarded_paused_frames'])
            self.assertTrue(source.forward); self.assertIsNone(source.error)
        finally:
            source.stop.set(); source.thread.join(timeout=1)
        self.assertFalse(source.thread.is_alive())

    def test_expired_fifo_wait_does_not_signal_after_intentional_pause(self):
        from array import array
        source = self.source(); source.fd = 7; source.forward = True
        source.capture.mark.side_effect = [0, 480]
        source.capture.samples.return_value = array('h', [0] * 480)
        def blocked(*args):
            source.forward = False; source.stop.set()
            return [], [], []
        with patch.object(audio.select, 'select', side_effect=blocked), \
             patch.object(audio.os, 'kill') as kill:
            source.feed()
        self.assertIsNone(source.error); kill.assert_not_called()

    def test_quiesce_ack_dead_thread_and_timeout_fail(self):
        source = self.source()
        source.thread.is_alive.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'thread exited'):
            source.wait_forwarding(threading.Event(), 'no ack')
        source.thread.is_alive.return_value = True
        with patch.object(audio.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, 'no ack'):
                source.wait_forwarding(threading.Event(), 'no ack')
        source.capture.healthy.side_effect = RuntimeError('dead capture')
        with self.assertRaisesRegex(RuntimeError, 'dead capture'): source.pause_forwarding()

    def test_pause_window_cap_and_resume_requires_unexpired_quiescence(self):
        source = self.source(); source.capture.wall_deadline = 110
        source.wait_forwarding = Mock(side_effect=lambda event, message: event.set())
        with patch.object(audio.time, 'clock_gettime', return_value=100):
            for seconds in (0, 61):
                with self.assertRaisesRegex(RuntimeError, 'Invalid'): source.pause_forwarding(seconds)
            self.assertEqual(source.pause_forwarding(60)['deadline_boottime'], 110)
            with self.assertRaisesRegex(RuntimeError, 'overlapping'): source.pause_forwarding()
        with patch.object(audio.time, 'clock_gettime', return_value=111):
            with self.assertRaisesRegex(RuntimeError, 'expired'): source.resume_forwarding()
        self.assertFalse(source.forward)

    def test_original_sleep_failure_survives_microphone_cleanup_failure(self):
        result = {}; window = resume.ResumeWindow(Mock(), result, True)
        window.microphone = Mock(report={'cleanup_errors': ['adapter failed']})
        window.microphone.close.side_effect = AssertionError('adapter cleanup failed')
        with patch.object(resume, 'retained_window', side_effect=InterruptedError('original sleep signal')):
            with self.assertRaisesRegex(InterruptedError, 'original sleep signal'): window()
        self.assertEqual(result['default_microphone_window_cleanup_error'], 'adapter cleanup failed')
        self.assertFalse(result['functional_pass'])


class DeferredInfrastructure(unittest.TestCase):
    def test_default_client_post_runs_after_audio_teardown_with_original_baseline(self):
        for post_failed in (False, True):
            events = []; closed = False
            original = {'parked': 'original codecs and closed PCMs'}
            ops = Mock(); ops.output = Path('/private/audio-resume')
            lease = ops.audio = object()
            ops.gate.return_value = {'parked_audio': original, 'services': {'sensor': 8}}
            ops.cleanup.return_value = {'masks_restored': True}
            arguments = args(); arguments.default_mic_resume = True
            contract = Mock(report={'held': {'live': 'different owner observation'}})
            def verify(report, *args, microphone=None, **kwargs):
                events.append('post-client-and-native-proof')
                report['public_desktop'] = {'acoustic_passed': True}
                microphone.report['phases'].append({'score': {'passed': True}})
            def initialize(configured, report, *, live_resume):
                nonlocal closed
                report['public_desktop'] = {'acoustic_passed': True}
                live_resume.microphone = Mock(report=dict(phases=[{'score': {'passed': True}}],
                    client_closed=True, default_source_restored=True, same_owners=True))
                live_resume.result['default_microphone'] = live_resume.microphone.report
                live_resume(report, Mock(), Mock(), Mock(), {}, {})
                report.update(capture_deadline_expired=False, parked=True,
                    capture={'recording': None, 'closed_status': 'closed', 'ownership_wall_seconds': 90, 'log': ''},
                    pcm={'log': ''}, runtime_pm={'restored': True})
                closed = True; events.append('audio-closed-amps-parked-graph-restored')
            def post(before):
                self.assertTrue(closed); self.assertIs(ops.audio, lease)
                self.assertIs(before['parked_audio'], original)
                events.append('full-infrastructure-post')
                if post_failed: raise RuntimeError('post service/transfer gate failed')
                return {'services': {'sensor': 8}, 'download_bytes': 1000000}
            ops.post.side_effect = post
            with patch.object(Path, 'read_text', return_value='{}'), patch.object(resume, 'admission'), \
                 patch.object(audio, 'initialize', side_effect=initialize), patch.object(resume, 'quiet'), \
                 patch.object(resume, 'LiveOwnedAudio', return_value=contract), \
                 patch.object(audio, 'verify_public_playback', side_effect=verify), \
                 patch.object(resume.sleep, 'sleep_proven', return_value=True):
                result = resume.exercise(ops, arguments, 'owned')
            self.assertEqual(events, ['post-client-and-native-proof', 'audio-closed-amps-parked-graph-restored', 'full-infrastructure-post'])
            self.assertEqual(result['complete'], not post_failed)
            self.assertEqual(result.get('post_infrastructure_passed', False), not post_failed)
            self.assertIs(result['before']['parked_audio'], original)
            if post_failed: self.assertIn('post service/transfer gate failed', result['error'])

    def test_scoped_constructor_budget_defaults_bounds_and_recording(self):
        import tempfile
        from pathlib import Path
        import systemd_sleep
        for requested, parked, seconds in ((False, False, 100), (False, True, 100), (True, True, 140)):
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(Path, 'read_text', return_value='boot'), \
                 patch.object(systemd_sleep.signal, 'signal'), patch.object(systemd_sleep.signal, 'getsignal'), \
                 patch.object(systemd_sleep.signal, 'setitimer') as timer:
                live = systemd_sleep.Live(Path(directory) / 'fresh', 'attempt', 'release',
                    parked_audio=parked, default_mic_resume=requested)
                self.assertEqual(live.active_budget, seconds)
                self.assertEqual(live.budget['command_window_seconds'], seconds - 5)
                timer.assert_called_once_with(systemd_sleep.signal.ITIMER_REAL, seconds)
                record = {}; live.save(record)
                self.assertEqual(record['helper_budget'], live.budget)
        for requested, parked in ((True, False), (141, True)):
            with self.assertRaises(AssertionError):
                systemd_sleep.Live(Path('/unused'), 'attempt', 'release',
                    parked_audio=parked, default_mic_resume=requested)



class NativeMicResume(unittest.TestCase):
    def arguments(self):
        result = args(); result.native_mic_resume = True
        return result

    def test_typed_matching_exclusive_admission_and_parser(self):
        import io, sys
        record = prepared(); record['native_mic_resume'] = True
        resume.admission(record, self.arguments())
        for value in (False, 1, 'yes'):
            changed = dict(record, native_mic_resume=value)
            with self.subTest(value=value), self.assertRaises(AssertionError):
                resume.admission(changed, self.arguments())
        changed = self.arguments(); changed.default_mic_resume = True
        with self.assertRaises(AssertionError):
            resume.admission(dict(record, default_mic_resume=True), changed)
        for flags in (['--native-mic-resume'],
                      ['--live-audio-resume', '--native-mic-resume', '--default-mic-resume'],
                      ['--live-audio-resume', '--native-mic-resume', '--desktop-controls']):
            with patch.object(sys, 'argv', ['trial.py', 'systemd-suspend', '20261008el', *flags]), \
                 patch.object(sys, 'stderr', io.StringIO()), patch.object(trial, 'systemd_suspend') as hardware:
                with self.assertRaises(SystemExit) as error: trial.main()
            self.assertEqual(error.exception.code, 2); hardware.assert_not_called()

    def test_native_dispatch_budget_and_flag_without_changing_legacy(self):
        import json
        for enabled in (False, True):
            record = prepared(); record['native_mic_resume'] = enabled
            with patch.object(trial, 'OUT', Path('/private'), create=True), \
                 patch.object(trial, 'ATTEMPT', '20261008el', create=True), \
                 patch.object(trial, 'RELEASE', 'test-kernel', create=True), \
                 patch.object(Path, 'exists', return_value=False), \
                 patch.object(Path, 'read_text', autospec=True, side_effect=lambda path: 'boot-id' if str(path) == '/proc/sys/kernel/random/boot_id' else json.dumps(dict(complete=True, boot_id='boot-id', release='test-kernel'))), \
                 patch.object(trial.subprocess, 'run') as run:
                trial.dispatch_live_audio_resume(args(), record)
            argv = run.call_args.args[0]
            self.assertEqual('--native-mic-resume' in argv, enabled)
            self.assertIn('--property=RuntimeMaxSec=' + ('260' if enabled else '200'), argv)
            self.assertEqual(run.call_args.kwargs['timeout'], 265 if enabled else 205)

    def test_native_budget_scoped_and_typed(self):
        import tempfile, systemd_sleep
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'read_text', return_value='boot'), \
             patch.object(systemd_sleep.signal, 'signal'), patch.object(systemd_sleep.signal, 'getsignal'), \
             patch.object(systemd_sleep.signal, 'setitimer') as timer:
            live = systemd_sleep.Live(Path(directory)/'fresh', 'attempt', 'release',
                                     parked_audio=True, native_mic_resume=True)
        self.assertEqual(live.active_budget, 220)
        self.assertEqual(live.budget['command_window_seconds'], 215)
        self.assertIn('pre/post', live.budget['extension_scope'])
        timer.assert_called_once_with(systemd_sleep.signal.ITIMER_REAL, 220)
        for keywords in (dict(native_mic_resume=True),
                         dict(native_mic_resume=1, parked_audio=True),
                         dict(native_mic_resume=True, default_mic_resume=True, parked_audio=True)):
            with self.assertRaises(AssertionError): systemd_sleep.Live(Path('/unused'), 'a', 'r', **keywords)

    def test_renewal_rejects_active_owner_watcher_process_reader_or_raw(self):
        source = Mock(active_owner=None, thread=None, status=Path('/capture/status'))
        client = Mock(raw=bytearray(), log=Mock(closed=True)); client.process.poll.return_value = 0
        client.thread.is_alive.return_value = False
        graph = SimpleNamespace(recordings=[client])
        with patch.object(audio, 'read_text', return_value='closed'):
            resume.require_native_idle(source, graph)
            changes = [(source, 'active_owner', {}), (source, 'thread', Mock()),
                       (client.process, 'poll', Mock(return_value=None)),
                       (client.thread, 'is_alive', Mock(return_value=True)),
                       (client, 'raw', bytearray(b'private'))]
            for obj, name, value in changes:
                previous = getattr(obj, name); setattr(obj, name, value)
                with self.subTest(name=name), self.assertRaises(AssertionError):
                    resume.require_native_idle(source, graph)
                setattr(obj, name, previous)
        with patch.object(audio, 'read_text', return_value='RUNNING'), self.assertRaises(AssertionError):
            resume.require_native_idle(source, graph)

    def window_fixture(self):
        events = []; result = {'before': {'parked_audio': object()}}
        graph = Mock(recordings=[]); graph.default_source_before_test = None
        capture = Mock(card=0, status=Path('/capture/status')); capture.process.poll.return_value = 0
        report = {'recording_closed': True, 'public_desktop': {'acoustic_passed': True}, 'microphone_mixer': []}
        ops = Mock(); source = Mock(default_selected=True, active_owner=None, thread=None,
                                   status=capture.status, wall_deadline=0, report={'restored': True})
        source.close.side_effect = lambda: events.append('source-unload')
        graph.monitor.close.side_effect = lambda: events.append('monitor-close')
        def verify(source, graph, evidence, *args, frequencies=(440, 660), previous_trigger=None):
            self.assertEqual(frequencies, (440, 660))
            name = 'pre' if previous_trigger is None else 'post'; events.append(name)
            evidence.update(microphone_client_passed=True, clients=[
                dict(passed=True, pid=(10 if name == 'pre' else 20) + index,
                     native_owner={'trigger_time': name + str(index)}) for index in range(2)])
        def suspend():
            events.append('sleep'); self.assertEqual(events[:2], ['pre', 'sleep'])
            return {}
        ops.sleep.side_effect = suspend
        contract = Mock(report={'held': {}})
        contract.retained.side_effect = lambda before: events.append('identity')
        return events, result, graph, capture, report, ops, source, contract, verify

    def run_window(self, fixture):
        events, result, graph, capture, report, ops, source, contract, verify = fixture
        window = resume.NativeResumeWindow(ops, result)
        with patch.object(audio, 'NativeMicSource', return_value=source), \
             patch.object(audio, 'read_text', return_value='closed'), \
             patch.object(audio, 'verify_native_microphone_clients', side_effect=verify), \
             patch.object(resume, 'quiet'), patch.object(resume, 'require_native_idle'), \
             patch.object(resume, 'NativeIdleAudio', return_value=contract), \
             patch.object(resume.sleep, 'sleep_proven', return_value=True):
            window(report, Mock(), graph, capture, {}, {})
        return window

    def test_native_window_fresh_phases_idle_sleep_unload_before_monitor(self):
        fixture = self.window_fixture(); original = fixture[1]['before']['parked_audio']
        self.run_window(fixture)
        events, result, graph, _, _, ops, _, _, _ = fixture
        self.assertEqual(events, ['pre', 'sleep', 'identity', 'post', 'identity', 'source-unload', 'monitor-close'])
        self.assertIs(result['before']['parked_audio'], original); ops.post.assert_not_called()
        self.assertTrue(result['functional_pass'])
        self.assertIsNot(result['native_microphone']['pre']['clients'], result['native_microphone']['post']['clients'])
        for name in ('pre', 'post'):
            phase = result['native_microphone'][name]
            self.assertAlmostEqual(phase['wall_deadline_boottime'] - phase['started_boottime'], 60)
            self.assertIsNone(phase['recording'])
            self.assertEqual(phase['frequencies_hz'], [440, 660])
        self.assertIsNone(graph.microphone); self.assertIsNone(graph.monitor)

    def test_sleep_failure_preserved_monitor_ends_source_unloads(self):
        fixture = self.window_fixture()
        monitor = fixture[2].monitor
        monitor.end_suspend.side_effect = RuntimeError('monitor failure')
        fixture[5].sleep.side_effect = RuntimeError('original sleep failure')
        with self.assertRaisesRegex(RuntimeError, 'original sleep failure'): self.run_window(fixture)
        monitor.end_suspend.assert_called_once()
        self.assertEqual(fixture[1]['monitor_window_cleanup_error'], 'monitor failure')
        self.assertNotIn('post', fixture[0]); self.assertIn('source-unload', fixture[0])

    def test_identity_failure_stops_before_post_recording_and_closes_source(self):
        for identity in ('default', 'module', 'service', 'trigger', 'geometry', 'mixer'):
            fixture = self.window_fixture()
            fixture[7].retained.side_effect = RuntimeError(identity + ' changed')
            with self.subTest(identity=identity), self.assertRaisesRegex(RuntimeError, identity):
                self.run_window(fixture)
            self.assertNotIn('post', fixture[0]); self.assertIn('source-unload', fixture[0])
            self.assertFalse(fixture[1].get('functional_pass', False))

    def test_oracle_close_required_before_source_load(self):
        for closed in (False, True):
            fixture = self.window_fixture(); fixture[4]['recording_closed'] = closed
            fixture[3].process.poll.return_value = None
            with patch.object(audio, 'NativeMicSource') as load, self.assertRaisesRegex(AssertionError, 'Original oracle'):
                resume.NativeResumeWindow(fixture[5], fixture[1])(fixture[4], Mock(), fixture[2], fixture[3], {}, {})
            load.assert_not_called()

    def test_post_trigger_reuse_rejects_before_tones_and_discards_client(self):
        source = Mock(wall_deadline=60)
        source.begin_client.return_value = {'trigger_time': 'old-trigger'}
        client = Mock(); client.process.pid = 50
        pcm = Mock(); pcm.healthy.return_value = 'owner_pid: 10\ntrigger_time: playback\n'
        evidence = {'clients': []}
        with patch.object(audio.time, 'clock_gettime', return_value=0), \
             patch.object(audio, 'DesktopRecording', return_value=client), \
             self.assertRaisesRegex(RuntimeError, 'First post-sleep client'):
            audio.verify_native_microphone_clients(source, Mock(), evidence, pcm, {}, {},
                                                   previous_trigger='old-trigger')
        client.wait_frames.assert_not_called(); pcm.play.assert_not_called()
        source.end_client.assert_called_once(); client.close.assert_called_once()
        self.assertFalse(evidence['clients'][0]['passed'])

    def test_native_infrastructure_runs_only_after_all_audio_teardown(self):
        events = []; ops = Mock(output=Path('/private/audio-resume')); lease = ops.audio = object()
        original = object(); ops.gate.return_value = {'parked_audio': original}
        ops.cleanup.return_value = {'masks_restored': True}
        def initialize(configured, report, *, live_resume):
            self.assertTrue(configured.native_mic_resume)
            self.assertTrue(live_resume.after_recording)
            live_resume.result.update(functional_pass=True, native_microphone={'passed': True, 'source': {'restored': True}})
            report.update(capture_deadline_expired=False, capture={'recording': None, 'closed_status': 'closed',
                'ownership_wall_seconds': 30}, pcm={'log': ''}, parked=True, runtime_pm={'restored': True})
            ops.audio = object(); events.append('source-pcm-graph-mixer-teardown')
        def post(before):
            self.assertIs(ops.audio, lease); self.assertIs(before['parked_audio'], original)
            self.assertEqual(events, ['source-pcm-graph-mixer-teardown']); events.append('infrastructure')
            return {}
        ops.post.side_effect = post
        with patch.object(Path, 'read_text', return_value='{}'), patch.object(resume, 'admission'), \
             patch.object(audio, 'initialize', side_effect=initialize):
            result = resume.exercise(ops, self.arguments(), 'owner')
        self.assertTrue(result['complete']); self.assertEqual(events[-1], 'infrastructure')

    def test_listen_callback_closes_oracle_first_only_for_native_mode(self):
        for native in (False, True):
            events = []; pcm = Mock(feed_stats={}); pcm.process.pid = 10
            pcm.healthy.return_value = 'state: RUNNING'
            pcm.close.side_effect = lambda: events.append('playback-attached-close') or ''
            graph = Mock(); graph.monitor = Mock()
            report = {'stages': [{'physical_units_to_addresses': {}}], 'before': {'internal_cards': [0]}}
            configured = SimpleNamespace(action='serve', allow_playback=True, desktop_user='user',
                                         desktop_peak=1433, native_mic_resume=native)
            def oracle(): events.append('oracle-close-retain-mixer')
            def callback(*args): events.append('resume-window')
            callback.after_recording = native
            def verify(report, *args, **kwargs): events.append('public-oracle-proof')
            holders = []; graphs = []
            with patch.object(audio, 'devices', return_value=[{'unit': 3, 'name': 'left'}, {'unit': 4, 'name': 'right'}]), \
                 patch.object(Path, 'exists', return_value=True), patch.object(Path, 'write_text'), \
                 patch.object(audio, 'configure_stereo'), patch.object(audio, 'assert_pcm_idle'), \
                 patch.object(audio, 'OwnedPCM', return_value=pcm), \
                 patch.object(audio, 'read_text', return_value='format: S16_LE\nchannels: 2\nrate: 48000\n'), \
                 patch.object(audio, 'check_stereo', return_value={}), \
                 patch.object(audio, 'playback_state', side_effect=[{'LATE_INIT_COUNT': value} for value in (0, 1, 1, 0, 1, 1)]), \
                 patch.object(audio, 'DesktopGraph', return_value=graph), \
                 patch.object(audio, 'verify_public_playback', side_effect=verify), \
                 patch.object(audio, 'check_desktop_teardown') as teardown:
                audio.listen(configured, report, holders, Mock(), desktop_holder=graphs,
                             before_serve=oracle, live_resume=callback)
            self.assertEqual(events, ['public-oracle-proof', *(['oracle-close-retain-mixer', 'resume-window'] if native else
                                                            ['resume-window', 'oracle-close-retain-mixer']), 'playback-attached-close'])
            self.assertEqual(graph.preserve_default_source, native)
            teardown.assert_called_once(); self.assertEqual(holders, [])

    def test_idle_observer_rejects_source_metadata_default_or_mixer_change(self):
        owner = resume.NativeIdleAudio.__new__(resume.NativeIdleAudio); owner.report = {}
        before = dict(processes={}, native_owners={}, geometry={}, initialized_counts={},
                      native_source={'module': 'owned', 'default': 'ours', 'mixer': 'retained'})
        for field in before['native_source']:
            after = copy.deepcopy(before); after['native_source'][field] = 'changed'
            owner.check = lambda: after
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, 'native source'):
                owner.retained(before)


if __name__ == '__main__': unittest.main()
