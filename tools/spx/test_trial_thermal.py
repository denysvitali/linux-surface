#!/usr/bin/env python3
"""Queued workloads require explicit intent and never retry an interrupted run."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import json
import subprocess
import sys
from unittest.mock import Mock
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class QueuedThermalTests(unittest.TestCase):
    def test_trip_argument_is_prepare_only_and_requires_policy_opt_in(self):
        path = Path(__file__).with_name('trial.py')
        for command, options in (('thermal', ['--cpu-passive-cooling']),
                                 ('prepare', []), ('prepare', ['--cpu-passive-cooling', '--cpu-passive-trip', '85000'])):
            run = subprocess.run([sys.executable, '-B', str(path), command, '20261007test',
                '--cpu-passive-trip', '55000', *options], text=True, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn('cpu-passive-trip', run.stderr)

    def test_prepared_trip_reports_inherited_policy_without_rewriting(self):
        spec = importlib.util.spec_from_file_location('thermal', Path(__file__).with_name('thermal.py'))
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with patch.dict(sys.modules, thermal=module), \
             patch.object(module, 'stage_policy') as stage, \
             patch.object(module, 'policy_trip', return_value=55000):
            args = SimpleNamespace(cpu_passive_cooling=False, cpu_passive_trip=None)
            self.assertEqual(trial.stage_cpu_policy(args, Path('/retained/dtb')), 55000)
            stage.assert_not_called()
            args.cpu_passive_cooling = True
            self.assertEqual(trial.stage_cpu_policy(args, Path('/retained/dtb')), 55000)
            stage.assert_called_once_with(Path('/retained/dtb'), 75000)

    def test_manual_and_queued_runs_use_prepared_actual_trip_and_old_record_default(self):
        for combined in (False, True):
            for trip in (55000, 75000, 'old'):
                with self.subTest(combined=combined, trip=trip), tempfile.TemporaryDirectory() as directory:
                    output = Path(directory)
                    prepared = dict(thermal_combined=True, thermal_gpu_fixture='/retained/fixture')
                    if trip != 'old':
                        prepared['cpu_passive_trip_mc'] = trip
                    (output / 'prepared.json').write_text(json.dumps(prepared))
                    args = SimpleNamespace(thermal_combined=combined,
                        thermal_gpu_fixture=Path('/retained/fixture'), thermal_cpu_stress_ng=None)
                    live = Mock(); live.exercise.return_value = dict(complete=True, responses={'0': True, '1': True})
                    module = SimpleNamespace(Live=Mock(return_value=live), CombinedLive=Mock(return_value=live))
                    with patch.dict(sys.modules, thermal=module), \
                         patch.object(trial, 'OUT', output, create=True), \
                         patch.object(trial, 'ATTEMPT', '20261007test', create=True), \
                         patch.object(trial, 'RELEASE', 'test-kernel', create=True), \
                         patch.object(trial.subprocess, 'run'):
                        if combined:
                            trial.dispatch_thermal(args, prepared)
                        else:
                            trial.thermal_check(args)
                    constructor = module.CombinedLive if combined else module.Live
                    self.assertEqual(constructor.call_args.kwargs['passive_trip'], 75000 if trip == 'old' else trip)
                    live.exercise.assert_called_once()

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
