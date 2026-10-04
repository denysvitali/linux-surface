#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent exact AR config review; inactive Kconfig menu lines are ignored."""
import json

EXPECTED = {
    'CONFIG_LOCALVERSION': ('"-spx-mainline-20261001am"', '"-spx-mainline-20261003ar"'),
    'CONFIG_I2C_QCOM_CCI': ('n', 'm'), 'CONFIG_VIDEO_DEV': ('n', 'm'),
    'CONFIG_VIDEO_V4L2_I2C': ('n', 'y'), 'CONFIG_VIDEO_V4L2_SUBDEV_API': ('n', 'y'),
    'CONFIG_V4L2_ASYNC': ('n', 'm'), 'CONFIG_V4L2_FWNODE': ('n', 'm'),
    'CONFIG_VIDEO_CAMERA_SENSOR': ('n', 'y'), 'CONFIG_VIDEO_OV13858': ('n', 'm'),
}


def states(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_'))


def verify_config(before_path, after_path, delta_path):
    before, after = states(before_path), states(after_path)
    delta = {name: {'before': before.get(name, 'n'), 'after': after.get(name, 'n')}
             for name in sorted(set(before) | set(after))
             if before.get(name, 'n') != after.get(name, 'n')}
    assert delta == {name: dict(zip(('before', 'after'), values)) for name, values in EXPECTED.items()}, delta
    assert delta == json.loads(delta_path.read_text())
    return delta
