#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline effect-order tests: fake transport, no services/devices/QRTR."""
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('lifecycle', Path(__file__).with_name('lifecycle.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

REMOVED = 'channel remove users=0 pending=0\n'
RESTORED = 'SDSP heap restored to HLOS owners=0x8; final context drained\n'
SHARED = 'SDSP heap [mem 0xfd800000-0xfe7fffff] shared owners=0x28\n'


class Fake:
    def __init__(self, patched=True, teardown=REMOVED + RESTORED, fail=None):
        self.patched, self.teardown, self.fail = patched, teardown, fail
        self.effects = []
        self.saved = []
        self.reads = []
        self.backend_calls = 0

    def gate(self):
        if not self.patched:
            raise module.Refused('no patched module lease')
        return dict(host_pid=817)

    def save(self, result):
        self.saved.append(dict(result))

    def cursor(self):
        return 'cursor'

    def effect(self, name):
        self.effects.append(name)
        if self.fail == name:
            raise RuntimeError(name + ' failed')

    def stop_services(self):
        self.effect('stop-proxy-and-provider')

    def stop_slpi(self):
        self.effect('stop-slpi')

    def start_slpi(self):
        # This assertion catches any restart issued without inspecting proof.
        assert 'teardown-kernel.log' in self.reads
        assert module.teardown_proven(self.teardown)
        self.effect('start-slpi')

    def start_services(self):
        self.effect('start-provider-and-proxy')

    def kernel_since(self, cursor, filename):
        self.reads.append(filename)
        return self.teardown if filename == 'teardown-kernel.log' else SHARED

    def backend(self):
        return dict(host_pid=900)

    def stream(self, sensor):
        self.effect('stream-' + sensor)
        return dict(returncode=0, stdout='sensor measurement: X=1 Y=2 Z=3\n' * 20,
                    stderr='Sensor disable request sent successfully')

    def desktop(self):
        self.effect('native-monitor')
        return dict(accelerometer=dict(returncode=124, stdout='Accelerometer orientation changed: bottom-up', stderr=''),
                    compass=dict(returncode=124, stdout='Compass heading changed: 70.25', stderr=''))

    def capture(self):
        self.reads.append('final-capture')


class EffectOrder(unittest.TestCase):
    def test_actual_live_gate_rejects_old_module_before_commands(self):
        live = module.Live.__new__(module.Live)
        live.attempt, live.release = '20261006co', 'trial'
        live.checked = Mock(side_effect=AssertionError('old module gate must stop before commands'))
        files = {
            '/proc/cmdline': 'spx_attempt=20261006co spx_boot=mainline-functional spx_sensors=1',
            '/proc/iomem': 'fd800000-fe7fffff : System RAM',
        }
        with patch.object(module, 'Path', side_effect=lambda name: SimpleNamespace(read_text=lambda: files[name])), \
             patch.object(module.os, 'geteuid', return_value=0), \
             patch.object(module.os, 'uname', return_value=SimpleNamespace(release='trial')):
            with self.assertRaisesRegex(module.Refused, 'no patched SDSP ownership lease'):
                live.gate()
        live.checked.assert_not_called()

    def test_old_module_refuses_without_any_effect(self):
        ops = Fake(patched=False)
        self.assertFalse(module.exercise(ops)['complete'])
        self.assertEqual(ops.effects, [])
        self.assertIn('final-capture', ops.reads)

    def test_missing_restore_stops_without_restart(self):
        ops = Fake(teardown=REMOVED)
        result = module.exercise(ops)
        self.assertFalse(result['complete'])
        self.assertFalse(result['restarted'])
        self.assertEqual(ops.effects, ['stop-proxy-and-provider', 'stop-slpi'])

    def test_pending_context_and_failed_restore_never_restart(self):
        for log in ('channel remove users=0 pending=1\n' + RESTORED,
                    REMOVED + 'SDSP heap restore failed -5\n', RESTORED + REMOVED):
            with self.subTest(log=log):
                ops = Fake(teardown=log)
                self.assertFalse(module.exercise(ops)['complete'])
                self.assertNotIn('start-slpi', ops.effects)

    def test_positive_proof_orders_all_effects(self):
        ops = Fake()
        result = module.exercise(ops)
        self.assertTrue(result['complete'])
        self.assertEqual(ops.effects, ['stop-proxy-and-provider', 'stop-slpi', 'start-slpi',
                                      'start-provider-and-proxy', 'stream-accelerometer',
                                      'stream-gyroscope', 'stream-magnetometer', 'native-monitor'])
        self.assertTrue(result['restore_proven'])

    def test_proxy_discovery_polls_until_true(self):
        live = module.Live.__new__(module.Live)
        live.private = False
        live.checked = Mock(return_value='')
        live.backend = Mock(return_value={})
        live.run = Mock(side_effect=[dict(returncode=0, stdout='(<false>,)'),
                                    dict(returncode=0, stdout='(<true>,)')])
        with patch.object(module.time, 'sleep'):
            live.start_services()
        self.assertEqual(live.run.call_count, 2)
        self.assertEqual(live.checked.call_args_list[0].args[0], 'start-provider')
        self.assertEqual(live.checked.call_args_list[1].args[0], 'start-proxy')

    def test_native_cached_header_orientation_is_usable(self):
        ops = Fake()
        desktop = ops.desktop()
        desktop['accelerometer']['stdout'] = '=== Has accelerometer (orientation: bottom-up, tilt: tilted-up)'
        ops.desktop = lambda: desktop
        self.assertTrue(module.exercise(ops)['complete'])

    def test_stop_failure_never_restarts_and_saves_partial(self):
        ops = Fake(fail='stop-slpi')
        result = module.exercise(ops)
        self.assertFalse(result['complete'])
        self.assertNotIn('start-slpi', ops.effects)
        self.assertIn('error', ops.saved[-1])

    def test_stream_requires_finite_samples_and_disable(self):
        record = dict(returncode=0, stdout='sensor measurement: X=1 Y=2 Z=3\n' * 20,
                      stderr='Sensor disable request sent successfully')
        self.assertTrue(module.stream_proven(record))
        self.assertFalse(module.stream_proven(dict(record, stderr='')))
        self.assertFalse(module.stream_proven(dict(record, stdout=record['stdout'].replace('X=1', 'X=nan'))))
        self.assertFalse(module.stream_proven(dict(record, returncode=1)))


if __name__ == '__main__':
    unittest.main()
