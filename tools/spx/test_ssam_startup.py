#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exercise the workaround with fake sysfs and command boundaries only."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ssam_startup as ssam


TIMEOUT = ('surface_serial_hub serial1-0: error -ETIMEDOUT: failed to get firmware version\n'
           'surface_serial_hub serial1-0: probe with driver surface_serial_hub failed with error -110\n')


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, content in {
            'sys/firmware/devicetree/base/compatible': 'microsoft,surface-pro-x\0qcom,sc8180x\0',
            'proc/sys/kernel/random/boot_id': 'd87f94b5-e519-4372-be2e-c616d81f5095',
            'proc/sys/kernel/osrelease': 'test-kernel',
            'proc/uptime': '11.00 20.00',
            'sys/bus/serial/devices/serial1-0/of_node/compatible': 'microsoft,surface-sam\0',
            'sys/bus/serial/drivers/surface_serial_hub/bind': '',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.client = self.root / 'sys/bus/serial/devices/serial1-0'
        self.commands = []
        self.messages = TIMEOUT
        self.lock_busy = False
        self.race = False
        self.fail_bind = False
        self.timeout_bind = False

    def attach(self):
        (self.client / 'driver').symlink_to('../fake-driver')

    def command(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[0] == 'journalctl':
            self.assertIn('--boot=d87f94b5e5194372be2ec616d81f5095', argv)
            self.assertIn('--dmesg', argv)
            return subprocess.CompletedProcess(argv, 0, self.messages, '')
        if argv[0] == 'fake-lock':
            if argv[1] == 'acquire':
                if self.lock_busy:
                    return subprocess.CompletedProcess(argv, 1, '', 'held by tester')
                if self.race:
                    self.attach()
            return subprocess.CompletedProcess(argv, 0, '', '')
        self.assertEqual(argv[-1], 'serial1-0')
        if self.timeout_bind:
            raise subprocess.TimeoutExpired(argv, 20)
        if self.fail_bind:
            return subprocess.CompletedProcess(argv, 1, '', 'Input/output error')
        self.attach()
        return subprocess.CompletedProcess(argv, 0, '', '')

    def run_helper(self):
        with patch.object(ssam.subprocess, 'run', side_effect=self.command), \
             patch.object(ssam.time, 'sleep') as sleep, \
             patch('builtins.print'):
            result = ssam.run(self.root, Path('fake-lock'))
        if result['outcome'] != 'wrong_board':
            sleep.assert_called_once_with(19.0)
        return result

    def writes(self):
        return [c for c in self.commands if c[0] not in ('journalctl', 'fake-lock')]

    def test_wrong_board_never_runs_commands(self):
        (self.root / 'sys/firmware/devicetree/base/compatible').write_text(
            'microsoft,surface-pro-x-other\0qcom,sc8180x\0')
        self.assertEqual(self.run_helper()['outcome'], 'wrong_board')
        self.assertEqual(self.commands, [])

    def test_bound_controller_is_never_touched(self):
        self.attach()
        self.assertEqual(self.run_helper()['outcome'], 'already_bound')
        self.assertEqual(self.commands, [])

    def test_requires_both_exact_messages_for_this_client(self):
        for messages in ['', TIMEOUT.splitlines()[0], TIMEOUT.splitlines()[1],
                         TIMEOUT.replace('serial1-0', 'serial2-0'),
                         TIMEOUT.replace('-ETIMEDOUT', '-EIO'),
                         TIMEOUT.replace('error -110', 'error -5')]:
            with self.subTest(messages=messages):
                self.messages = messages
                self.commands.clear()
                self.assertEqual(self.run_helper()['outcome'], 'no_matching_timeout')
                self.assertEqual(len(self.commands), 1)

    def test_busy_device_is_not_stolen(self):
        self.lock_busy = True
        self.assertEqual(self.run_helper()['outcome'], 'device_busy')
        self.assertFalse(self.writes())
        self.assertEqual([c[1] for c in self.commands if c[0] == 'fake-lock'], ['acquire'])

    def test_binding_during_lock_acquisition_is_preserved(self):
        self.race = True
        self.assertEqual(self.run_helper()['outcome'], 'bound_before_retry')
        self.assertFalse(self.writes())
        self.assertEqual(self.commands[-1][1], 'release')

    def test_one_successful_bind_and_release(self):
        result = self.run_helper()
        self.assertEqual(result['outcome'], 'bound')
        self.assertTrue(result['bound_after'])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.commands[-1][1], 'release')

    def test_failed_bind_is_not_retried_on_service_restart(self):
        self.fail_bind = True
        self.assertEqual(self.run_helper()['outcome'], 'bind_failed')
        self.assertEqual(self.commands[-1][1], 'release')
        self.assertEqual(self.run_helper()['outcome'], 'already_attempted')
        self.assertEqual(len(self.writes()), 1)

    def test_timed_out_bind_releases_lock_without_restarting_probe(self):
        self.timeout_bind = True
        self.assertEqual(self.run_helper()['outcome'], 'bind_timed_out')
        self.assertEqual(self.commands[-1][1], 'release')
        self.assertEqual(self.run_helper()['outcome'], 'already_attempted')
        self.assertEqual(len(self.writes()), 1)


if __name__ == '__main__':
    unittest.main()
