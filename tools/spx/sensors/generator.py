#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Order the desktop proxy on sensor trials or explicitly enabled baselines."""
from pathlib import Path
import sys


PRIVATE_SSC = '/usr/local/libexec/spx-sensors/libssc'
BASELINE_CONFIG = Path('/etc/spx/sensors-enabled')


def generate(output, cmdline, baseline_config=None):
    words = cmdline.split()
    if 'spx_sensors=0' in words:
        return
    trial = 'spx_sensors=1' in words
    baseline = (any(word.startswith('spx_baseline=') for word in words) and
                baseline_config in ('system', 'private'))
    if not (trial or baseline):
        return
    if baseline and not trial:
        provider = output / 'spx-sensors.service.d'
        provider.mkdir(parents=True, exist_ok=True)
        (provider / '50-spx-baseline.conf').write_text(
            '[Unit]\nConditionKernelCommandLine=\nConditionKernelCommandLine=spx_baseline\n')
        wants = output / 'multi-user.target.wants'
        wants.mkdir(parents=True, exist_ok=True)
        (wants / 'spx-sensors.service').symlink_to('/etc/systemd/system/spx-sensors.service')
    directory = output / 'iio-sensor-proxy.service.d'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '50-spx-sensors.conf').write_text(
        '[Unit]\nRequires=spx-sensors.service\nAfter=spx-sensors.service\n'
        'BindsTo=spx-sensors.service\n')
    private = ('spx_sensors_libssc=private' in words if trial else
               baseline_config == 'private')
    if private:
        for unit in ('spx-sensors.service', 'iio-sensor-proxy.service'):
            override = output / (unit + '.d')
            override.mkdir(parents=True, exist_ok=True)
            (override / '60-spx-libssc.conf').write_text(
                '[Service]\nEnvironment=LD_LIBRARY_PATH=' + PRIVATE_SSC + '\n' +
                ('Environment=G_MESSAGES_DEBUG=all\n'
                 if unit == 'iio-sensor-proxy.service' and
                 'spx_sensors_recovery=1' in words and
                 'spx_sensors_close_debug=1' in words else ''))


if __name__ == '__main__':
    config = BASELINE_CONFIG.read_text().strip() if BASELINE_CONFIG.is_file() else None
    generate(Path(sys.argv[1]), Path('/proc/cmdline').read_text(), config)
