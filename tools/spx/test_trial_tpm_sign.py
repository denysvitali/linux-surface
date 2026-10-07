#!/usr/bin/env python3
"""Signing remains opt-in and consumes its prepared private fixture once."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class SigningQueueTests(unittest.TestCase):
    def test_prepare_opt_in_rejects_conflicting_experiments_before_effects(self):
        for command, flags in [('tpm-sign', []), ('prepare', ['--audio']), ('prepare', ['--cdsp']),
                               ('prepare', ['--thermal-combined']), ('prepare', ['--sensors-crash-recovery'])]:
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('trial.py')),
                                     command, '20261007test', '--tpm-sign', *flags], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--tpm-sign requires prepare', result.stderr)

    def test_no_opt_in_no_run(self):
        with patch.object(trial, 'tpm_sign') as run:
            trial.dispatch_tpm_sign(SimpleNamespace(), {})
            run.assert_not_called()

    def test_prepared_fixture_propagates_and_interrupted_run_is_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            prepared = dict(tpm_sign=True, tpm_tools='/private/fixture/usr/bin')
            args = SimpleNamespace(tpm_tools=Path('/wrong/default'))
            def start(value):
                self.assertEqual(value.tpm_tools, Path('/private/fixture/usr/bin'))
                (output / 'tpm-sign').mkdir()
                raise RuntimeError('interrupted signature')
            with patch.object(trial, 'OUT', output, create=True), patch.object(trial, 'tpm_sign', side_effect=start) as run:
                with self.assertRaises(RuntimeError):
                    trial.dispatch_tpm_sign(args, prepared)
                trial.dispatch_tpm_sign(args, prepared)
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
