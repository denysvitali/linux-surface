#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline config and private-library installation checks; no system services."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('trial', Path(__file__).with_name('trial.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


generator_spec = importlib.util.spec_from_file_location('generator', Path(__file__).parent / 'sensors/generator.py')
generator = importlib.util.module_from_spec(generator_spec)
generator_spec.loader.exec_module(generator)


class SensorStaging(unittest.TestCase):
    def test_proxy_dependency_is_generated_only_on_opted_in_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generator.generate(root, 'spx_boot=known-good spx_sensors=0')
            self.assertEqual(list(root.iterdir()), [])
            generator.generate(root, 'spx_boot=mainline-functional spx_sensors=1')
            self.assertIn('BindsTo=spx-sensors.service', (root / 'iio-sensor-proxy.service.d/50-spx-sensors.conf').read_text())

    def inputs(self, root):
        config = root / 'input'
        (config / 'socinfo').mkdir(parents=True)
        for key, value in dict(soc_id='340', hw_platform='CLS', revision='3.1',
                              platform_version='65536', platform_subtype_id='0',
                              platform_subtype='Unknown').items():
            (config / 'socinfo' / key).write_text(value + '\n')
        (config / 'sensors/config').mkdir(parents=True)
        (config / 'sensors/config/8180_cls_lsm6dso_display.json').write_text('{}')
        (config / 'sensors/registry').mkdir()
        binaries = []
        for name in ('daemon', 'library', 'ready'):
            path = root / name
            path.write_bytes(name.encode())
            path.chmod(0o755)
            binaries.append(path)
        return SimpleNamespace(sensors_config=config, sensors_daemon=binaries[0],
                               sensors_library=binaries[1], sensors_ready=binaries[2])

    def test_private_runpath_layout_and_durable_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.inputs(root)
            out = root / 'stage'
            out.mkdir()
            trial.stage_sensors(args, out)
            destination = root / 'install'
            trial.install_sensors(out / 'sensors', destination)
            private = destination / trial.SENSORS_LIBEXEC.relative_to('/')
            self.assertEqual((private / 'hexagonrpcd/hexagonrpcd').read_bytes(), b'daemon')
            self.assertEqual((private / 'hexagonrpcd/../libhexagonrpc/libhexagonrpc.so.0.5').read_bytes(), b'library')
            self.assertEqual((destination / trial.SENSORS_ROOT.relative_to('/') / 'socinfo/soc_id').read_text().strip(), '340')
            self.assertEqual((destination / 'etc/udev/rules.d/81-spx-sensors.rules').read_text().count('ssc-accel'), 1)
            self.assertIn('spx_sensors=1', (destination / 'etc/systemd/system/spx-sensors.service').read_text())
            self.assertEqual((private / 'ready').stat().st_mode & 0o777, 0o755)
            self.assertFalse((destination / 'etc/systemd/system/iio-sensor-proxy.service.d').exists())
            self.assertEqual((destination / 'usr/lib/systemd/system-generators/spx-sensors').stat().st_mode & 0o777, 0o755)

    def test_wrong_board_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.inputs(root)
            (args.sensors_config / 'socinfo/soc_id').write_text('321')
            with self.assertRaises(AssertionError):
                trial.stage_sensors(args, root)

    def test_external_config_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.inputs(root)
            (args.sensors_config / 'sensors/registry/external').symlink_to(root / 'daemon')
            with self.assertRaises(AssertionError):
                trial.stage_sensors(args, root)


if __name__ == '__main__':
    unittest.main()
