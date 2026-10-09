#!/usr/bin/env python3
"""Reject experiments when native shutdown support cannot be prepared."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
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


class BaselineReturnTests(unittest.TestCase):
    def test_promoted_boot_check_cannot_dispatch_hardware_work(self):
        def read(path, *args, **kwargs):
            if path.name == 'prepared.json':
                return '{"preboot_id":"old-boot","release":"7.3.0-test"}'
            if str(path) == '/proc/cmdline':
                return 'spx_attempt=20261009wx spx_baseline=20261009wx'
            raise AssertionError(path)

        with patch.object(sys, 'argv', ['trial.py', 'check', '20261009wx']), \
             patch.object(Path, 'read_text', autospec=True, side_effect=read), \
             patch.object(trial, 'functional_check') as check, \
             patch.object(trial, 'dispatch_audio') as audio, \
             patch.object(trial.subprocess, 'run') as run:
            trial.main()
            check.assert_not_called()
            audio.assert_not_called()
            run.assert_not_called()

    def test_promoted_baseline_cannot_be_rebooted_by_trial_return(self):
        with patch.object(trial, 'ATTEMPT', '20261009wx', create=True), \
             patch.object(trial, 'Path', return_value=SimpleNamespace(
                 read_text=lambda: 'spx_attempt=20261009wx spx_baseline=20261009wx')), \
             patch.object(trial.subprocess, 'run') as run:
            trial.return_to_default(SimpleNamespace())
            run.assert_not_called()

    def test_mainline_is_accepted_as_persistent_default(self):
        with patch.object(trial.subprocess, 'check_output',
                          return_value='saved_entry=spx-mainline\n'):
            self.assertEqual(trial.persistent_default(), 'spx-mainline')


if __name__ == '__main__':
    unittest.main()
