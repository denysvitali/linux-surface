#!/usr/bin/env python3
"""Ensure recovery cannot reuse a module tree belonging to another Image."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class RetainedModuleTests(unittest.TestCase):
    def exercise(self, image_matches=True, release='6.18.3-1-surface+',
                 cmdline='spx_boot=known-good'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / 'modules'
            modules.mkdir()
            image = root / 'build/arch/arm64/boot/Image'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'trial image')
            (modules / 'vmlinuz').write_bytes(b'trial image' if image_matches else b'other image')
            real_path = trial.Path

            def paths(value):
                if value == '/proc/cmdline':
                    return SimpleNamespace(read_text=lambda: cmdline)
                return real_path(value)

            with patch.multiple(trial, BUILD=root / 'build', RELEASE='trial-release', create=True), \
                 patch.object(trial, 'Path', side_effect=paths), \
                 patch.object(trial.os, 'uname', return_value=SimpleNamespace(release=release)):
                trial.verify_retained_modules({'replace_modules': []}, modules)

    def test_known_good_reuses_matching_image(self):
        self.exercise()

    def test_different_image_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.exercise(image_matches=False)

    def test_other_running_kernel_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.exercise(release='unknown')

    def test_recovery_requires_known_good_boot(self):
        with self.assertRaises(AssertionError):
            self.exercise(cmdline='spx_boot=other')


if __name__ == '__main__':
    unittest.main()
