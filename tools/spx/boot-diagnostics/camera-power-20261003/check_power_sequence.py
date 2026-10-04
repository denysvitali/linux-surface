#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fault-inject actual OV13858 power functions; never operate hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

STUBS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
struct regulator { int id, refs; };
struct regulator_bulk_data { struct regulator *consumer; };
struct clk { int refs; };
struct gpio_desc { int value; };
struct ov13858 {
    struct clk *clk;
    struct gpio_desc *reset_gpio;
    struct regulator_bulk_data supplies[3];
    bool manages_power, powered;
};
static int fail_rail, fail_clock, events[64], count;
static void event(int val) { assert(count < 64); events[count++] = val; }
static int regulator_enable(struct regulator *r) {
    event(10 + r->id);
    if (fail_rail == r->id) return -EIO;
    r->refs++;
    return 0;
}
static int regulator_disable(struct regulator *r) {
    event(20 + r->id);
    assert(r->refs > 0);
    r->refs--;
    return 0;
}
static int regulator_bulk_enable(int n, struct regulator_bulk_data *s) {
    /* Reverse completion is a valid asynchronous bulk-enable schedule. */
    int rc, i;
    for (i = n - 1; i >= 0; i--) {
        rc = regulator_enable(s[i].consumer);
        if (rc) {
            for (++i; i < n; i++) regulator_disable(s[i].consumer);
            return rc;
        }
    }
    return 0;
}
static int regulator_bulk_disable(int n, struct regulator_bulk_data *s) {
    while (n--) regulator_disable(s[n].consumer);
    return 0;
}
static int clk_prepare_enable(struct clk *c) {
    event(30);
    if (fail_clock) return -EBUSY;
    c->refs++;
    return 0;
}
static void clk_disable_unprepare(struct clk *c) {
    event(31);
    assert(c->refs == 1);
    c->refs--;
}
static void gpiod_set_value_cansleep(struct gpio_desc *g, int val) {
    event(40 + val);
    g->value = val;
}
static void usleep_range(int lo, int hi) { assert(lo > 0 && hi >= lo); }
'''

TEST = r'''
static void expect(const int *wanted, int n) {
    assert(count == n);
    for (int i = 0; i < n; i++) assert(events[i] == wanted[i]);
}
int main(void) {
    int cases = 0;
    for (int peer = 0; peer <= 1; peer++) {
        for (int fault = -1; fault <= 3; fault++) {
            struct regulator rails[3] = {{0, peer}, {1, peer}, {2, peer}};
            struct clk clk = {0};
            struct gpio_desc reset = {1};
            struct ov13858 sensor = {.clk = &clk, .reset_gpio = &reset,
                .manages_power = true, .supplies = {{&rails[0]}, {&rails[1]}, {&rails[2]}}};
            fail_rail = fault < 3 ? fault : -1;
            fail_clock = fault == 3;
            count = 0;
            int rc = ov13858_power_on(&sensor);
            if (fault >= 0) {
                assert(rc == (fault == 3 ? -EBUSY : -EIO));
                assert(!sensor.powered && reset.value == 1 && clk.refs == 0);
                for (int i = 0; i < 3; i++) assert(rails[i].refs == peer);
                int wanted[8], n = 0;
                for (int i = 0; i <= fault && i < 3; i++) wanted[n++] = 10 + i;
                if (fault == 3) wanted[n++] = 30;
                for (int i = (fault == 3 ? 2 : fault - 1); i >= 0; i--)
                    wanted[n++] = 20 + i;
                expect(wanted, n);
                count = 0;
                ov13858_power_off(&sensor);
                assert(count == 0);
                fail_rail = -1;
                fail_clock = 0;
                assert(ov13858_power_on(&sensor) == 0);
            }
            const int on[] = {10, 11, 12, 30, 40};
            expect(on, ARRAY_SIZE(on));
            assert(sensor.powered && reset.value == 0 && clk.refs == 1);
            for (int i = 0; i < 3; i++) assert(rails[i].refs == peer + 1);
            count = 0;
            assert(ov13858_power_on(&sensor) == 0);
            assert(count == 0);
            ov13858_power_off(&sensor);
            const int off[] = {41, 31, 22, 21, 20};
            expect(off, ARRAY_SIZE(off));
            assert(!sensor.powered && reset.value == 1 && clk.refs == 0);
            for (int i = 0; i < 3; i++) assert(rails[i].refs == peer);
            count = 0;
            ov13858_power_off(&sensor);
            assert(count == 0);
            cases++;
        }
    }
    struct ov13858 unmanaged = {0};
    count = 0;
    assert(ov13858_power_on(&unmanaged) == 0);
    ov13858_power_off(&unmanaged);
    assert(count == 0);
    printf("PASS %d cases: ordered rails, each enable/clock failure, retry, peer refs, idempotence, unmanaged path\n", cases + 1);
}
'''


def function(source, name):
    start = source.index('static ', source.index(name) - 20)
    brace = source.index('{', start)
    level = 1
    end = brace + 1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text()
    harness = args.work / 'power-harness.c'
    harness.write_text(STUBS + '\n' + function(source, 'ov13858_power_on') + '\n' +
                       function(source, 'ov13858_power_off') + '\n' + TEST)
    executable = args.work / 'power-harness'
    command = ['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-function', '-Wno-sign-compare', '-O1', '-g',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               str(harness), '-o', str(executable)]
    subprocess.run(command, check=True)
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    evidence = {'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
                'harness_sha256': hashlib.sha256(harness.read_bytes()).hexdigest(),
                'compile_command': command, 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr,
                'limits': 'Stubs model successful disables; real PMIC, disable failures and timing untested.'}
    (args.work / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(result.stdout + result.stderr, end='')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
