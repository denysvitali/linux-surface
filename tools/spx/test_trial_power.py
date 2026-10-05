#!/usr/bin/env python3
"""Exercise battery refusal and process cleanup without device access."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class PowerTests(unittest.TestCase):
    def test_low_charge_refuses_before_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for node, value in {'BAT/type': 'Battery', 'BAT/status': 'Discharging',
                                'BAT/capacity': '14', 'BAT/voltage_now': '7173000',
                                'BAT/power_now': '2381000', 'BAT/energy_now': '4280000',
                                'AC/type': 'Mains', 'AC/online': '0'}.items():
                path = root / 'class/power_supply' / node
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            with patch.object(trial, 'power_sample', side_effect=lambda: original(root)), \
                 patch.object(trial, 'wifi_band_gate', return_value='boot'), \
                 patch.object(trial.subprocess, 'run'), patch.object(trial.subprocess, 'Popen') as spawn, \
                 patch.multiple(trial, OUT=root, ATTEMPT='20261005power', RELEASE='test', create=True):
                with self.assertRaises(AssertionError):
                    trial.power_measure(SimpleNamespace())
                spawn.assert_not_called()
                self.assertFalse((root / 'power-measure/result.json').exists())

    def test_phases_and_worker_cleanup(self):
        for failure in (AssertionError('guard'), OSError('private battery identity'), None):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                worker = Mock()
                worker.poll.return_value = None
                policy = Mock()
                policy.__truediv__ = Mock(return_value=Mock(read_text=Mock(return_value='0 1 2 3')))
                clock = [0]
                def sleep(seconds):
                    clock[0] += seconds
                row = dict(capacity=25, power_now=4000000, energy_now=7000000)
                with patch.multiple(trial, OUT=Path(directory), ATTEMPT='20261005power', RELEASE='test', create=True), \
                     patch.object(trial, 'wifi_band_gate', return_value='boot'), \
                     patch.object(trial.Path, 'glob', return_value=[policy]), \
                     patch.object(trial, 'power_sample', side_effect=([dict(row, energy_now=7000000-i*1000) for i in range(52)] if failure is None else
                                                                   [dict(row) for _ in range(19)] + [failure])), \
                     patch.object(trial.time, 'sleep', side_effect=sleep), \
                     patch.object(trial.time, 'monotonic', side_effect=lambda: clock[0]), \
                     patch.object(trial.Path, 'read_text', return_value='boot'), \
                     patch.object(trial.subprocess, 'run') as run, \
                     patch.object(trial.subprocess, 'Popen', return_value=worker) as spawn:
                    with self.assertRaises(AssertionError) if failure else nullcontext():
                        trial.power_measure(SimpleNamespace())
                    spawn.assert_called_once()
                    worker.terminate.assert_called_once()
                    worker.wait.assert_called_once()
                    self.assertEqual(run.call_args.args[0][1], 'release')
                result = json.loads((Path(directory) / 'power-measure/result.json').read_text())
                self.assertEqual(result['complete'], failure is None)
                if failure is None:
                    self.assertEqual(list(result['phases']), ['idle', 'load', 'recovery'])
                    for phase in result['phases'].values():
                        self.assertEqual(phase['median_watts'], 4.0)
                        self.assertEqual(phase['energy_delta_uwh'], 15000)
                        self.assertEqual(phase['samples'][-1]['phase_seconds'], 30)
                self.assertNotIn('private battery identity', json.dumps(result))


original = trial.power_sample
if __name__ == '__main__':
    unittest.main()
