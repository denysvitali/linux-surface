#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Order the desktop proxy only on explicitly opted-in sensor boots."""
from pathlib import Path
import sys


def generate(output, cmdline):
    if 'spx_sensors=1' not in cmdline.split():
        return
    directory = output / 'iio-sensor-proxy.service.d'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '50-spx-sensors.conf').write_text(
        '[Unit]\nRequires=spx-sensors.service\nAfter=spx-sensors.service\n'
        'BindsTo=spx-sensors.service\n')


if __name__ == '__main__':
    generate(Path(sys.argv[1]), Path('/proc/cmdline').read_text())
