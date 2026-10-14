#!/usr/bin/env python3
"""Watchdog ownership, nonce and boot attribution with no real device/ioctl."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def marker():
    return dict(boot_id='prior', release='kernel', attempt='20261014test', nonce='nonce',
                armed=True, timeout_seconds=10, pretimeout_seconds=0, pre_bootstatus=0)


class FakeWatchdog:
    release = 'kernel'
    def __init__(self, bootstatus=0):
        self.calls, self.pending, self.failure, self.collection = [], None, None, None
        self.bootstatus, self.timeout, self.pretimeout = bootstatus, 30, 0
    def release_manager(self):
        self.calls.append('release'); return 30000000
    def restore_manager(self, value):
        assert value == 30000000
        self.calls.append('restore')
    def open(self):
        self.calls.append('open'); return 7
    def ioctl(self, fd, request, value=0):
        assert fd == 7
        self.calls.append(('ioctl', request, value))
        if request == trial.WDIOC_GETBOOTSTATUS: return self.bootstatus
        if request == trial.WDIOC_GETPRETIMEOUT: return self.pretimeout
        if request == trial.WDIOC_SETPRETIMEOUT: self.pretimeout = value; return value
        if request == trial.WDIOC_SETTIMEOUT: self.timeout = value; return value
        if request == trial.WDIOC_GETTIMEOUT: return self.timeout
        raise AssertionError('unexpected ioctl')
    def disarm_close(self, fd):
        assert fd == 7; self.calls.append('disarm-close')
    def save_pending(self, record):
        self.pending = dict(record); self.calls.append('persist')
    def sync(self): self.calls.append('sync')
    def wait(self, seconds):
        assert seconds == 20
        assert self.calls[-2:] == ['persist', 'sync']
        assert self.pending['armed']
        assert self.calls.count('open') == 1
        self.calls.append('wait20')
    def save_failure(self, record): self.failure = dict(record); self.calls.append('failure')
    def save_collection(self, record): self.collection = dict(record); self.calls.append('collection')
    def remove_pending(self): self.pending = None; self.calls.append('consume')


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        # Any accidental actual ioctl is a test failure, including all error paths.
        self.guard = patch.object(trial.fcntl, 'ioctl', side_effect=AssertionError('real ioctl forbidden'))
        self.guard.start(); self.addCleanup(self.guard.stop)

    def test_no_reset_disarms_restores_and_records_failure(self):
        ops = FakeWatchdog()
        result = trial.watchdog_reset_test(ops, marker())
        self.assertEqual(result['status'], 'fail')
        self.assertIn('20 seconds', result['error'])
        self.assertFalse(result['armed'])
        self.assertEqual(ops.calls[-4:], ['disarm-close', 'restore', 'failure', 'consume'])
        self.assertEqual(ops.failure, result)

    def test_zeroes_pretimeout_and_rejects_stale_reset_flag(self):
        ops = FakeWatchdog(); ops.pretimeout = 2
        trial.watchdog_reset_test(ops, marker())
        self.assertIn(('ioctl', trial.WDIOC_SETPRETIMEOUT, 0), ops.calls)
        ops = FakeWatchdog(trial.WDIOF_CARDRESET)
        result = trial.watchdog_reset_test(ops, marker())
        self.assertEqual(result['status'], 'fail')
        self.assertNotIn('wait20', ops.calls)
        self.assertEqual(ops.calls.count('open'), 1)
        self.assertIn('restore', ops.calls)

    def test_busy_open_restores_pid1_without_second_open(self):
        ops = FakeWatchdog()
        with patch.object(ops, 'open', side_effect=OSError('busy')) as opened:
            result = trial.watchdog_reset_test(ops, marker())
        opened.assert_called_once()
        self.assertIn('restore', ops.calls)
        self.assertEqual(result['status'], 'fail')

    def test_arm_io_error_and_cleanup_failure_are_retained(self):
        ops = FakeWatchdog()
        with patch.object(ops, 'ioctl', side_effect=OSError('ioctl failed')), \
             patch.object(ops, 'disarm_close', side_effect=OSError('disarm failed')):
            result = trial.watchdog_reset_test(ops, marker())
        self.assertEqual(result['status'], 'fail')
        self.assertIn('cleanup_error', ops.failure)
        self.assertIn('restore', ops.calls)
        self.assertIsNone(ops.pending)

    def test_collection_only_passes_new_reset_cause_and_immediate_boot(self):
        for previous, status, expected in [('prior', 0x20, 'pass'), ('prior', 0, 'blocked'),
                                            ('older', 0x20, 'blocked'), (None, 0x20, 'blocked')]:
            with self.subTest(previous=previous, status=status):
                ops = FakeWatchdog(status)
                r = trial.watchdog_collect_test(ops, marker(), 'current', previous)
                self.assertEqual(r['status'], expected)
                self.assertEqual(r['complete'], expected == 'pass')
                self.assertEqual(r['marker']['nonce'], 'nonce')
                self.assertEqual(r['boot_id'], 'current')
                self.assertEqual(ops.calls[-2:], ['collection', 'consume'])
                if previous == 'prior':
                    self.assertEqual(ops.calls.count('open'), 1)
                    self.assertIn('restore', ops.calls)
                else:
                    self.assertNotIn('open', ops.calls)

    def test_same_boot_retry_does_not_consume_or_open(self):
        ops = FakeWatchdog()
        self.assertIsNone(trial.watchdog_collect_test(ops, marker(), 'prior', 'older'))
        self.assertEqual(ops.calls, [])

    def test_unarmed_nonce_timeout_and_stale_status_cannot_pass(self):
        for change in [dict(armed=False), dict(nonce=''), dict(timeout_seconds=30),
                       dict(pretimeout_seconds=1), dict(pre_bootstatus=0x20)]:
            ops = FakeWatchdog(0x20); value = dict(marker(), **change)
            r = trial.watchdog_collect_test(ops, value, 'current', 'prior')
            self.assertEqual(r['status'], 'blocked')
            self.assertFalse(r['complete'])

    def test_collection_io_and_restoration_failures(self):
        ops = FakeWatchdog()
        with patch.object(ops, 'ioctl', side_effect=OSError('bootstatus missing')):
            r = trial.watchdog_collect_test(ops, marker(), 'current', 'prior')
        self.assertEqual(r['status'], 'blocked')
        self.assertIn('restore', ops.calls)
        ops = FakeWatchdog(0x20)
        with patch.object(ops, 'restore_manager', side_effect=OSError('restore failed')):
            r = trial.watchdog_collect_test(ops, marker(), 'current', 'prior')
        self.assertEqual(r['status'], 'fail')
        self.assertFalse(r['complete'])

    def test_durable_write_fsyncs_file_and_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(trial.os, 'fsync') as sync:
            target = Path(directory) / 'private/result.json'
            trial.WatchdogLive.durable(target, marker())
            self.assertEqual(json.loads(target.read_text()), marker())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(sync.call_count, 2)

    def test_collector_retry_reuses_durable_consumption_without_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = root / 'watchdog-reset-pending.json'
            pending.write_text(json.dumps(marker()))
            output = root / 'boots/current/watchdog-reset/result.json'
            output.parent.mkdir(parents=True)
            output.write_text(json.dumps(dict(consumed=True,marker=marker())))
            real_path = Path
            def paths(value):
                if value == '/proc/sys/kernel/random/boot_id':
                    return SimpleNamespace(read_text=lambda: 'current')
                return real_path(value)
            ops = FakeWatchdog()
            with patch.object(trial,'WATCHDOG_PENDING',pending), \
                 patch.object(trial,'Path',side_effect=paths), \
                 patch.object(trial.os,'geteuid',return_value=0), \
                 patch.object(trial,'WatchdogLive',return_value=ops), \
                 patch.object(trial.subprocess,'run',side_effect=AssertionError('no collector command expected')):
                trial.watchdog_collect(SimpleNamespace())
            self.assertEqual(ops.calls,['consume'])

    def test_pid1_property_uses_runtime_dbus_override_and_readback(self):
        ops = trial.WatchdogLive(Path('/fake'))
        with patch.object(trial.subprocess, 'run') as run, \
             patch.object(trial.subprocess, 'check_output', return_value='t 0'):
            ops.set_property(0)
        self.assertEqual(run.call_args.args[0], ['busctl', 'set-property',
            *ops.manager, 't', '0'])



class WatchdogBootHookTests(unittest.TestCase):
    def test_explicit_pending_marker_collects_before_validator(self):
        spec = importlib.util.spec_from_file_location('automatic_validation',
            Path(__file__).parent / 'boot-diagnostics/automatic-validation.py')
        wrapper = importlib.util.module_from_spec(spec); spec.loader.exec_module(wrapper)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'runner'; binary.write_text('fake'); binary.chmod(0o755)
            (root / 'watchdog-reset-pending.json').write_text(json.dumps(marker()))
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                if 'watchdog-collect' in command: return SimpleNamespace(returncode=0)
                raise FileNotFoundError('fake validator missing')
            result = wrapper.run_once(root,binary,root,'current','kernel',execute=execute,
                network_wait_seconds=0,route_reader=lambda _: '')
            self.assertEqual(result,1)
            self.assertEqual(calls[0][-2:],['watchdog-collect','20261014test'])
            self.assertEqual(calls[1][0],str(binary))


if __name__ == '__main__': unittest.main()
