#!/usr/bin/env python3
"""GMEM acceptance stays opt-in, runs once, and judges only unpatched-driver evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('spx_trial', HERE / 'trial.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)
spec = importlib.util.spec_from_file_location('spx_gmem_acceptance', HERE / 'gmem/acceptance.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

DEVICE = 'Device: Turnip Adreno (TM) 680; driver: turnip (Mesa); queue family 0\n'
STORE = 'SPX store_cp_blit: tile0=768x640 gmem_offset=0x0 va=0x%x pitch=3072 cpp=4 src=768x640 fmt=1\n'


class JudgeTests(unittest.TestCase):
    def test_pass_requires_hardware_device_and_pass_line(self):
        self.assertEqual(acceptance.judge('distro-gmem', 0, DEVICE + 'PASS; elapsed 3 s\n'), (True, []))
        self.assertFalse(acceptance.judge('distro-gmem', 0, 'PASS; elapsed 3 s\n')[0])
        self.assertFalse(acceptance.judge('distro-gmem', 0, DEVICE)[0])

    def test_failure_quotes_first_nonzero_mismatch_not_the_clean_baseline(self):
        text = DEVICE + ('2880x1920 frame=-1: 0/5529600 pixels differ\n'
                         '2880x1920 frame=0: 885094/5529600 pixels differ\nFAIL; elapsed 3 s\n')
        passed, notes = acceptance.judge('distro-gmem', 1, text)
        self.assertFalse(passed)
        self.assertIn('2880x1920 frame=0: 885094/5529600 pixels differ', notes)
        self.assertFalse(any('frame=-1' in note for note in notes))

    def test_diagnostic_run_requires_the_aligned_base_in_every_store(self):
        good = DEVICE + STORE % 0x200000 + 'PASS; elapsed 3 s\n'
        self.assertEqual(acceptance.judge('diagnostic-no-clear-full', 0, good), (True, []))
        old = DEVICE + STORE % 0x100000 + 'PASS; elapsed 3 s\n'
        passed, notes = acceptance.judge('diagnostic-no-clear-full', 0, old)
        self.assertFalse(passed)
        self.assertIn('GMEM base is 0x100000, not 0x200000', notes)
        silent = DEVICE + 'PASS; elapsed 3 s\n'
        self.assertFalse(acceptance.judge('diagnostic-no-clear-full', 0, silent)[0])


class PlanTests(unittest.TestCase):
    def test_environment_is_built_from_scratch_and_names_the_driver(self):
        with patch.dict('os.environ', {'TU_GMEM': '1', 'SPX_GMEM_CAP': '1', 'SPX_GMEM_VA_ADJ': '1',
                                       'VK_ICD_FILENAMES': '/workaround.json'}):
            runs = acceptance.plan('/pls', '/main.json')
        self.assertEqual([r[0] for r in runs], ['distro-gmem', 'distro-gmem+unaligned_store',
                                                  'diagnostic-no-clear-full'])
        for name, environment, argv in runs:
            for forbidden in ('TU_GMEM', 'SPX_GMEM_CAP', 'SPX_GMEM_VA_ADJ', 'VK_ICD_FILENAMES'):
                self.assertNotIn(forbidden, environment)
            self.assertNotIn('workaround', environment['VK_DRIVER_FILES'])
            self.assertTrue(environment['TU_DEBUG'].startswith('gmem'))
        self.assertEqual(runs[1][1]['TU_DEBUG'], 'gmem,unaligned_store')
        self.assertEqual(runs[2][1]['SPX_NO_COND'], '1')
        self.assertEqual(runs[2][2][1:], ['--single', '1', '1', '2877', '1917', '--no-clear'])


class DispatchTests(unittest.TestCase):
    def test_no_opt_in_no_run(self):
        with patch.object(trial.subprocess, 'run') as run:
            trial.dispatch_gmem_acceptance(SimpleNamespace(), {})
            run.assert_not_called()

    def test_existing_result_is_not_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'gmem-acceptance').mkdir()
            with patch.object(trial, 'OUT', output, create=True), patch.object(trial.subprocess, 'run') as run:
                trial.dispatch_gmem_acceptance(SimpleNamespace(), dict(gmem_acceptance=dict(msm_build_id='x')))
                run.assert_not_called()

    def test_opt_in_rejects_conflicting_experiments_before_effects(self):
        for command, flags in [('check', []), ('prepare', ['--cdsp']),
                               ('prepare', ['--tpm-sign']), ('prepare', ['--thermal-combined'])]:
            result = subprocess.run([sys.executable, '-B', str(HERE / 'trial.py'), command, '20261007test',
                                     '--gmem-acceptance', *flags], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('--gmem-acceptance requires prepare', result.stderr)


if __name__ == '__main__':
    unittest.main()
