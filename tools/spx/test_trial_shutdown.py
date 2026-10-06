#!/usr/bin/env python3
"""Reject experiments when native shutdown support cannot be prepared."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class ShutdownPreparationTests(unittest.TestCase):
    def exercise(self, state='Result=success\nExecMainStatus=0\n', executable=True,
                 start_error=None):
        with patch.object(trial.subprocess, 'run', side_effect=start_error), \
             patch.object(trial.subprocess, 'check_output', return_value=state), \
             patch.object(trial, 'Path', return_value=SimpleNamespace(is_file=lambda: True)), \
             patch.object(trial.os, 'access', return_value=executable):
            return trial.prepare_shutdown_ramfs()

    def test_success_requires_native_executable(self):
        self.assertTrue(self.exercise()['ready'])
        with self.assertRaises(AssertionError):
            self.exercise(executable=False)

    def test_failed_generator_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.exercise(start_error=subprocess.CalledProcessError(1, 'systemctl'))
        with self.assertRaises(AssertionError):
            self.exercise(state='Result=exit-code\nExecMainStatus=1\n')

    def test_generator_timeout_is_rejected(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.exercise(start_error=subprocess.TimeoutExpired('systemctl', 60))


if __name__ == '__main__':
    unittest.main()
