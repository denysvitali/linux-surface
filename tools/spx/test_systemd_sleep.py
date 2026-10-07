#!/usr/bin/env python3
"""Offline sequencing, normal-service evidence and owned cleanup tests."""
import os
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import systemd_sleep as sleep


def evidence():
    return dict(boot_unchanged=True, sleep_seconds=29.5, kernel_entered=True, kernel_exited=True,
                service_completed=True, irq_before=2, irq_after=3, event=0xa0, alarm_disabled=True, user_thawed=True)


class Fake:
    def __init__(self, fail=None):
        self.events, self.fail = [], fail
    def action(self, name, value=None):
        self.events.append(name)
        if name == self.fail:
            raise RuntimeError(name + ' refused')
        return value
    def gate(self): return self.action('gate', {})
    def save(self, r): pass
    def direct(self): return self.action('direct', {})
    def inhibit_idle(self): return self.action('idle')
    def open_shadows(self): return self.action('shadows')
    def sleep(self): return self.action('sleep', evidence())
    def post(self, before): return self.action('post', {})
    def cleanup(self): return self.action('cleanup', dict(masks_restored=True))


class Effects(unittest.TestCase):
    def test_success_order_includes_second_gate_and_cleanup(self):
        f = Fake()
        r = sleep.exercise(f)
        self.assertTrue(r['complete'])
        self.assertEqual(f.events, ['gate', 'direct', 'gate', 'idle', 'shadows', 'sleep', 'post', 'cleanup'])
        self.assertFalse(r['full_suspend_acceptance'])
        self.assertFalse(r['audio_tested'])

    def test_each_failure_restores_and_stops_later_effects(self):
        for name in ('gate', 'direct', 'idle', 'shadows', 'sleep', 'post'):
            with self.subTest(name=name):
                f = Fake(name)
                r = sleep.exercise(f)
                self.assertFalse(r['complete'])
                self.assertEqual(f.events[-1], 'cleanup')
                if name in ('gate', 'direct', 'idle', 'shadows'):
                    self.assertNotIn('sleep', f.events)

    def test_cleanup_failure_prevents_acceptance(self):
        r = sleep.exercise(Fake('cleanup'))
        self.assertFalse(r['complete'])
        self.assertIn('cleanup_error', r)

    def test_sleep_command_success_alone_cannot_pass(self):
        for key, value in [('boot_unchanged', False), ('sleep_seconds', 0), ('sleep_seconds', 60),
                           ('kernel_entered', False), ('kernel_exited', False), ('service_completed', False),
                           ('irq_after', 2), ('event', 0x80), ('event', 0x20), ('alarm_disabled', False), ('user_thawed', False)]:
            r = evidence()
            r[key] = value
            self.assertFalse(sleep.sleep_proven(r), key)

    def test_collected_service_requires_fresh_successful_journal(self):
        before = dict(ExecMainExitTimestampMonotonic='0')
        after = dict(ActiveState='inactive', SubState='dead', Result='success', ExecMainStatus='0', ExecMainExitTimestampMonotonic='0')
        self.assertFalse(sleep.service_completed(before, after))
        self.assertTrue(sleep.service_completed(before, after, fresh_journal=True))

    def test_journal_requires_one_invocation_and_successful_finished_job(self):
        messages = ["Successfully froze unit 'user.slice'.", "Performing sleep operation 'suspend'...",
                    "System returned from sleep operation 'suspend'.", "Successfully thawed unit 'user.slice'."]
        records = [dict(UNIT='systemd-suspend.service', MESSAGE_ID='7d4958e842da4a758f6c1cdc7b36dcc5', JOB_TYPE='start', __MONOTONIC_TIMESTAMP='1')]
        records += [dict(MESSAGE=m, _SYSTEMD_UNIT='systemd-suspend.service', _SYSTEMD_INVOCATION_ID='one', __MONOTONIC_TIMESTAMP=str(i+2)) for i, m in enumerate(messages)]
        records += [dict(UNIT='systemd-suspend.service', MESSAGE_ID='39f53479d3a045ac8e11786248231fbf', JOB_TYPE='start', JOB_RESULT='done', __MONOTONIC_TIMESTAMP='6')]
        self.assertTrue(sleep.journal_completed(records))
        records[-1]['JOB_RESULT'] = 'failed'
        self.assertFalse(sleep.journal_completed(records))
        records[-1]['JOB_RESULT'] = 'done'
        records[3]['_SYSTEMD_INVOCATION_ID'] = 'another'
        self.assertFalse(sleep.journal_completed(records))

    def test_previous_completion_and_active_job_do_not_pass(self):
        before = dict(ExecMainExitTimestampMonotonic='100')
        after = dict(ActiveState='inactive', SubState='dead', Result='success', ExecMainStatus='0', ExecMainExitTimestampMonotonic='101')
        self.assertTrue(sleep.service_completed(before, after))
        after['ExecMainExitTimestampMonotonic'] = '100'
        self.assertFalse(sleep.service_completed(before, after))
        after.update(ExecMainExitTimestampMonotonic='101', ActiveState='activating')
        self.assertFalse(sleep.service_completed(before, after))


class Recovery(unittest.TestCase):
    def test_empty_assertion_retains_exception_and_location(self):
        f = Fake()
        f.gate = lambda: (_ for _ in ()).throw(AssertionError())
        r = sleep.exercise(f)
        self.assertFalse(r['complete'])
        self.assertIn('AssertionError', r['error'])
        self.assertIn('Traceback', r['traceback'])
        self.assertEqual(f.events, ['cleanup'])

    def test_reconnect_wait_returns_only_after_carrier_proof(self):
        live = sleep.Live.__new__(sleep.Live)
        values = iter([AssertionError('wlan0 carrier absent'), 'connected'])
        def network():
            value = next(values)
            if isinstance(value, Exception):
                raise value
            return value
        live.network = network
        with patch.object(sleep.time, 'sleep'):
            self.assertEqual(live.connected_network(), 'connected')


class Gates(unittest.TestCase):
    def test_root_release_and_attempt_mismatch_precede_any_effect(self):
        live = sleep.Live.__new__(sleep.Live)
        live.attempt, live.release = '20261007do', 'expected'
        live.run = lambda *args: self.fail('external command before identity gate')
        with patch.object(sleep.os, 'geteuid', return_value=1000):
            with self.assertRaises(AssertionError): live.gate()
        with patch.object(sleep.os, 'geteuid', return_value=0), patch.object(sleep.os, 'uname') as uname:
            uname.return_value.release = 'wrong'
            with self.assertRaises(AssertionError): live.gate()
            uname.return_value.release = 'expected'
            with patch.object(sleep.Path, 'read_text', return_value='spx_attempt=20261007other spx_boot=mainline-functional'):
                with self.assertRaises(AssertionError): live.gate()

    def test_user_slice_is_rejected_before_external_commands(self):
        live = sleep.Live.__new__(sleep.Live)
        live.attempt, live.release = '20261007do', 'expected'
        live.run = lambda *args: self.fail('external command before cgroup gate')
        words = 'spx_attempt=20261007do spx_boot=mainline-functional spx_sensors=1 module_blacklist=' + ','.join(sleep.AUDIO)
        with patch.object(sleep.os, 'geteuid', return_value=0), patch.object(sleep.os, 'uname') as uname:
            uname.return_value.release = 'expected'
            with patch.object(sleep.Path, 'read_text', side_effect=[words, '0::/user.slice/user-1000.slice/session.scope']), patch.object(sleep.Path, 'exists', return_value=False):
                with self.assertRaises(AssertionError): live.gate()


class ParkedAudio(unittest.TestCase):
    def test_mode_requires_all_explicit_preparation_and_default_stays_blocked(self):
        # This is the actual trial.prepare schema; there is no "audio" boolean.
        prepared = dict(audio_mode='parked', slim_s2idle_retain=True, pmic_rtc=True)
        words = ['spx_audio=parked', 'slim_qcom_ngd_ctrl.spx_s2idle_retain=1']
        sleep.audio_mode_gate(True, prepared, words, sleep.AUDIO, 'Y')
        for key, value in [('audio_mode', 'blocked'),
                           ('slim_s2idle_retain', 1), ('pmic_rtc', False)]:
            with self.subTest(key=key), self.assertRaises(AssertionError):
                sleep.audio_mode_gate(True, dict(prepared, **{key: value}), words, sleep.AUDIO, 'Y')
        for bad_words, loaded, retain in [(words[:1], sleep.AUDIO, 'Y'),
                                          (words, sleep.AUDIO - {'wcd934x'}, 'Y'),
                                          (words, sleep.AUDIO, 'N')]:
            with self.assertRaises(AssertionError):
                sleep.audio_mode_gate(True, prepared, bad_words, loaded, retain)
        blocked = ['module_blacklist=' + ','.join(sleep.AUDIO)]
        sleep.audio_mode_gate(False, dict(audio_mode='blocked'), blocked, set(), None)
        with self.assertRaises(AssertionError):
            sleep.audio_mode_gate(False, prepared, words, sleep.AUDIO, 'Y')
        f = Fake('sleep')
        f.parked_audio = True
        self.assertEqual(sleep.exercise(f)['audio_mode'], 'parked-retention')
        self.assertEqual(f.events[-1], 'cleanup')

    def test_fresh_retention_requires_ordered_callbacks_and_no_firmware_fault(self):
        log = sleep.RETAIN_ENTRY + '\n' + sleep.RETAIN_EXIT
        self.assertTrue(sleep.retention_proven(log)['complete'])
        for bad in ['', sleep.RETAIN_ENTRY, sleep.RETAIN_EXIT + '\n' + sleep.RETAIN_ENTRY,
                    log + '\nfatal error received', log + '\ns2idle retention lost controller invariants']:
            with self.subTest(log=bad), self.assertRaises(AssertionError):
                sleep.retention_proven(bad)

    def test_historical_or_audio_off_direct_result_cannot_replace_loaded_prerequisite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            output = root / 'pmic-rtc-suspend'
            output.mkdir()
            live = sleep.Live.__new__(sleep.Live)
            live.output, live.boot, live.release, live.parked_audio = root / 'systemd-suspend', 'boot', 'release', True
            import json
            for boot in ('old-boot', 'boot'):
                (output / 'result.json').write_text(json.dumps(dict(complete=True, boot_id=boot,
                    release='release', requested_seconds=15, sleep_seconds=14.5)))
                with self.subTest(boot=boot), patch.object(sleep.pmic_rtc, 'exercise') as exercise:
                    with self.assertRaises(AssertionError): live.direct()
                    exercise.assert_not_called()

    def test_independent_recovery_cannot_change_original_audio_mode(self):
        with tempfile.TemporaryDirectory() as d:
            for parked in (False, True):
                f = Fake()
                f.parked_audio, f.boot, f.release, f.output = parked, 'boot', 'release', Path(d) / 'recovery'
                original = dict(boot_id='boot', release='release',
                                audio_mode='blocked' if parked else 'parked-retention')
                r = sleep.verify_returned(f, original)
                self.assertFalse(r['complete'])
                self.assertIn('sleep audio mode mismatch', r['error'])
                self.assertEqual(f.events, ['gate', 'cleanup'])

    def fixture(self, root, *, control='auto', interrupt=False):
        master = root / 'master'
        (master / 'power').mkdir(parents=True)
        policy = master / 'power/control'
        policy.write_text(control + '\n')
        (master / 'power/runtime_status').write_text('active\n')
        statuses = [root / 'playback-status', root / 'capture-status']
        for path in statuses: path.write_text('closed\n')
        snapshot = dict(GPIO_DIR=0x1e, GPIO_VAL=0x80, SLV_STATUS=0,
                        FIFO_STATUS=0, DP1_B0=263, DP1_B1=263, DP4_B0=1543, DP4_B1=1543)
        writes = []
        def write(text):
            writes.append(text)
            snapshot['GPIO_VAL'] = int(text.split()[1], 16)
            if interrupt:
                raise InterruptedError('signal after owned auxiliary write')
        writer = SimpleNamespace(exists=lambda: True, write_text=write)
        params = dict(spx_wsa_gpio_mask='0x1e', spx_wsa_gpio_dir='0x1e', spx_wsa_gpio_val='0x18',
                      spx_wsa_en_pin='-1', spx_force_attach='0', spx_blind_attach='0',
                      spx_core_enum='0', spx_watchdog='0', spx_exact_windows_init='N',
                      spx_broadcast_audio='N', spx_enumerated_mode='Y', spx_write_only='N', spx_pio_mode='Y')
        def inventory(_):
            self.assertEqual(policy.read_text().strip(), 'on', 'hardware read without owned PM hold')
            return dict(internal_cards=['0'], devices=[dict(unit=n, status='UNATTACHED',
                        driver='wsa881x-codec', initialized=False) for n in (3, 4)], state=copy.deepcopy(snapshot))
        ops = sleep.ParkedAudio(root, 'boot', 'dvitali')
        ops.audio = SimpleNamespace(read_text=lambda p: Path(p).read_text().strip(),
                    assert_desktop_paused=lambda user: None, parameter=lambda module, name: params[name],
                    codec_paths=lambda: (writer, master), inventory=inventory)
        return ops, policy, statuses, snapshot, writes

    def test_cold_auxiliary_park_preserves_other_bits_and_each_pm_policy(self):
        for control in ('auto', 'on'):
            with self.subTest(control=control), tempfile.TemporaryDirectory() as d:
                ops, policy, statuses, snapshot, writes = self.fixture(Path(d), control=control)
                with patch.object(sleep.Path, 'glob', return_value=statuses):
                    held = ops.establish()
                    self.assertEqual(held['state']['GPIO_VAL'], 0x98)
                    self.assertEqual(writes, ['43 98\n'])
                    self.assertTrue(ops.cleanup()['restored'])
                self.assertEqual(policy.read_text().strip(), control)
                self.assertEqual(snapshot['GPIO_VAL'] & 0x1e, 0x18)
                self.assertFalse(ops.report['playback_or_capture_opened'])
                self.assertFalse(ops.report['firmware_sessions_proven_absent'])

    def test_open_capture_or_audio_request_precedes_pm_or_gpio_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            ops, policy, statuses, snapshot, writes = self.fixture(Path(d))
            statuses[1].write_text('RUNNING\n')
            with patch.object(sleep.Path, 'glob', return_value=statuses), self.assertRaises(AssertionError):
                ops.establish()
            statuses[1].write_text('closed\n')
            (Path(d) / 'audio-request.json').write_text('{}')
            with self.assertRaises(AssertionError): ops.establish()
            self.assertEqual(policy.read_text().strip(), 'auto')
            self.assertFalse(writes)

    def test_active_slave_fifo_or_port_refuses_gpio_write_and_restores_pm(self):
        for key, value in [('GPIO_DIR', 0), ('GPIO_VAL', 0x82), ('SLV_STATUS', 4),
                           ('FIFO_STATUS', 0x100), ('DP4_B1', 0x1000000)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as d:
                ops, policy, statuses, snapshot, writes = self.fixture(Path(d))
                snapshot[key] = value
                with patch.object(sleep.Path, 'glob', return_value=statuses):
                    with self.assertRaises(AssertionError): ops.establish()
                    self.assertTrue(ops.cleanup()['restored'])
                self.assertFalse(writes)
                self.assertEqual(policy.read_text().strip(), 'auto')

    def test_signal_after_aux_write_still_verifies_park_and_restores_pm(self):
        with tempfile.TemporaryDirectory() as d:
            ops, policy, statuses, snapshot, writes = self.fixture(Path(d), interrupt=True)
            with patch.object(sleep.Path, 'glob', return_value=statuses):
                with self.assertRaises(InterruptedError): ops.establish()
                self.assertTrue(ops.cleanup()['restored'])
            self.assertEqual(policy.read_text().strip(), 'auto')
            self.assertEqual(snapshot['GPIO_VAL'], 0x98)
            self.assertIn('after', ops.report)

    def test_post_wake_park_failure_still_restores_pm_and_fails(self):
        with tempfile.TemporaryDirectory() as d:
            ops, policy, statuses, snapshot, writes = self.fixture(Path(d))
            with patch.object(sleep.Path, 'glob', return_value=statuses):
                ops.establish()
                snapshot['FIFO_STATUS'] = 0x100
                with self.assertRaises(AssertionError): ops.cleanup()
            self.assertEqual(policy.read_text().strip(), 'auto')
            self.assertTrue(ops.report['restored'])


class OwnedShadows(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        stock, runtime, persistent = (root / name for name in ('stock', 'runtime', 'persistent'))
        for path in (stock, runtime, persistent): path.mkdir()
        for unit in sleep.UNITS:
            (stock / unit).write_bytes(b'[Unit]\nDescription=stock ' + unit.encode() + b'\n')
            (persistent / unit).symlink_to('/dev/null')
        live = sleep.Live.__new__(sleep.Live)
        live.owned, live.handlers = {}, {}
        live.fd = live.idle = None
        live.original_verified = True
        live.runtime_created = False
        live.properties = lambda unit, *args: dict(LoadState='loaded', FragmentPath=str(runtime / unit), DropInPaths='')
        live.run = lambda name, argv, timeout=5: 's "yes"' if name == 'can-suspend' else ''
        return stock, runtime, persistent, live

    def test_exact_bytes_and_cleanup_leave_persistent_masks(self):
        with tempfile.TemporaryDirectory() as d:
            stock, runtime, persistent, live = self.fixture(d)
            def restored(argv, **kwargs):
                unit = argv[2]
                return 'LoadState=masked\nFragmentPath=' + str(persistent / unit) + '\n'
            with patch.object(sleep, 'STOCK', stock), patch.object(sleep, 'RUNTIME', runtime), patch.object(sleep, 'PERSISTENT', persistent):
                live.open_shadows()
                for unit in sleep.UNITS:
                    self.assertEqual((runtime / unit).read_bytes(), (stock / unit).read_bytes())
                    self.assertEqual(os.readlink(persistent / unit), '/dev/null')
                with patch.object(sleep.subprocess, 'run'), patch.object(sleep.subprocess, 'check_output', side_effect=restored):
                    self.assertTrue(live.cleanup()['masks_restored'])
                self.assertEqual(list(runtime.iterdir()), [])

    def test_absent_runtime_directory_is_owned_and_removed_after_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            stock, runtime, persistent, live = self.fixture(d)
            runtime.rmdir()
            def restored(argv, **kwargs):
                return 'LoadState=masked\nFragmentPath=' + str(persistent / argv[2]) + '\n'
            with patch.object(sleep, 'STOCK', stock), patch.object(sleep, 'RUNTIME', runtime), patch.object(sleep, 'PERSISTENT', persistent):
                live.open_shadows()
                self.assertTrue(live.runtime_created)
                with patch.object(sleep.subprocess, 'run'), patch.object(sleep.subprocess, 'check_output', side_effect=restored):
                    self.assertTrue(live.cleanup()['masks_restored'])
                self.assertFalse(runtime.exists())

    def test_existing_shadow_not_owned_or_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            stock, runtime, persistent, live = self.fixture(d)
            existing = runtime / sleep.UNITS[0]
            existing.write_text('another owner')
            with patch.object(sleep, 'STOCK', stock), patch.object(sleep, 'RUNTIME', runtime):
                with self.assertRaises(FileExistsError): live.open_shadows()
            self.assertEqual(existing.read_text(), 'another owner')
            self.assertFalse(live.owned)

    def test_failed_load_still_owns_both_files_for_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            stock, runtime, persistent, live = self.fixture(d)
            live.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('reload failed'))
            with patch.object(sleep, 'STOCK', stock), patch.object(sleep, 'RUNTIME', runtime):
                with self.assertRaises(RuntimeError): live.open_shadows()
            self.assertEqual(set(live.owned), {runtime / unit for unit in sleep.UNITS})

    def test_cleanup_does_not_unlink_replaced_inode(self):
        with tempfile.TemporaryDirectory() as d:
            stock, runtime, persistent, live = self.fixture(d)
            path = runtime / sleep.UNITS[0]
            path.write_text('owned')
            live.owned[path] = path.stat().st_ino
            path.unlink()
            path.symlink_to(stock / sleep.UNITS[0])
            live.original_verified = False
            with self.assertRaises(AssertionError): live.cleanup()
            self.assertTrue(path.is_symlink())


if __name__ == '__main__': unittest.main()
