#!/usr/bin/env python3
"""Safety checks for desktop power restoration without live display changes."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class DisplayPowerTests(unittest.TestCase):
    def test_recovery_rejected_before_commands(self):
        with patch.multiple(trial, RELEASE='7.3.0-rc2-spx-mainline-20261004bg+', create=True), \
             patch.object(trial.os, 'geteuid', return_value=0), \
             patch.object(trial.os, 'uname', return_value=SimpleNamespace(release='6.18.3-1-surface+')), \
             patch.object(trial.subprocess, 'run') as run:
            with self.assertRaises(AssertionError):
                trial.display_power(SimpleNamespace(desktop_user='dvitali'))
            run.assert_not_called()

    def exercise(self, fail_off=False, fail_log=False):
        with tempfile.TemporaryDirectory() as directory:
            calls, power, counter = [], [0], [0]
            original_read = Path.read_text

            def read(path, *args, **kwargs):
                if str(path).endswith('/dri/0/state'):
                    if fail_off and power[0] == 3:
                        raise OSError('off snapshot failed')
                    active = int(power[0] == 0)
                    return (f'plane[46]: plane-0\n\tcrtc=crtc-0\n\tfb={102 * active}\n'
                            '\t\tallocated by = gnome-shell\n'
                            f'crtc[94]: crtc-0\n\tenable={active}\n\tactive={active}\n'
                            '\tmode: "2880x1920": 60 355500\n'
                            'connector[39]: eDP-1\n\tcrtc=crtc-0\n')
                return original_read(path, *args, **kwargs)

            def run(argv, **kwargs):
                calls.append(argv)
                if 'set-property' in argv:
                    power[0] = int(argv[-1])
                if argv[0] == 'journalctl' and fail_log:
                    raise TimeoutError('journal timed out')
                stdout = 'i ' + str(power[0]) if 'get-property' in argv else ''
                return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

            def ioctl(fd, command, buf, mutate):
                counter[0] += 1
                buf[:] = struct.pack('=IIqq', 1, counter[0], 100, counter[0] * 16667)

            with patch.multiple(trial, OUT=Path(directory), ATTEMPT='20261005ce', RELEASE='test', create=True), \
                 patch.object(trial, 'wifi_band_gate', return_value='boot'), \
                 patch.object(Path, 'glob', return_value=[Path('/sys/class/drm/card0-eDP-1')]), \
                 patch.object(Path, 'read_text', read), \
                 patch.object(trial.subprocess, 'run', side_effect=run), \
                 patch.object(trial.time, 'sleep'), \
                 patch.object(trial.os, 'open', return_value=123), \
                 patch.object(trial.os, 'close'), \
                 patch.object(trial.fcntl, 'ioctl', side_effect=ioctl):
                trial.display_power(SimpleNamespace(desktop_user='dvitali'))
            result = json.loads((Path(directory) / 'display-power/result.json').read_text())
            self.assertEqual(power[0], 0)
            self.assertTrue(result['restored'])
            self.assertEqual(calls[-1][1:3], ['release', 'device'])
            return result, calls

    def test_failure_after_off_restores_power_and_releases_lock(self):
        result, calls = self.exercise(fail_off=True)
        self.assertFalse(result['complete'])
        self.assertIn('off snapshot failed', result['error'])
        self.assertEqual([call[-1] for call in calls if 'set-property' in call], ['3', '0'])

    def test_log_failure_preserves_restoration_evidence(self):
        result, calls = self.exercise(fail_log=True)
        self.assertFalse(result['complete'])
        self.assertIn('journal timed out', result['kernel_log_error'])

    def test_two_real_state_transitions_and_vblank_restore(self):
        result, calls = self.exercise()
        self.assertTrue(result['complete'])
        self.assertEqual([call[-1] for call in calls if 'set-property' in call], ['3', '0', '3', '0', '0'])
        self.assertEqual(result['original_active_connectors'], {'eDP-1': '0'})
        self.assertEqual(result['snapshots']['off-2']['crtcs']['0']['active'], '0')
        self.assertEqual(len(result['snapshots']['finally-restored']['vblank']['0']), 2)


if __name__ == '__main__':
    unittest.main()
