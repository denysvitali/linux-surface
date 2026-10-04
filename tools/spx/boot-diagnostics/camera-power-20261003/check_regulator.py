#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual regulator getter/init functions with injected bus failures."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def block(source, marker):
    start = source.index(marker)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + (';' if marker.startswith(('enum ', 'struct ')) else '')


STUBS = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char u8;
struct spmi_regulator {
    enum spmi_regulator_logical_type logical_type;
    struct spmi_voltage_set_points *set_points;
};
struct regulator_dev { struct spmi_regulator *vreg; };
static struct spmi_regulator *rdev_get_drvdata(struct regulator_dev *r) { return r->vreg; }
static u8 hardware[256];
static int read_error, write_error, writes;
static int spmi_vreg_read(struct spmi_regulator *v, unsigned reg, u8 *buf, unsigned n) {
    (void)v;
    if (read_error) return read_error;
    assert(reg + n <= sizeof(hardware));
    memcpy(buf, hardware + reg, n);
    return 0;
}
static int spmi_vreg_write(struct spmi_regulator *v, unsigned reg, u8 *buf, unsigned n) {
    (void)v;
    assert(reg + n <= sizeof(hardware));
    writes++;
    if (write_error) return write_error;
    memcpy(hardware + reg, buf, n);
    return 0;
}
static int spmi_vreg_update_bits(struct spmi_regulator *v, unsigned reg, u8 val, u8 mask) {
    u8 next = (hardware[reg] & ~mask) | (val & mask);
    return spmi_vreg_write(v, reg, &next, 1);
}
'''

TESTS = r'''
int main(void) {
    struct spmi_voltage_range ranges[] = {
        {.set_point_min_uV=320000, .set_point_max_uV=1304000, .step_uV=8000},
        {.set_point_min_uV=1504000, .set_point_max_uV=2000000, .step_uV=8000},
        {.set_point_min_uV=1504000, .set_point_max_uV=3544000, .step_uV=8000},
    };
    struct spmi_voltage_set_points points = {.range=&ranges[0], .count=1};
    struct spmi_regulator v = {.logical_type=SPMI_REGULATOR_LOGICAL_TYPE_LDO_510,
                              .set_points=&points};
    struct regulator_dev r = {.vreg=&v};
    int checked = 0;
    for (unsigned n = 0; n < sizeof(ranges)/sizeof(ranges[0]); n++) {
        points.range = &ranges[n];
        for (int code = 0; code <= 65535; code++) {
            hardware[0x40] = code & 255;
            hardware[0x41] = code >> 8;
            int voltage = code * 1000;
            int expected = -EINVAL;
            if (voltage >= ranges[n].set_point_min_uV && voltage <= ranges[n].set_point_max_uV &&
                (voltage - ranges[n].set_point_min_uV) % ranges[n].step_uV == 0)
                expected = (voltage - ranges[n].set_point_min_uV)/ranges[n].step_uV;
            assert(spmi_regulator_ftsmps426_get_voltage(&r) == expected);
            checked++;
        }
    }
    const int errors[] = {-EIO, -ETIMEDOUT, -ENODEV};
    for (unsigned n = 0; n < sizeof(errors)/sizeof(errors[0]); n++) {
        read_error = errors[n];
        assert(spmi_regulator_ftsmps426_get_voltage(&r) == read_error);
    }
    read_error = 0;
    struct spmi_regulator_init_data defaults = {
        .pin_ctrl_enable=SPMI_REGULATOR_PIN_CTRL_ENABLE_HW_DEFAULT,
        .pin_ctrl_hpm=SPMI_REGULATOR_PIN_CTRL_HPM_HW_DEFAULT,
        .vs_soft_start_strength=SPMI_VS_SOFT_START_STR_HW_DEFAULT,
    };
    for (unsigned i = 0; i < sizeof(hardware); i++) hardware[i] = i;
    u8 saved[256]; memcpy(saved, hardware, sizeof(saved));
    assert(spmi_regulator_init_registers(&v, &defaults) == 0);
    assert(writes == 0 && memcmp(saved, hardware, sizeof(saved)) == 0);
    struct spmi_regulator_init_data pins = defaults;
    pins.pin_ctrl_enable = 0; pins.pin_ctrl_hpm = 0;
    v.logical_type = SPMI_REGULATOR_LOGICAL_TYPE_LDO;
    hardware[0x45]=0x7f; hardware[0x46]=0xab;
    memcpy(saved, hardware, sizeof(saved));
    assert(spmi_regulator_init_registers(&v, &pins) == 0);
    assert(writes == 1 && hardware[0x45] == 0x60 && hardware[0x46] == 0xa0);
    saved[0x45]=0x60; saved[0x46]=0xa0;
    assert(memcmp(saved, hardware, sizeof(saved)) == 0);
    writes = 0;
    assert(spmi_regulator_init_registers(&v, &pins) == 0 && writes == 0);
    hardware[0x45]=0x7f; hardware[0x46]=0xab;
    write_error = -EIO;
    memcpy(saved, hardware, sizeof(saved));
    assert(spmi_regulator_init_registers(&v, &pins) == -EIO);
    assert(writes == 1 && memcmp(saved, hardware, sizeof(saved)) == 0);
    write_error=0; read_error=-ETIMEDOUT; writes=0;
    assert(spmi_regulator_init_registers(&v, &pins) == -ETIMEDOUT && writes == 0);
    read_error=0; v.logical_type=SPMI_REGULATOR_LOGICAL_TYPE_VS;
    pins=defaults; pins.vs_soft_start_strength=1;
    hardware[0x4c]=0xbc;
    memcpy(saved, hardware, sizeof(saved));
    assert(spmi_regulator_init_registers(&v, &pins) == 0);
    assert(writes == 1 && hardware[0x4c] == 0xbd);
    saved[0x4c]=0xbd;
    assert(memcmp(saved, hardware, sizeof(saved)) == 0);
    printf("PASS %d voltage codes, 3 read failures, default/no-op writes, legacy pin changes, read/write failures, VS soft start\n", checked);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text()
    data = '\n'.join(block(source, marker) for marker in (
        'enum spmi_regulator_logical_type', 'enum spmi_vs_soft_start_str',
        'enum spmi_common_regulator_registers',
        'enum spmi_ftsmps426_regulator_registers', 'enum spmi_vs_registers',
        'enum spmi_common_control_register_index', 'struct spmi_voltage_range {',
        'struct spmi_voltage_set_points {', 'struct spmi_regulator_init_data {'))
    constants = '\n'.join(re.findall(
        r'^#define SPMI_(?:REGULATOR_PIN_CTRL_[A-Z0-9_]+|COMMON_(?:ENABLE|MODE)_FOLLOW_[A-Z0-9_]+|VS_[A-Z0-9_]+)\s+[^\n]+',
        source, flags=re.M))
    functions = '\n'.join(block(source, marker) for marker in (
        'static int spmi_regulator_ftsmps426_get_voltage',
        'static int spmi_regulator_init_registers'))
    harness = args.work / 'harness.c'
    # u8 is needed by any source declarations before the stub section.
    harness.write_text('#include <stddef.h>\n#include <stdbool.h>\ntypedef unsigned char u8;\n' +
                       data + '\n' + constants + '\n' + STUBS + '\n' + functions + '\n' + TESTS)
    command = ['gcc', '-Wall', '-Wextra', '-Werror', '-std=gnu11', '-O1', '-g',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               str(harness), '-o', str(args.work / 'harness')]
    compiled = subprocess.run(command, capture_output=True, text=True)
    (args.work / 'compile.log').write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(args.work / 'harness')], capture_output=True, text=True)
    state = {'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
             'command': command, 'returncode': result.returncode,
             'stdout': result.stdout, 'stderr': result.stderr,
             'limits': 'Bus calls are stubs; electrical behavior, regulator core and actual writes untested.'}
    (args.work / 'result.json').write_text(json.dumps(state, indent=2) + '\n')
    print(result.stdout + result.stderr, end='')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
