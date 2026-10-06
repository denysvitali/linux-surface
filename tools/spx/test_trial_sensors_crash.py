#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Queue opt-in/one-shot dispatch without any device or service access."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
spec=importlib.util.spec_from_file_location('trial',Path(__file__).with_name('trial.py'))
trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)
sys.path.insert(0,str(Path(__file__).parent/'sensors'))
import crash_test


class Queue(unittest.TestCase):
    def test_no_optin_or_existing_evidence_never_runs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial,'OUT',Path(tmp),create=True), patch.object(trial.subprocess,'run') as run:
            trial.dispatch_sensors_crash(None,{})
            (Path(tmp)/'sensors-crash').mkdir()
            trial.dispatch_sensors_crash(None,dict(sensors_crash_recovery=True))
            run.assert_not_called()
    def test_explicit_queue_runs_once_with_same_recovery_owner(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial,'OUT',Path(tmp),create=True), patch.object(trial,'ATTEMPT','a',create=True), \
             patch.object(trial,'RELEASE','r',create=True), patch.object(trial.subprocess,'run') as run, \
             patch.object(trial.subprocess,'check_output',return_value='inactive\n'), \
             patch.object(crash_test,'Live') as live, patch.object(crash_test,'exercise',return_value=dict(complete=True)) as exercise:
            trial.dispatch_sensors_crash(None,dict(sensors_crash_recovery=True))
            live.assert_called_once_with(Path(tmp)/'sensors-crash','a','r')
            exercise.assert_called_once()
            self.assertEqual(run.call_args_list[0].args[0][-1],'sensor-crash-a')
            self.assertEqual(run.call_args_list[1].args[0][1],'release')
    def test_live_automatic_recovery_retains_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial,'OUT',Path(tmp),create=True), patch.object(trial,'ATTEMPT','a',create=True), \
             patch.object(trial,'RELEASE','r',create=True), patch.object(trial.subprocess,'run') as run, \
             patch.object(trial.subprocess,'check_output',return_value='activating\n'), \
             patch.object(crash_test,'Live'), patch.object(crash_test,'exercise',return_value=dict(complete=False,error='interrupted')):
            with self.assertRaises(RuntimeError):
                trial.dispatch_sensors_crash(None,dict(sensors_crash_recovery=True))
            self.assertEqual(run.call_count,1)


if __name__=='__main__':unittest.main()
