#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fault-inject actual OV13858 stream cleanup and the V4L2 privacy wrapper."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('lifecycle', Path(__file__).with_name('check_rear_lifecycle.py'))
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

ADDITIONS = r'''
#define WARN_ON(v) (v)
#define dev_warn(...) (warnings++)
static int pm_refs, fail_resume, start_error, stop_error, suspend_block;
static bool privacy_on, require_quiet;
static int ov13858_runtime_resume(struct device *dev);
static int ov13858_runtime_suspend(struct device *dev);
static int monitored_stream(struct v4l2_subdev *sd, int enable);
static const struct v4l2_subdev_video_ops video_ops={.s_stream=monitored_stream};
static const struct v4l2_subdev_ops subdev_ops={.video=&video_ops};
static int pm_runtime_resume_and_get(struct device *d) {
    event(61);
    if(fail_resume) return fail_resume;
    int ret=ov13858_runtime_resume(d);
    if(ret) return ret;
    pm_refs++;
    return 0;
}
static int pm_runtime_get_if_in_use(struct device *d) {
    event(60);
    if(!d->client->sd->owner->powered) return 0;
    pm_refs++;
    return 1;
}
static void pm_runtime_put(struct device *d) {
    (void)d; event(62); assert(pm_refs>0); pm_refs--;
}
static int pm_runtime_put_sync_suspend(struct device *d) {
    event(69); assert(pm_refs>0); pm_refs--;
    /* __pm_runtime_suspend returns 0 after decrement when another user remains. */
    if(pm_refs) return 0;
    if(suspend_block) return -EACCES;
    return ov13858_runtime_suspend(d);
}
static int ov13858_start_streaming(struct ov13858 *s) {
    assert(s->powered && s->reset_gpio->value==0); event(66); return start_error;
}
static int ov13858_stop_streaming(struct ov13858 *s) {
    assert(s->powered && s->reset_gpio->value==0); event(67); return stop_error;
}
static int v4l2_subdev_enable_privacy_led(struct v4l2_subdev *sd) {
    (void)sd; event(70); privacy_on=true; return 0;
}
static void v4l2_subdev_disable_privacy_led(struct v4l2_subdev *sd) {
    /* Assert before LED release, using the actual V4L2 wrapper. */
    if(require_quiet) assert(!sd->owner->powered || sd->owner->reset_gpio->value==1);
    event(71); privacy_on=false;
}
'''

TESTS = r'''
static int last_stream_result;
static int monitored_stream(struct v4l2_subdev *sd,int enable) {
    last_stream_result=ov13858_set_stream(sd,enable);
    return last_stream_result;
}
static void stream_init(struct fixture *f,int peer) {
    init(f,peer); pm_refs=fail_resume=start_error=stop_error=suspend_block=0;
    privacy_on=require_quiet=false; last_stream_result=0;
    f->sensor.sd.ops=&subdev_ops; f->sensor.sd.dev=&f->dev;
    assert(call_s_stream(&f->sensor.sd,1)==0);
    assert(f->sensor.sd.s_stream_enabled && privacy_on && pm_refs==1);
    assert(f->sensor.powered && f->reset.value==0 && f->clk.refs==1);
    count=0;
}
static void gated(struct fixture *f,int error) {
    count=0;
    assert(ov13858_runtime_resume(&f->dev)==error && count==0);
    assert(ov13858_set_ctrl(&f->ctrl)==error && count==0);
    assert(call_s_stream(&f->sensor.sd,1)==error && count==4);
    assert(events[0]==70 && events[1]==51 && events[2]==52 && events[3]==71);
    assert(!privacy_on && pm_refs>=0);
    count=0;
}
int main(void) {
    struct fixture f;
#ifdef BASELINE
    stream_init(&f,0); stop_error=-EREMOTEIO; require_quiet=true;
    /* The original standby error reaches LED-off while reset is released. */
    puts("Checking failed standby cannot release privacy LED while reset is deasserted");
    fflush(stdout);
    call_s_stream(&f.sensor.sd,0);
    return 0;
#else
    lifecycle_main();
    int stream_cases=0;
    for(int peer=0;peer<2;peer++) {
        stream_init(&f,peer);
        assert(call_s_stream(&f.sensor.sd,0)==0 && last_stream_result==0);
        assert(!privacy_on && !f.sensor.sd.s_stream_enabled && pm_refs==0);
        assert(f.sensor.powered && f.reset.value==0);
        assert(ov13858_runtime_suspend(&f.dev)==0);
        for(int i=0;i<3;i++) assert(f.rails[i].refs==peer);
        stream_cases++;
        /* Standby errors: immediate cleanup, PM-forbidden and another PM user. */
        for(int mode=0;mode<3;mode++) {
            stream_init(&f,peer); stop_error=-EREMOTEIO; require_quiet=true;
            suspend_block=mode==1; if(mode==2) pm_refs++;
            assert(call_s_stream(&f.sensor.sd,0)==0); /* Actual V4L2 hides stop error. */
            assert(last_stream_result==-EREMOTEIO && !privacy_on && f.reset.value==1);
            assert(!f.sensor.sd.s_stream_enabled && pm_refs==(mode==2));
            if(mode) {
                assert(f.sensor.powered && f.sensor.stream_error==-EREMOTEIO && f.clk.refs==1);
                gated(&f,-EREMOTEIO);
                suspend_block=0;
                if(mode==2) assert(pm_runtime_put_sync_suspend(&f.dev)==0);
                else assert(ov13858_runtime_suspend(&f.dev)==0);
            }
            assert(!f.sensor.powered && !f.sensor.stream_error && f.clk.refs==0);
            stop_error=0; count=0; require_quiet=false;
            assert(call_s_stream(&f.sensor.sd,1)==0 && privacy_on && pm_refs==1);
            assert(call_s_stream(&f.sensor.sd,0)==0 && pm_refs==0);
            assert(ov13858_runtime_suspend(&f.dev)==0);
            for(int i=0;i<3;i++) assert(f.rails[i].refs==peer);
            stream_cases++;
        }
        /* All rail-disable points, including vote release and restore failure. */
        for(int fault=0;fault<3;fault++) for(int consumes=0;consumes<2;consumes++)
        for(int restore=-1;restore<3;restore++) {
            stream_init(&f,peer); stop_error=-EREMOTEIO; require_quiet=true;
            fail_disable=fault; consume_on_error=consumes; fail_restore=restore;
            assert(call_s_stream(&f.sensor.sd,0)==0 && last_stream_result==-EREMOTEIO);
            assert(!privacy_on && pm_refs==0 && f.reset.value==1 && f.clk.refs==0);
            assert(!f.sensor.powered && f.sensor.power_error==-EIO);
            gated(&f,-EIO); stream_cases++;
        }
        /* Start errors cannot leave a partially started sensor active. */
        for(int mode=0;mode<3;mode++) {
            init(&f,peer); f.sensor.sd.ops=&subdev_ops; f.sensor.sd.dev=&f.dev;
            pm_refs=fail_resume=stop_error=0; start_error=-ENXIO;
            suspend_block=mode==1; if(mode==2) pm_refs=1;
            privacy_on=require_quiet=false; count=0;
            assert(call_s_stream(&f.sensor.sd,1)==-ENXIO);
            assert(!privacy_on && !f.sensor.sd.s_stream_enabled && f.reset.value==1);
            assert(pm_refs==(mode==2));
            if(mode) {
                assert(f.sensor.stream_error==-ENXIO && f.sensor.powered);
                gated(&f,-ENXIO); suspend_block=0;
                if(mode==2) assert(pm_runtime_put_sync_suspend(&f.dev)==0);
                else assert(ov13858_runtime_suspend(&f.dev)==0);
            }
            assert(!f.sensor.stream_error && !f.sensor.powered && f.clk.refs==0);
            start_error=0; count=0;
            assert(call_s_stream(&f.sensor.sd,1)==0);
            assert(call_s_stream(&f.sensor.sd,0)==0);
            assert(ov13858_runtime_suspend(&f.dev)==0);
            stream_cases++;
        }
        init(&f,peer); f.sensor.sd.ops=&subdev_ops; f.sensor.sd.dev=&f.dev;
        pm_refs=0; fail_resume=-ETIMEDOUT; count=0;
        assert(call_s_stream(&f.sensor.sd,1)==-ETIMEDOUT && pm_refs==0);
        assert(count==5 && events[0]==70 && events[1]==51 && events[2]==61);
        assert(events[3]==52 && events[4]==71);
        stream_cases++;
        /* Quiesce still drains a quarantined stream with PM forbidden. */
        stream_init(&f,peer); stop_error=-EREMOTEIO; suspend_block=1; require_quiet=true;
        call_s_stream(&f.sensor.sd,0); count=0;
        ov13858_shutdown(&f.client);
        assert(f.sensor.shutting_down && !f.sensor.powered && !f.sensor.stream_error);
        assert(f.reset.value==1 && f.clk.refs==0); stream_cases++;
    }
    /* Legacy firmware-managed stop retains its PM path and surfaces the write error. */
    stream_init(&f,0); f.sensor.manages_power=false; stop_error=-EREMOTEIO;
    assert(ov13858_set_stream(&f.sensor.sd,0)==-EREMOTEIO);
    assert(pm_refs==0 && !f.sensor.stream_error && f.reset.value==0);
    stream_cases++;
    printf("PASS %d stream cases: standby/start faults, privacy release ordering, PM blocks/peers, rail cleanup faults, quarantine/restart/shutdown\n",stream_cases);
    return 0;
#endif
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('work', type=Path)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    args.work.mkdir(mode=0o700)
    source = args.source.read_text()
    core = Path('drivers/regulator/core.c').read_text()
    wrapper = Path('drivers/media/v4l2-core/v4l2-subdev.c').read_text()
    stubs = old.STUBS.replace('int power_error;', 'int power_error, stream_error;')
    replacement = ('struct v4l2_subdev;\n'
                   'struct v4l2_subdev_video_ops { int (*s_stream)(struct v4l2_subdev *, int); };\n'
                   'struct v4l2_subdev_ops { const struct v4l2_subdev_video_ops *video; };\n'
                   'struct v4l2_subdev { struct ov13858 *owner; struct device *dev; '
                   'const struct v4l2_subdev_ops *ops; bool s_stream_enabled; };')
    assert stubs.count('struct v4l2_subdev { struct ov13858 *owner; };') == 1
    stubs = stubs.replace('struct v4l2_subdev { struct ov13858 *owner; };', replacement)
    for name in ('pm_runtime_get_if_in_use', 'pm_runtime_resume_and_get', 'pm_runtime_put', 'pm_runtime_put_sync_suspend',
                 'ov13858_start_streaming', 'ov13858_stop_streaming'):
        stubs = stubs.replace(old.function(stubs, name), '')
    names = ['ov13858_power_on', 'ov13858_power_off', 'ov13858_runtime_resume',
             'ov13858_runtime_suspend', 'ov13858_set_ctrl']
    if not args.baseline:
        names.append('ov13858_stream_failure')
    names += ['ov13858_set_stream', 'ov13858_quiesce', 'ov13858_shutdown']
    regression = old.TESTS.replace('int main(void)', 'int lifecycle_main(void)', 1)
    end = regression.rfind('}')
    regression = regression[:end] + 'return 0;\n' + regression[end:]
    harness = args.work / 'stream-failure.c'
    harness.write_text(stubs + ADDITIONS + old.function(core, 'regulator_bulk_disable') + '\n' +
                       '\n'.join(old.function(source, name) for name in names) + '\n' +
                       old.function(wrapper, 'call_s_stream') + '\n' + regression + TESTS)
    command = ['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
               '-Wno-unused-function', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer'] + (['-DBASELINE'] if args.baseline else []) + \
              [str(harness), '-o', str(args.work / 'stream-failure')]
    compile_result = subprocess.run(command, capture_output=True, text=True)
    result = subprocess.run([str(args.work / 'stream-failure')], capture_output=True, text=True) \
        if not compile_result.returncode else None
    report = dict(source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  wrapper_sha256=hashlib.sha256(wrapper.encode()).hexdigest(),
                  regulator_core_sha256=hashlib.sha256(core.encode()).hexdigest(),
                  command=command, compile_returncode=compile_result.returncode,
                  compile_stdout=compile_result.stdout, compile_stderr=compile_result.stderr,
                  baseline=args.baseline, returncode=result.returncode if result else None,
                  stdout=result.stdout if result else '', stderr=result.stderr if result else '',
                  limits=['Actual sensor, regulator bulk-disable and V4L2 wrapper extracted; PM/GPIO/clock/I2C mocked',
                          'PM blocked/peer cases verify reset and quarantine, not electrical reset success',
                          'SPX configured reset required for failed-stop privacy ordering; optional-reset boards need their own validation',
                          'Current wrapper enables LED before start; physical onset timing remains untested',
                          'No kernel concurrency, capture or physical privacy acceptance'])
    (args.work / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(compile_result.stderr + report['stdout'] + report['stderr'], end='')
    if args.baseline:
        assert not compile_result.returncode and result.returncode != 0
        assert 'sd->owner->reset_gpio->value==1' in result.stderr
        print('PASS: original source reproduces failed-standby privacy ordering defect')
    else:
        assert not compile_result.returncode and result.returncode == 0


if __name__ == '__main__':
    main()
