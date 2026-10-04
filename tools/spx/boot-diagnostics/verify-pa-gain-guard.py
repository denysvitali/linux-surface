#!/usr/bin/python3
"""Verify the isolated gain guard and exercise the exact callback with stubs."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
repo = Path('/home/dvitali/Documents/git/linux-surface-next')
run = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ai')
old_root = run / 'post-result-records'
out = Path('/var/tmp/spx-pa-gain-guard-20260930')
assert os.geteuid() == 0 and not out.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == '81412181-f873-4ba8-a5fe-07f5376bf680'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def function(s, name):
    m = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\n\{', s, re.M)
    assert m, name
    pos = m.end()
    depth = 1
    while depth:
        depth += (s[pos] == '{') - (s[pos] == '}')
        pos += 1
    return s[m.start():pos]
old = (old_root / 'wsa881x-before.c').read_text()
new = (repo / 'sound/soc/codecs/wsa881x.c').read_text()
guard = '\tif (!wsa881x_spx_slave_available(wsa881x))\n\t\treturn -ENODEV;\n\n'
assert new.replace(guard, '', 1) == old
assert new.count(guard) == old.count(guard) + 1
assert sha(repo / '.config') == sha(old_root / 'config')
def chunks(b):
    return {x.split(b'\n', 1)[0]: x for x in re.split(b'(?=^diff --git )', b, flags=re.M) if x.startswith(b'diff --git ')}
current = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=repo)
before, after = chunks((old_root / 'source.diff').read_bytes()), chunks(current)
key = b'diff --git a/sound/soc/codecs/wsa881x.c b/sound/soc/codecs/wsa881x.c'
assert {k:v for k,v in before.items() if k != key} == {k:v for k,v in after.items() if k != key}
out.mkdir(mode=0o700)
(out / 'wsa881x-before.c').write_text(old)
(out / 'wsa881x.c').write_text(new)
(out / 'source.diff').write_bytes(current)
shutil.copy2(repo / '.config', out / 'config')
shutil.copy2(__file__, out / 'verify-pa-gain-guard.py')
with (out / 'compile.log').open('wb') as stream:
    result = subprocess.run(['make', '-j4', 'sound/soc/codecs/wsa881x.o'], cwd=repo,
                            stdout=stream, stderr=subprocess.STDOUT)
(out / 'compile-result.json').write_text(json.dumps({'exit_code': result.returncode, 'driver_sha256': sha(out / 'wsa881x.c')}, indent=2) + '\n')
assert result.returncode == 0
assert not re.search(r'warning:|error:', (out / 'compile.log').read_text(), re.I)
helpers = function(new, 'wsa881x_spx_slave_available')
callbacks = function(old, 'wsa881x_put_pa_gain').replace('wsa881x_put_pa_gain(', 'old_put_pa_gain(', 1) + '\n' + function(new, 'wsa881x_put_pa_gain')
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define SDW_SLAVE_ATTACHED 1
#define READ_ONCE(x) (x)
#define WSA881X_SPKR_DRV_GAIN 0x311b
#define WSA881X_SPKR_PAG_GAIN_MASK 0xf0
#define G_4P5DB 9
#define G_0DB 12
static bool spx_enumerated_mode;
struct slave { int status; };
struct wsa881x_priv { struct slave *slave; };
struct snd_soc_component { void *dev; struct wsa881x_priv *data; };
struct soc_mixer_control { int max; };
struct snd_kcontrol { unsigned long private_value; struct snd_soc_component *comp; };
struct snd_ctl_elem_value { struct { struct { long value[1]; } integer; } value; };
struct trace { unsigned count; int events[96][4]; };
static struct trace trace;
static int pm_ret, write_ret;
static void record(int kind,int a,int b,int c) { assert(trace.count<96);int *r=trace.events[trace.count++];r[0]=kind;r[1]=a;r[2]=b;r[3]=c; }
static struct snd_soc_component *snd_kcontrol_chip(struct snd_kcontrol *k) { return k->comp; }
static struct wsa881x_priv *snd_soc_component_get_drvdata(struct snd_soc_component *c) { return c->data; }
static int fls(unsigned n) { int i=0;while(n){n>>=1;i++;}return i; }
static int pm_runtime_resume_and_get(void *d) { (void)d;record(1,0,0,0);return pm_ret; }
static void pm_runtime_put_autosuspend(void *d) { (void)d;record(2,0,0,0); }
static void usleep_range(int a,int b) { record(3,a,b,0); }
static int wsa881x_update_bits(struct wsa881x_priv *p,unsigned r,unsigned m,unsigned v) { (void)p;record(4,r,m,v);return write_ret; }
static void dev_err(void *d,const char *s) { (void)d;(void)s;record(5,0,0,0); }
''' + helpers + '\n' + callbacks + r'''
int main(void) {
 struct slave s={0};struct wsa881x_priv p={&s};struct snd_soc_component c={0,&p};
 struct soc_mixer_control mc={12};struct snd_kcontrol k={(unsigned long)&mc,&c};struct snd_ctl_elem_value v={0};
 unsigned cases=0;
 int pm_cases[]={0,-EACCES,-EIO};int write_cases[]={0,-EIO};
 for(int mode=0;mode<2;mode++)for(int status=0;status<4;status++)
 for(unsigned pm=0;pm<3;pm++)for(unsigned wr=0;wr<2;wr++)for(int gain=0;gain<=12;gain++) {
  spx_enumerated_mode=mode;s.status=status;pm_ret=pm_cases[pm];write_ret=write_cases[wr];v.value.integer.value[0]=gain;
  memset(&trace,0,sizeof(trace));int expected=old_put_pa_gain(&k,&v);struct trace original=trace;
  memset(&trace,0,sizeof(trace));int actual=wsa881x_put_pa_gain(&k,&v);
  if(mode&&status!=SDW_SLAVE_ATTACHED) { assert(actual==-ENODEV&&trace.count==0); }
  else { assert(actual==expected&&!memcmp(&trace,&original,sizeof(trace))); }
  cases++;
 }
 assert(cases==624);printf("%u exact-C differential cases passed: detached no PM/write/sleep; original attached/non-enumerated ramps and error behavior preserved\n",cases);
}
'''
(out / 'gain-harness.c').write_text(harness)
with (out / 'harness-build.log').open('wb') as stream:
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-g', str(out / 'gain-harness.c'), '-o', str(out / 'gain-harness')], stdout=stream, stderr=subprocess.STDOUT, check=True)
with (out / 'harness-run.log').open('wb') as stream:
    subprocess.run([str(out / 'gain-harness')], stdout=stream, stderr=subprocess.STDOUT, check=True)
subprocess.run(['git', 'diff', '--check'], cwd=repo, check=True)
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=repo) == current
report = {'only_delta_is_pa_gain_availability_guard': True, 'config_unchanged': True,
          'native_codec_object_compile_exit_code': 0, 'compiler_warnings': 0,
          'exact_C_differential_cases': 624, 'sanitizers_passed': True,
          'detached_returns_ENODEV_before_PM_IO_delay': True,
          'attached_and_non_enumerated_behavior_preserved': True,
          'driver_sha256': sha(out / 'wsa881x.c'), 'source_diff_sha256': sha(out / 'source.diff'),
          'ai_post_result_manifest_sha256': sha(old_root / 'sha256.json'),
          'live_control_or_audio_test_performed': False,
          'limits': ['Entry-time status check does not serialize a subsequent asynchronous detach.',
                     'Stubs verify callback behavior; hardware outcome and error causality remain unproved.']}
(out / 'independent-review.json').write_text(json.dumps(report, indent=2) + '\n')
dest = run / 'pa-gain-guard-candidate'
assert not dest.exists()
shutil.copytree(out, dest)
hashes = {str(p.relative_to(dest)): sha(p) for p in sorted(dest.rglob('*')) if p.is_file()}
(dest / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
assert all(sha(dest / n) == h for n,h in hashes.items())
os.sync()
print(json.dumps(report | {'archive_files': len(hashes), 'archive_manifest_sha256': sha(dest / 'sha256.json')}, indent=2))
