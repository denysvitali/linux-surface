#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual rear power/PM/shutdown functions with regulator fault injection."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

STUBS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define READ_ONCE(x) (x)
#define container_of(p,t,m) ((p)->owner)
#define ERR_PTR(e) ((void *)(long)(e))
#define pr_err(...) ((void)0)
#define dev_info(...) ((void)0)
#define dev_err(...) (warnings++)
#define to_ov13858(sd) ((sd)->owner)
#define to_i2c_client(d) ((d)->client)
#define i2c_get_clientdata(c) ((c)->sd)
typedef long long s64;
struct ov13858;
struct i2c_client;
struct device { struct i2c_client *client; };
struct v4l2_subdev { struct ov13858 *owner; };
struct i2c_client { struct v4l2_subdev *sd; };
struct regulator { int id, refs; };
struct regulator_bulk_data { struct regulator *consumer; const char *supply; };
struct clk { int refs; };
struct gpio_desc { int value; };
struct mutex { bool held; };
struct v4l2_ctrl_handler { struct ov13858 *owner; };
struct v4l2_ctrl { struct v4l2_ctrl_handler *handler; int id, val, minimum, step; };
struct mode { int height; };
struct ov13858 {
    struct device *dev;
    struct clk *clk;
    struct gpio_desc *reset_gpio;
    struct regulator_bulk_data supplies[3];
    bool manages_power, powered, shutting_down;
    int power_error, stream_error;
    struct mutex mutex;
    struct v4l2_ctrl_handler ctrl_handler;
    struct v4l2_ctrl *exposure;
    struct mode *cur_mode;
    struct v4l2_subdev sd;
};
enum { V4L2_CID_VBLANK, V4L2_CID_ANALOGUE_GAIN, V4L2_CID_DIGITAL_GAIN,
       V4L2_CID_EXPOSURE, V4L2_CID_TEST_PATTERN };
enum { OV13858_REG_ANALOG_GAIN, OV13858_REG_EXPOSURE, OV13858_REG_VTS,
       OV13858_REG_VALUE_16BIT, OV13858_REG_VALUE_24BIT };
static int fail_enable, fail_disable, fail_restore, consume_on_error, fail_clock;
static int events[128], count, warnings, cases;
static bool unwinding;
static void event(int n) { assert(count < 128); events[count++] = n; }
static int regulator_enable(struct regulator *r) {
    event(10 + r->id);
    if ((!unwinding && fail_enable == r->id) ||
        (unwinding && fail_restore == r->id)) return -EBUSY;
    r->refs++;
    return 0;
}
static int regulator_disable(struct regulator *r) {
    event(20 + r->id);
    assert(r->refs > 0);
    if (fail_disable == r->id) {
        if (consume_on_error) r->refs--;
        unwinding = true;
        return -EIO;
    }
    r->refs--;
    return 0;
}
static int clk_prepare_enable(struct clk *c) {
    event(30);
    if (fail_clock) return -ENXIO;
    assert(c->refs == 0);
    c->refs++;
    return 0;
}
static void clk_disable_unprepare(struct clk *c) {
    event(31); assert(c->refs == 1); c->refs--;
}
static void gpiod_set_value_cansleep(struct gpio_desc *g, int v) { event(40+v); g->value=v; }
static void usleep_range(int lo, int hi) { assert(lo>0 && hi>=lo); }
static void pm_runtime_disable(struct device *d) { (void)d; event(50); }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held=true; event(51); }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held=false; event(52); }
static int pm_runtime_get_if_in_use(struct device *d) { (void)d; event(60); return 1; }
static int pm_runtime_resume_and_get(struct device *d) { (void)d; event(61); return 0; }
static void pm_runtime_put(struct device *d) { (void)d; event(62); }
static int pm_runtime_put_sync_suspend(struct device *d) { (void)d; event(69); return 0; }
static int ov13858_write_reg(struct ov13858 *s,int a,int b,int c) {
    (void)s;(void)a;(void)b;(void)c;event(63);return 0;
}
static int ov13858_update_digital_gain(struct ov13858 *s,int v) { (void)s;(void)v;event(64);return 0; }
static int ov13858_enable_test_pattern(struct ov13858 *s,int v) { (void)s;(void)v;event(65);return 0; }
static int ov13858_start_streaming(struct ov13858 *s) { (void)s;event(66);return 0; }
static int ov13858_stop_streaming(struct ov13858 *s) { (void)s;event(67);return 0; }
static void __v4l2_ctrl_modify_range(struct v4l2_ctrl *c,int a,int b,int d,int e) {
    (void)c;(void)a;(void)b;(void)d;(void)e;event(68);
}
'''

TESTS = r'''
struct fixture {
    struct regulator rails[3]; struct clk clk; struct gpio_desc reset;
    struct ov13858 sensor; struct device dev; struct i2c_client client;
    struct v4l2_ctrl ctrl; struct mode mode;
};
static void init(struct fixture *f, int peer) {
    memset(f,0,sizeof(*f));
    f->sensor=(struct ov13858){.dev=&f->dev,.clk=&f->clk,.reset_gpio=&f->reset,.manages_power=true};
    for (int i=0;i<3;i++) {
        f->rails[i]=(struct regulator){i,peer};
        f->sensor.supplies[i]=(struct regulator_bulk_data){&f->rails[i],"rail"};
    }
    f->sensor.sd.owner=&f->sensor; f->client.sd=&f->sensor.sd; f->dev.client=&f->client;
    f->sensor.ctrl_handler.owner=&f->sensor;
    f->ctrl.handler=&f->sensor.ctrl_handler; f->ctrl.id=V4L2_CID_ANALOGUE_GAIN;
    f->sensor.exposure=&f->ctrl; f->sensor.cur_mode=&f->mode;
    f->reset.value=1;
    fail_enable=fail_disable=fail_restore=-1; fail_clock=consume_on_error=0;
    unwinding=false; count=warnings=0;
}
static void quarantined(struct fixture *f) {
    int refs[3]; for(int i=0;i<3;i++) refs[i]=f->rails[i].refs;
    assert(f->sensor.power_error == -EIO && !f->sensor.powered);
    assert(f->clk.refs==0 && f->reset.value==1);
    count=0; fail_enable=fail_disable=fail_restore=-1; unwinding=false;
    assert(ov13858_runtime_suspend(&f->dev)==-EIO);
    assert(ov13858_runtime_resume(&f->dev)==-EIO);
    assert(count==0);
#ifndef OLD
    assert(ov13858_set_ctrl(&f->ctrl)==-EIO && count==0);
    assert(ov13858_set_stream(&f->sensor.sd,0)==-EIO && count==2);
    assert(events[0]==51 && events[1]==52);
#endif
    for(int i=0;i<3;i++) assert(refs[i]==f->rails[i].refs);
}
int main(void) {
    struct fixture f;
    /* A suspend failure must not silently report success. */
    for (int peer=0;peer<2;peer++) for(int mode=0;mode<2;mode++)
    for(int fault=0;fault<3;fault++) for(int restore=-1;restore<3;restore++) {
        init(&f,peer); assert(ov13858_runtime_resume(&f.dev)==0);
        fail_disable=fault; consume_on_error=mode; fail_restore=restore;
        assert(ov13858_runtime_suspend(&f.dev)==-EIO);
        quarantined(&f); cases++;
    }
    /* Enable/clock failure with failed unwind retains the original error. */
    for(int peer=0;peer<2;peer++) for(int mode=0;mode<2;mode++)
    for(int fault=1;fault<=3;fault++) for(int disable=0;disable<fault;disable++)
    for(int restore=-1;restore<3;restore++) {
        init(&f,peer); fail_enable=fault<3?fault:-1; fail_clock=fault==3;
        fail_disable=disable; consume_on_error=mode; fail_restore=restore;
        assert(ov13858_runtime_resume(&f.dev)==(fault==3?-ENXIO:-EBUSY));
        quarantined(&f); cases++;
    }
    /* Successful cleanup permits a fresh, balanced retry, preserving peers. */
    for(int peer=0;peer<2;peer++) for(int fault=0;fault<=4;fault++) {
        init(&f,peer); fail_enable=fault<3?fault:-1; fail_clock=fault==3;
        int rc=ov13858_runtime_resume(&f.dev);
        if(fault<4) {
            assert(rc==(fault==3?-ENXIO:-EBUSY));
            assert(!f.sensor.power_error && !f.sensor.powered && f.clk.refs==0);
            for(int i=0;i<3;i++) assert(f.rails[i].refs==peer);
            fail_enable=-1; fail_clock=0; unwinding=false; count=0;
            assert(ov13858_runtime_resume(&f.dev)==0);
        } else assert(rc==0);
        assert(f.sensor.powered && f.clk.refs==1 && f.reset.value==0);
        const int on[]={10,11,12,30,40};
        assert(count==5 && !memcmp(events,on,sizeof(on)));
        int n=count; assert(ov13858_runtime_resume(&f.dev)==0 && count==n);
        assert(ov13858_runtime_suspend(&f.dev)==0);
        const int off[]={41,31,22,21,20};
        assert(count==10 && !memcmp(events+5,off,sizeof(off)));
        assert(!f.sensor.powered && f.clk.refs==0 && f.reset.value==1);
        for(int i=0;i<3;i++) assert(f.rails[i].refs==peer);
        n=count; assert(ov13858_runtime_suspend(&f.dev)==0 && count==n); cases++;
    }
#ifndef OLD
    for(int peer=0;peer<2;peer++) for(int active=0;active<2;active++)
    for(int fault=-1;fault<3;fault++) {
        init(&f,peer); if(active) assert(ov13858_runtime_resume(&f.dev)==0);
        fail_disable=fault; count=0;
        ov13858_shutdown(&f.client);
        assert(f.sensor.shutting_down && !f.sensor.powered);
        assert(f.clk.refs==0 && f.reset.value==1);
        assert(events[0]==50 && events[1]==51 && events[count-1]==52);
        count=0; ov13858_shutdown(&f.client); assert(count==0);
        assert(ov13858_set_ctrl(&f.ctrl)==-ESHUTDOWN && count==0);
        assert(ov13858_set_stream(&f.sensor.sd,1)==-ESHUTDOWN && count==2);
        assert(events[0]==51 && events[1]==52);
        assert(ov13858_set_stream(&f.sensor.sd,0)==-ESHUTDOWN && count==4);
        count=0; assert(ov13858_runtime_resume(&f.dev)==-ESHUTDOWN && count==0);
        cases++;
    }
    init(&f,0); f.sensor.manages_power=false;
    ov13858_shutdown(&f.client); assert(count==0 && !f.sensor.shutting_down);
    assert(ov13858_runtime_resume(&f.dev)==0 && ov13858_runtime_suspend(&f.dev)==0 && count==0);
    ov13858_quiesce(&f.sensor); assert(count==3 && f.sensor.shutting_down);
    count=0; ov13858_quiesce(&f.sensor); assert(count==0); cases++;
#endif
    printf("PASS %d cases: disable/restore faults, partial vote release, rollback, peer references, PM errors, shutdown/I/O gates\n",cases);
}
'''


def function(source, name):
    match = re.search(r'^(?:static )?(?:int|void)\s+' + name + r'\s*\(', source, re.M)
    assert match, name
    brace = source.index('{', match.end())
    level, end = 1, brace + 1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('work', type=Path)
    parser.add_argument('--old', action='store_true')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    source = args.source.read_text()
    core = Path('drivers/regulator/core.c').read_text()
    functions = ['ov13858_power_on', 'ov13858_power_off', 'ov13858_runtime_resume', 'ov13858_runtime_suspend']
    if not args.old:
        if 'static void ov13858_stream_failure(' in source:
            functions += ['ov13858_stream_failure']
        functions += ['ov13858_set_ctrl', 'ov13858_set_stream', 'ov13858_quiesce', 'ov13858_shutdown']
        assert '.shutdown = ov13858_shutdown,' in source
        removal = function(source, 'ov13858_remove')
        assert removal.index('ov13858_quiesce') < removal.index('ov13858_free_controls')
    harness = args.work / 'lifecycle.c'
    harness.write_text(STUBS + function(core, 'regulator_bulk_disable') + '\n' +
                       '\n'.join(function(source, name) for name in functions) + '\n' + TESTS)
    exe = args.work / 'lifecycle'
    command = ['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
               '-Wno-unused-function', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer'] + (['-DOLD'] if args.old else []) + [str(harness), '-o', str(exe)]
    subprocess.run(command, check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    report = {'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
              'core_sha256': hashlib.sha256(core.encode()).hexdigest(), 'compile_command': command,
              'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
              'limits': ['Actual sensor and bulk-disable functions extracted; APIs, clocks, GPIO and PM mocked.',
                         'Faults include disable errors before/after vote release and failed restore.',
                         'Not an exhaustive kernel concurrency or electrical ownership test.']}
    (args.work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result.stdout + result.stderr, end='')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
