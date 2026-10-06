#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Order the desktop proxy only on explicitly opted-in sensor boots."""
from pathlib import Path
import sys


PRIVATE_SSC = '/usr/local/libexec/spx-sensors/libssc'


def generate(output, cmdline):
    if 'spx_sensors=1' not in cmdline.split():
        return
    directory = output / 'iio-sensor-proxy.service.d'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '50-spx-sensors.conf').write_text(
        '[Unit]\nRequires=spx-sensors.service\nAfter=spx-sensors.service\n'
        'BindsTo=spx-sensors.service\n')
    if 'spx_sensors_libssc=private' in cmdline.split():
        for unit in ('spx-sensors.service', 'iio-sensor-proxy.service'):
            override = output / (unit + '.d')
            override.mkdir(parents=True, exist_ok=True)
            (override / '60-spx-libssc.conf').write_text(
                '[Service]\nEnvironment=LD_LIBRARY_PATH=' + PRIVATE_SSC + '\n' +
                ('Environment=G_MESSAGES_DEBUG=all\n'
                 if unit == 'iio-sensor-proxy.service' and
                 'spx_sensors_recovery=1' in cmdline.split() and
                 'spx_sensors_close_debug=1' in cmdline.split() else ''))


if __name__ == '__main__':
    generate(Path(sys.argv[1]), Path('/proc/cmdline').read_text())
