#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline lifecycle tests; no FastRPC or QRTR access."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('supervise', Path(__file__).with_name('supervise.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Lifecycle(unittest.TestCase):
    def run_case(self, daemon, checker, notify=None, timeout=0.3, witness=None):
        children = []
        spawn = subprocess.Popen
        stopped = threading.Event()
        messages = []
        def record(*args, **kwargs):
            child = spawn(*args, **kwargs)
            children.append(child)
            return child
        def send(message):
            messages.append(message)
            if notify:
                notify(message, stopped)
        with patch.object(module.subprocess, 'Popen', side_effect=record):
            result = module.supervise([sys.executable, '-c', daemon],
                                      [sys.executable, '-c', checker],
                                      stopped, send, timeout, witness=witness)
        self.assertTrue(all(child.poll() is not None for child in children))
        return result, messages

    def test_readiness_keeps_listener_until_requested_stop(self):
        result, messages = self.run_case('import time; time.sleep(30)', 'pass',
            lambda message, stop: stop.set() if message.startswith('READY=') else None)
        self.assertEqual(result, 0)
        self.assertEqual(sum(message.startswith('READY=') for message in messages), 1)
        self.assertIn('STOPPING=1', messages)

    def test_intentional_stop_never_marks_crash_eligible(self):
        events=[]
        self.run_case('import time; time.sleep(30)', 'pass',
                      lambda message, stop: stop.set() if message.startswith('READY=') else None,
                      witness=lambda event, daemon: events.append(event))
        self.assertEqual(events, ['ready','intentional-stop'])

    def test_initial_exit_never_marks_crash_eligible(self):
        events=[]
        self.run_case('pass', 'import time; time.sleep(30)', witness=lambda event, daemon: events.append(event))
        self.assertEqual(events, [])

    def test_missing_metadata_cleans_up_listener_and_blocked_checker(self):
        result, messages = self.run_case('import time; time.sleep(30)', 'import time; time.sleep(30)')
        self.assertEqual(result, 1)
        self.assertFalse(any(message.startswith('READY=') for message in messages))

    def test_zero_exit_listener_is_failure_and_not_restarted(self):
        result, messages = self.run_case('pass', 'import time; time.sleep(30)')
        self.assertEqual(result, 1)
        self.assertFalse(any(message.startswith('READY=') for message in messages))

    def test_listener_exit_after_readiness_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'exit'
            events=[]
            result, messages = self.run_case(
                'import pathlib,time\np=pathlib.Path(' + repr(str(marker)) + ')\nwhile not p.exists(): time.sleep(.01)',
                'pass', lambda message, _: marker.touch() if message.startswith('READY=') else None,
                witness=lambda event, daemon: events.append(event))
        self.assertEqual(result, 1)
        self.assertTrue(any(message.startswith('READY=') for message in messages))
        self.assertEqual(events, ['ready', 'crash'])


if __name__ == '__main__':
    unittest.main()
