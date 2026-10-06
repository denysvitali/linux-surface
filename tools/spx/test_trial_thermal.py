#!/usr/bin/env python3
"""Queued workloads require explicit intent and never retry an interrupted run."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class QueuedThermalTests(unittest.TestCase):
    def test_opt_in_is_required(self):
        with patch.object(trial, 'thermal_check') as run:
            trial.dispatch_thermal(SimpleNamespace(), {})
            run.assert_not_called()

    def test_interrupted_run_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            prepared = dict(thermal_combined=True, thermal_gpu_fixture='/retained/fixture',
                            thermal_cpu_stress_ng='/private/stress-ng')
            args = SimpleNamespace()
            def start(value):
                self.assertTrue(value.thermal_combined)
                self.assertEqual(value.thermal_gpu_fixture, Path('/retained/fixture'))
                self.assertEqual(value.thermal_cpu_stress_ng, Path('/private/stress-ng'))
                (output / 'combined-thermal').mkdir()
                raise RuntimeError('interrupted workload')
            with patch.object(trial, 'OUT', output, create=True), \
                 patch.object(trial, 'thermal_check', side_effect=start) as run:
                with self.assertRaises(RuntimeError):
                    trial.dispatch_thermal(args, prepared)
                trial.dispatch_thermal(args, prepared)
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
