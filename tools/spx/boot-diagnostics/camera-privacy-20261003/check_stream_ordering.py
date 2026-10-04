#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual V4L2/LED/GPIO functions with modeled work and media state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[4]


def function(source, name):
    match = re.search(r'^(?:static )?(?:inline )?(?:int|void|bool)\s+' + re.escape(name) + r'\s*\(', source, re.M)
    assert match, name
    start = source.index('{', match.end())
    depth, end = 1, start+1
    while depth:
        depth += (source[end] == '{')-(source[end] == '}')
        end += 1
    return source[match.start():end]


STUBS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define ENOTSUPP 524
#define BIT_ULL(n) (1ULL << (n))
#define BITS_PER_BYTE 8
#define MEDIA_PAD_FL_SOURCE 1
#define V4L2_SUBDEV_FL_STREAMS 1
#define IS_REACHABLE(v) LED_REACHABLE
#define IS_ERR_OR_NULL(p) (!(p) || (uintptr_t)(p) >= (uintptr_t)-4095)
#define min(a,b) ((a)<(b)?(a):(b))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define dev_dbg(d,...) ((void)(d))
#define dev_warn(d,...) ((void)(d))
#define dev_err(d,...) ((void)(d))
#define WARN_ON(v) (!!(v))
#define smp_mb__before_atomic() ((void)0)
#define LED_SUSPENDED 1
#define LED_UNREGISTERING 2
#define LED_HW_PLUGGABLE 4
#define LED_BLINK_SW 0
#define LED_BLINK_BRIGHTNESS_CHANGE 4
#define LED_BLINK_DISABLE 5
#define LED_SET_BRIGHTNESS_OFF 6
#define LED_SET_BRIGHTNESS 7
#define LED_SET_BLINK 8
enum led_brightness { LED_OFF=0, LED_FULL=255 };
struct device { int unused; };
struct work_struct { bool pending; };
struct workqueue_struct { int unused; };
struct led_classdev {
    struct device *dev;
    unsigned int flags, brightness, max_brightness;
    unsigned long work_flags, blink_delay_on, blink_delay_off;
    unsigned long delayed_delay_on, delayed_delay_off;
    unsigned int delayed_set_value, new_blink_brightness;
    struct work_struct set_brightness_work;
    struct workqueue_struct *wq;
    void (*brightness_set)(struct led_classdev *,enum led_brightness);
    int (*brightness_set_blocking)(struct led_classdev *,enum led_brightness);
};
struct gpio_desc { int value; };
struct gpio_led_data {
    struct led_classdev cdev;
    struct gpio_desc *gpiod;
    bool can_sleep, blinking;
    int (*platform_gpio_blink_set)(struct gpio_desc *,int,unsigned long *,unsigned long *);
};
struct media_pad { unsigned int flags; };
struct media_device { struct device *dev; };
struct media_entity {
    unsigned int num_pads;
    struct media_pad *pads;
    const char *name;
    struct { struct media_device *mdev; } graph_obj;
};
struct v4l2_subdev_stream_config { u32 pad, stream; bool enabled; };
struct v4l2_subdev_state {
    struct { unsigned int num_configs; struct v4l2_subdev_stream_config *configs; } stream_configs;
    bool locked;
};
struct v4l2_subdev;
struct v4l2_subdev_pad_ops {
    int (*enable_streams)(struct v4l2_subdev *,struct v4l2_subdev_state *,u32,u64);
    int (*disable_streams)(struct v4l2_subdev *,struct v4l2_subdev_state *,u32,u64);
};
struct v4l2_subdev_video_ops { int (*s_stream)(struct v4l2_subdev *,int); };
struct v4l2_subdev_ops {
    const struct v4l2_subdev_pad_ops *pad;
    const struct v4l2_subdev_video_ops *video;
};
struct v4l2_subdev {
    struct device *dev;
    struct led_classdev *privacy_led;
    struct media_entity entity;
    const struct v4l2_subdev_ops *ops;
    unsigned int flags;
    u64 enabled_pads;
    bool s_stream_enabled;
    struct v4l2_subdev_state *state;
    u64 hardware[3];
};
static int events[256], count, cases, start_error, stop_error, led_on_error, led_off_error;
static int driver_starts, driver_stops, provider_on, provider_off;
static bool suspend_during_flush;
static void event(int e) { assert(count<256); events[count++]=e; }
static bool test_bit(unsigned int n,const unsigned long *p) { return !!(*p & (1UL<<n)); }
static void set_bit(unsigned int n,unsigned long *p) { *p |= 1UL<<n; }
static void clear_bit(unsigned int n,unsigned long *p) { *p &= ~(1UL<<n); }
static bool test_and_clear_bit(unsigned int n,unsigned long *p) {
    bool result=test_bit(n,p); clear_bit(n,p); return result;
}
static bool queue_work(struct workqueue_struct *q,struct work_struct *w) {
    (void)q; w->pending=true; return true;
}
static void set_brightness_delayed(struct work_struct *w);
static bool flush_work(struct work_struct *w) {
    bool pending=w->pending; event(1);
    if(pending) { w->pending=false; set_brightness_delayed(w); }
    if(suspend_during_flush) {
        container_of(w,struct led_classdev,set_brightness_work)->flags |= LED_SUSPENDED;
        suspend_during_flush=false;
    }
    return pending;
}
static void led_stop_software_blink(struct led_classdev *led) {
    led->blink_delay_on=led->blink_delay_off=0; clear_bit(LED_BLINK_SW,&led->work_flags);
}
static void led_blink_set(struct led_classdev *led,unsigned long *on,unsigned long *off) {
    led->blink_delay_on=*on; led->blink_delay_off=*off;
}
static struct gpio_led_data *cdev_to_gpio_led_data(struct led_classdev *led) {
    return container_of(led,struct gpio_led_data,cdev);
}
static void gpiod_set_value(struct gpio_desc *gpio,int value) {
    event(value?2:3); gpio->value=value;
    if(value) provider_on++; else provider_off++;
}
static void gpiod_set_value_cansleep(struct gpio_desc *gpio,int value) { gpiod_set_value(gpio,value); }
static int faulty_provider(struct led_classdev *led,enum led_brightness value) {
    struct gpio_led_data *data=cdev_to_gpio_led_data(led);
    /* Error can be reported after the hardware write, requiring rollback. */
    gpiod_set_value(data->gpiod,!!value);
    return value?led_on_error:led_off_error;
}
#define v4l2_subdev_has_op(sd,type,op) ((sd)->ops->type && (sd)->ops->type->op)
#define v4l2_subdev_call(sd,type,op,...) call_##type##_##op(sd,__VA_ARGS__)
static int call_s_stream(struct v4l2_subdev *sd,int enable);
static bool v4l2_subdev_is_streaming(struct v4l2_subdev *sd);
static int call_video_s_stream(struct v4l2_subdev *sd,int enable) { return call_s_stream(sd,enable); }
static int call_pad_enable_streams(struct v4l2_subdev *sd,struct v4l2_subdev_state *s,u32 p,u64 m) {
    return sd->ops->pad->enable_streams(sd,s,p,m);
}
static int call_pad_disable_streams(struct v4l2_subdev *sd,struct v4l2_subdev_state *s,u32 p,u64 m) {
    return sd->ops->pad->disable_streams(sd,s,p,m);
}
static struct v4l2_subdev_state *v4l2_subdev_lock_and_get_active_state(struct v4l2_subdev *sd) {
    assert(!sd->state->locked); sd->state->locked=true; return sd->state;
}
static struct v4l2_subdev_state *v4l2_subdev_get_locked_active_state(struct v4l2_subdev *sd) {
    assert(sd->state->locked); return sd->state;
}
static void v4l2_subdev_unlock_state(struct v4l2_subdev_state *s) { assert(s->locked); s->locked=false; }
static void check_light(struct v4l2_subdev *sd) {
    if(LED_REACHABLE && !IS_ERR_OR_NULL(sd->privacy_led))
        assert(cdev_to_gpio_led_data(sd->privacy_led)->gpiod->value==1);
}
static int mock_start(struct v4l2_subdev *sd,struct v4l2_subdev_state *s,u32 p,u64 m) {
    (void)s; check_light(sd); event(4); driver_starts++;
    if(start_error) return start_error;
    sd->hardware[p] |= m; return 0;
}
static int mock_stop(struct v4l2_subdev *sd,struct v4l2_subdev_state *s,u32 p,u64 m) {
    (void)s; event(5); driver_stops++;
    if(stop_error) return stop_error;
    sd->hardware[p] &= ~m; return 0;
}
static int mock_legacy(struct v4l2_subdev *sd,int enable) {
    if(enable) return mock_start(sd,NULL,0,1);
    /* Rear driver guarantees quiet before returning a negative stop error. */
    sd->hardware[0]=0; event(5); driver_stops++; return stop_error;
}
'''

TESTS = r'''
static const struct v4l2_subdev_pad_ops native_ops={mock_start,mock_stop};
static const struct v4l2_subdev_video_ops legacy_ops={mock_legacy};
static const struct v4l2_subdev_ops native={&native_ops,&legacy_ops}, legacy={NULL,&legacy_ops};
struct fixture {
    struct device dev;
    struct media_device media;
    struct media_pad pads[66];
    struct gpio_desc gpio;
    struct gpio_led_data led;
    struct v4l2_subdev sd;
    struct v4l2_subdev_state state;
    struct v4l2_subdev_stream_config configs[6];
};
static void init(struct fixture *f,int provider,int path) {
    memset(f,0,sizeof(*f));
    f->media.dev=&f->dev;
    for(int p=0;p<66;p++) f->pads[p].flags=MEDIA_PAD_FL_SOURCE;
    f->led.gpiod=&f->gpio; f->led.cdev.dev=&f->dev;
    f->led.cdev.max_brightness=1;
    f->led.can_sleep=provider!=0;
    if(provider==0) f->led.cdev.brightness_set=gpio_led_set;
    else if(provider==1) f->led.cdev.brightness_set_blocking=gpio_led_set_blocking;
    else if(provider==2) f->led.cdev.brightness_set_blocking=faulty_provider;
    f->state.stream_configs=(typeof(f->state.stream_configs)){6,f->configs};
    for(int i=0;i<6;i++) f->configs[i]=(struct v4l2_subdev_stream_config){i/2,i%2,false};
    f->sd.dev=&f->dev; f->sd.privacy_led=&f->led.cdev; f->sd.state=&f->state;
    f->sd.entity=(struct media_entity){3,f->pads,"test",{&f->media}};
    f->sd.ops=path?&native:&legacy;
    if(path==2) f->sd.flags=V4L2_SUBDEV_FL_STREAMS;
    start_error=stop_error=led_on_error=led_off_error=0;
    count=driver_starts=driver_stops=provider_on=provider_off=0;
    suspend_during_flush=false;
}
static void pump(struct fixture *f) { flush_work(&f->led.cdev.set_brightness_work); }
static int enable(struct fixture *f,int path,u32 pad,u64 mask) {
    int ret=path? v4l2_subdev_enable_streams(&f->sd,pad,mask):call_s_stream(&f->sd,1);
    assert(!f->state.locked); return ret;
}
static int disable(struct fixture *f,int path,u32 pad,u64 mask) {
    int ret=path? v4l2_subdev_disable_streams(&f->sd,pad,mask):call_s_stream(&f->sd,0);
    assert(!f->state.locked); return ret;
}
static bool streaming(struct fixture *f) {
    bool result;
    if(f->sd.flags & V4L2_SUBDEV_FL_STREAMS) f->state.locked=true;
    result=v4l2_subdev_is_streaming(&f->sd);
    f->state.locked=false; return result;
}
int main(void) {
    struct fixture f;
#if BASELINE_MODE
    init(&f,0,BASELINE_MODE==2?2:0);
    cases++;
    puts("Checking privacy LED is on before driver starts"); fflush(stdout);
    enable(&f,BASELINE_MODE==2?2:0,0,1);
    return 0;
#else
    for(int path=0;path<3;path++) for(int provider=0;provider<3;provider++) {
        init(&f,provider,path);
        assert(enable(&f,path,0,1)==0 && streaming(&f));
        assert(driver_starts==1 && f.sd.hardware[0]==1);
        assert(disable(&f,path,0,1)==0 && !streaming(&f));
        pump(&f); assert(f.gpio.value==0); cases++;
        for(int stale=0;stale<2;stale++) {
            init(&f,provider,path);
            if(stale) { f.gpio.value=1; led_set_brightness(&f.led.cdev,0); }
            assert(enable(&f,path,0,1)==0);
            pump(&f); if(LED_REACHABLE) assert(f.gpio.value==1);
            assert(disable(&f,path,0,1)==0); pump(&f); assert(f.gpio.value==0); cases++;
        }
        init(&f,provider,path); start_error=-EREMOTEIO;
        assert(enable(&f,path,0,1)==-EREMOTEIO && !streaming(&f));
        assert(driver_starts==1 && f.sd.hardware[0]==0);
        pump(&f); assert(f.gpio.value==0); cases++;
        if(LED_REACHABLE) {
            for(int condition=0;condition<5;condition++) {
                init(&f,provider,path);
                if(condition==0) f.led.cdev.flags=LED_SUSPENDED;
                if(condition==1) f.led.cdev.flags=LED_UNREGISTERING;
                if(condition==2) f.led.cdev.blink_delay_on=10;
                if(condition==3) f.led.cdev.blink_delay_off=10;
                if(condition==4) suspend_during_flush=true;
                assert(enable(&f,path,0,1)==(condition==2||condition==3?-EBUSY:-EAGAIN));
                assert(driver_starts==0 && !streaming(&f)); cases++;
            }
        }
        for(int absent=0;absent<2;absent++) {
            init(&f,provider,path);
            f.sd.privacy_led=absent?(void *)(intptr_t)-ENOENT:NULL;
            assert(enable(&f,path,0,1)==0 && streaming(&f));
            assert(provider_on==0 && driver_starts==1);
            assert(disable(&f,path,0,1)==0 && !streaming(&f)); cases++;
        }
        if(path) {
            init(&f,provider,path);
            assert(enable(&f,path,0,0)==0 && driver_starts==0 && provider_on==0);
            assert(enable(&f,path,3,1)==-EINVAL && provider_on==0);
            f.sd.entity.num_pads=65;
            assert(enable(&f,path,64,1)==-EOPNOTSUPP && provider_on==0);
            f.sd.entity.num_pads=3;
            assert(enable(&f,path,0,4)==-EINVAL && driver_starts==0 && provider_on==0);
            assert(enable(&f,path,0,1)==0);
            int on=provider_on, starts=driver_starts;
            assert(enable(&f,path,0,1)==-EALREADY && driver_starts==starts && provider_on==on);
            cases++;
            /* Failed additional stream must preserve every existing stream and light. */
            if(path==2) assert(enable(&f,path,0,2)==0);
            assert(enable(&f,path,1,1)==0);
            start_error=-EIO;
            assert(enable(&f,path,2,1)==-EIO && streaming(&f));
            if(LED_REACHABLE) assert(f.gpio.value==1 && provider_on==on);
            assert(f.sd.hardware[0]==(path==2?3:1) && f.sd.hardware[1]==1 && f.sd.hardware[2]==0);
            start_error=0; stop_error=-EIO;
            assert(disable(&f,path,0,1)==-EIO && streaming(&f));
            if(LED_REACHABLE) assert(f.gpio.value==1);
            stop_error=0;
            assert(disable(&f,path,0,1)==0 && streaming(&f));
            if(path==2) assert(disable(&f,path,0,2)==0 && streaming(&f));
            assert(disable(&f,path,1,1)==0 && !streaming(&f));
            pump(&f); assert(f.gpio.value==0); cases++;
        } else {
            init(&f,provider,0); assert(enable(&f,0,0,1)==0);
            int on=provider_on, starts=driver_starts;
            assert(enable(&f,0,0,1)==0 && provider_on==on && driver_starts==starts);
            stop_error=-EIO;
            assert(disable(&f,0,0,1)==0 && !streaming(&f));
            pump(&f); assert(f.gpio.value==0); cases++;
        }
    }
    if(LED_REACHABLE) {
        for(int path=0;path<3;path++) for(int fault=0;fault<3;fault++) {
            init(&f,2,path); led_on_error=fault==0?-EIO:fault==1?-ENODEV:-ENOTSUPP;
            assert(enable(&f,path,0,1)==led_on_error && !streaming(&f));
            assert(driver_starts==0);
            pump(&f); assert(f.gpio.value==0); cases++;
        }
        for(int path=0;path<3;path++) {
            init(&f,3,path); /* Provider has neither callback. */
            assert(enable(&f,path,0,1)==-ENOTSUPP && !streaming(&f));
            assert(driver_starts==0); cases++;
        }
    }
    /* .s_stream fallback tracks multiple pads but invokes one legacy start/stop. */
    for(int provider=0;provider<3;provider++) {
        init(&f,provider,0);
        assert(v4l2_subdev_enable_streams(&f.sd,0,1)==0);
        assert(v4l2_subdev_enable_streams(&f.sd,1,1)==0 && driver_starts==1);
        assert(v4l2_subdev_disable_streams(&f.sd,0,1)==0 && driver_stops==0);
        if(LED_REACHABLE) assert(f.gpio.value==1);
        assert(v4l2_subdev_disable_streams(&f.sd,1,1)==0 && driver_stops==1);
        pump(&f); assert(f.gpio.value==0); cases++;
    }
    printf("PASS %d privacy cases, LED_REACHABLE=%d: ordering/provider errors/pending work/rollback/legacy/native/multiple streams\n",cases,LED_REACHABLE);
    return 0;
#endif
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('work', type=Path)
    parser.add_argument('--baseline', choices=('legacy', 'native'))
    parser.add_argument('--leds-unreachable', action='store_true')
    args = parser.parse_args()
    args.work.mkdir(mode=0o700)
    source = args.source.read_text()
    led_source = (REPO / 'drivers/leds/led-core.c').read_text()
    gpio_source = (REPO / 'drivers/leds/leds-gpio.c').read_text()
    led_functions = ('__led_set_brightness', '__led_set_brightness_blocking',
                     'set_brightness_delayed_set_brightness', 'set_brightness_delayed',
                     'led_set_brightness_nopm', 'led_set_brightness_nosleep',
                     'led_set_brightness', 'led_set_brightness_sync')
    media_functions = ('v4l2_subdev_enable_privacy_led', 'v4l2_subdev_disable_privacy_led',
                       'call_s_stream', 'v4l2_subdev_collect_streams',
                       'v4l2_subdev_set_streams_enabled', 'v4l2_subdev_enable_streams',
                       'v4l2_subdev_disable_streams', 'v4l2_subdev_is_streaming')
    declarations = ('static void led_set_brightness_nosleep(struct led_classdev *,unsigned int);\n'
                    'static void led_set_brightness_nopm(struct led_classdev *,unsigned int);\n')
    # Public LED functions retain their linkage; prototypes precede dependency use.
    declarations = declarations.replace('static void led_set_', 'void led_set_')
    harness = args.work / 'privacy-ordering.c'
    harness.write_text(STUBS + declarations + '\n'.join(function(led_source,n) for n in led_functions) +
                       '\n' + '\n'.join(function(gpio_source,n) for n in ('gpio_led_set','gpio_led_set_blocking')) +
                       '\n' + '\n'.join(function(source,n) for n in media_functions) + '\n' + TESTS)
    command = ['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
               '-Wno-unused-parameter', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-DLED_REACHABLE='+str(int(not args.leds_unreachable)),
               '-DBASELINE_MODE='+str(1 if args.baseline == 'legacy' else 2 if args.baseline else 0),
               str(harness), '-o', str(args.work / 'privacy-ordering')]
    compiled = subprocess.run(command, capture_output=True, text=True)
    result = subprocess.run([str(args.work / 'privacy-ordering')], capture_output=True, text=True) \
        if not compiled.returncode else None
    report = dict(source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  led_source_sha256=hashlib.sha256(led_source.encode()).hexdigest(),
                  gpio_source_sha256=hashlib.sha256(gpio_source.encode()).hexdigest(),
                  command=command, baseline=args.baseline, leds_reachable=not args.leds_unreachable,
                  compile_returncode=compiled.returncode, compile_stdout=compiled.stdout,
                  compile_stderr=compiled.stderr, returncode=result.returncode if result else None,
                  stdout=result.stdout if result else '', stderr=result.stderr if result else '',
                  limits=['Actual V4L2 streaming, LED setters/worker and GPIO callbacks extracted',
                          'Work scheduling, GPIO bus and media state locks are serialized models',
                          'Provider completion precedes start in software; electrical/optical timing not verified',
                          'No real capture, full kernel concurrency or shared-LED-across-sensors acceptance'])
    (args.work / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(compiled.stderr+report['stdout']+report['stderr'], end='')
    if args.baseline:
        assert not compiled.returncode and result.returncode == -6
        assert 'gpiod->value==1' in result.stderr
        print('PASS: original '+args.baseline+' path reproduces LED-after-start defect')
    else:
        assert not compiled.returncode and result.returncode == 0


if __name__ == '__main__':
    main()
