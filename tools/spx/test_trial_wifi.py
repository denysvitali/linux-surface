#!/usr/bin/env python3
"""Check trial rejection and Wi-Fi restoration without touching hardware."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class WifiBandTests(unittest.TestCase):
    def test_recovery_rejected_before_any_command(self):
        with patch.multiple(trial, RELEASE='7.3.0-rc2-spx-mainline-20261004bg+', create=True), \
             patch.object(trial.os, 'geteuid', return_value=0), \
             patch.object(trial.os, 'uname', return_value=SimpleNamespace(release='6.18.3-1-surface+')), \
             patch.object(trial.subprocess, 'run') as run, \
             patch.object(trial.subprocess, 'check_output') as check:
            with self.assertRaises(AssertionError):
                trial.wifi_band(SimpleNamespace(wifi_profile='saved'))
            run.assert_not_called()
            check.assert_not_called()

    def exercise(self, association_fails=False, frequency=2422):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name)
        calls = []
        source = '11111111-1111-1111-1111-111111111111'
        original = '22222222-2222-2222-2222-222222222222'
        clone = '33333333-3333-3333-3333-333333333333'

        def run(argv, **kwargs):
            calls.append(argv)
            stdout, stderr, rc = '', '', 0
            if argv[0] == 'nmcli':
                if 'connection.uuid,connection.type,802-11-wireless.ssid' in argv:
                    stdout = source + '\n802-11-wireless\nsaved:ssid\n'
                elif 'GENERAL.CON-UUID' in argv:
                    stdout = original
                elif 'SSID,FREQ' in argv:
                    stdout = 'saved:ssid:2422 MHz\n'
                elif 'NAME' in argv:
                    stdout = 'saved\noriginal\n'
                elif 'connection.uuid' in argv:
                    stdout = clone
                elif 'up' in argv and clone in argv and association_fails:
                    rc, stderr = 10, 'association failed'
            elif argv[0] == 'iw':
                stdout = 'Connected to 00:11:22:33:44:55\n freq: ' + str(frequency) + '\n'
            elif argv[0] == 'curl':
                stdout = '25000000 5.0 5000000'
            return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

        with patch.multiple(trial, OUT=out, ATTEMPT='20261005cd', RELEASE='test', create=True), \
             patch.object(trial, 'wifi_band_gate', return_value='boot'), \
             patch.object(trial.subprocess, 'run', side_effect=run):
            trial.wifi_band(SimpleNamespace(wifi_profile='saved'))
        result = json.loads((out / 'wifi-band/result.json').read_text())
        self.assertTrue(result['restoration']['original_active'])
        self.assertTrue(result['restoration']['clone_deleted'])
        self.assertTrue(any('up' in call and original in call for call in calls))
        self.assertTrue(any('delete' in call and 'spx-wifi-band-20261005cd' in call for call in calls))
        mutations = [call for call in calls if 'modify' in call]
        self.assertEqual(len(mutations), 1)
        self.assertIn(clone, mutations[0])
        self.assertNotIn(source, mutations[0])
        return result, calls

    def test_failed_association_restores_original_and_deletes_owned_clone(self):
        result, calls = self.exercise(association_fails=True)
        self.assertFalse(result['complete'])
        self.assertFalse(any(call[0] == 'curl' for call in calls))

    def test_5ghz_association_cannot_pass(self):
        result, calls = self.exercise(frequency=5180)
        self.assertFalse(result['complete'])
        self.assertFalse(any(call[0] == 'curl' for call in calls))

    def test_two_exact_downloads_and_restoration_pass(self):
        result, calls = self.exercise(frequency=2422.0)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['links']), 4)
        self.assertEqual([t['bytes'] for t in result['transfers']], [25000000, 25000000])
        self.assertEqual(sum(call[0] == 'curl' for call in calls), 2)


if __name__ == '__main__':
    unittest.main()
