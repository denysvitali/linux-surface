#!/usr/bin/env python3
"""Offline sequencing, normal-service evidence and owned cleanup tests."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
