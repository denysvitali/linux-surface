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
run = Path('/var/lib/spx-boot-diagnostics/attempts/20260930aj')
old_root = run / 'post-result-records'
out = Path('/var/tmp/spx-boost-switch-guard-20260930')
assert os.geteuid() == 0 and not out.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == 'd3b9f9b1-7e95-4963-8225-adf840755102'
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
guard = '\tif (portidx == WSA881X_PORT_BOOST &&\n\t    !wsa881x_spx_slave_available(data))\n\t\treturn -ENODEV;\n\n'
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
shutil.copy2(__file__, out / 'verify-boost-switch-guard.py')
with (out / 'compile.log').open('wb') as stream:
    result = subprocess.run(['make', '-j4', 'sound/soc/codecs/wsa881x.o'], cwd=repo,
                            stdout=stream, stderr=subprocess.STDOUT)
(out / 'compile-result.json').write_text(json.dumps({'exit_code': result.returncode, 'driver_sha256': sha(out / 'wsa881x.c')}, indent=2) + '\n')
assert result.returncode == 0
assert not re.search(r'warning:|error:', (out / 'compile.log').read_text(), re.I)
helpers = function(new, 'wsa881x_spx_slave_available')
callbacks = function(new, 'wsa881x_boost_ctrl') + '\n' + function(old, 'wsa881x_set_port').replace('wsa881x_set_port(', 'old_set_port(', 1) + '\n' + function(new, 'wsa881x_set_port')
harness = '\n#include <assert.h>\n#include <stdbool.h>\n#include <stdio.h>\n#include <string.h>\n#include <errno.h>\n#define SDW_SLAVE_ATTACHED 1\n#define READ_ONCE(x) (x)\n#define WSA881X_PORT_BOOST 2\n#define WSA881X_BOOST_EN_CTL 0x312a\n#define WSA881X_BOOST_EN_MASK 0x80\n#define WSA881X_BOOST_EN 0x80\nstatic bool spx_enumerated_mode;\nstruct slave { int status; };\nstruct wsa881x_priv { struct slave *slave; bool port_enable[4]; };\nstruct snd_soc_component { struct wsa881x_priv *data; };\nstruct soc_mixer_control { int reg; };\nstruct snd_kcontrol { unsigned long private_value; struct snd_soc_component *comp; };\nstruct snd_ctl_elem_value { struct { struct { long value[1]; } integer; } value; };\nstruct trace { unsigned count; int events[8][4]; };\nstatic struct trace trace;\nstatic int write_ret;\nstatic void record(int kind,int a,int b,int c) { assert(trace.count<8);int *r=trace.events[trace.count++];r[0]=kind;r[1]=a;r[2]=b;r[3]=c; }\nstatic struct snd_soc_component *snd_kcontrol_chip(struct snd_kcontrol *k) { return k->comp; }\nstatic struct wsa881x_priv *snd_soc_component_get_drvdata(struct snd_soc_component *c) { return c->data; }\nstatic void usleep_range(int a,int b) { record(1,a,b,0); }\nstatic int wsa881x_update_bits(struct wsa881x_priv *p,unsigned r,unsigned m,unsigned v) { (void)p;record(2,r,m,v);return write_ret; }\n' + helpers + '\n' + callbacks + '\nint main(void) {\n struct slave s={0};struct wsa881x_priv p={&s,{0}};struct snd_soc_component c={&p};\n struct soc_mixer_control mc={0};struct snd_kcontrol k={(unsigned long)&mc,&c};struct snd_ctl_elem_value v={0};\n unsigned cases=0;\n for(int mode=0;mode<2;mode++)for(int status=0;status<4;status++)for(int port=0;port<4;port++)\n for(int oldflag=0;oldflag<2;oldflag++)for(int request=0;request<2;request++)for(int fail=0;fail<2;fail++) {\n  spx_enumerated_mode=mode;s.status=status;mc.reg=port;v.value.integer.value[0]=request;write_ret=fail?-EIO:0;\n  bool flags[4]={true,false,true,false};flags[port]=oldflag;memcpy(p.port_enable,flags,sizeof(flags));\n  memset(&trace,0,sizeof(trace));int expected=old_set_port(&k,&v);struct trace original=trace;\n  bool original_flags[4];memcpy(original_flags,p.port_enable,sizeof(flags));\n  memcpy(p.port_enable,flags,sizeof(flags));memset(&trace,0,sizeof(trace));int actual=wsa881x_set_port(&k,&v);\n  if(mode&&status!=SDW_SLAVE_ATTACHED&&port==WSA881X_PORT_BOOST) { assert(actual==-ENODEV&&trace.count==0&&!memcmp(flags,p.port_enable,sizeof(flags))); }\n  else { assert(actual==expected&&!memcmp(&trace,&original,sizeof(trace))&&!memcmp(original_flags,p.port_enable,sizeof(flags))); }\n  cases++;\n }\n assert(cases==256);printf("%u exact-C differential cases passed: detached BOOST no flag change/write/sleep; attached/non-enumerated and other port controls preserve original behavior\\n",cases);\n}\n'
(out / 'boost-harness.c').write_text(harness)
with (out / 'harness-build.log').open('wb') as stream:
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-g', str(out / 'boost-harness.c'), '-o', str(out / 'boost-harness')], stdout=stream, stderr=subprocess.STDOUT, check=True)
with (out / 'harness-run.log').open('wb') as stream:
    subprocess.run([str(out / 'boost-harness')], stdout=stream, stderr=subprocess.STDOUT, check=True)
subprocess.run(['git', 'diff', '--check'], cwd=repo, check=True)
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=repo) == current
report = {'only_delta_is_boost_switch_availability_guard': True, 'config_unchanged': True,
          'native_codec_object_compile_exit_code': 0, 'compiler_warnings': 0,
          'exact_C_differential_cases': 256, 'sanitizers_passed': True,
          'detached_boost_returns_ENODEV_before_flag_IO_delay': True,
          'attached_non_enumerated_and_other_ports_preserved': True,
          'driver_sha256': sha(out / 'wsa881x.c'), 'source_diff_sha256': sha(out / 'source.diff'),
          'aj_post_result_manifest_sha256': sha(old_root / 'sha256.json'),
          'live_control_or_audio_test_performed': False,
          'limits': ['Entry-time status check does not serialize a subsequent asynchronous detach.',
                     'Stubs verify callback behavior; hardware outcome and error causality remain unproved.']}
(out / 'independent-review.json').write_text(json.dumps(report, indent=2) + '\n')
dest = run / 'boost-switch-guard-candidate'
assert not dest.exists()
shutil.copytree(out, dest)
hashes = {str(p.relative_to(dest)): sha(p) for p in sorted(dest.rglob('*')) if p.is_file()}
(dest / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
assert all(sha(dest / n) == h for n,h in hashes.items())
os.sync()
print(json.dumps(report | {'archive_files': len(hashes), 'archive_manifest_sha256': sha(dest / 'sha256.json')}, indent=2))
