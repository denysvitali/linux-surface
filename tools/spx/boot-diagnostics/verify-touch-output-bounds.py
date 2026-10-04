#!/usr/bin/python3
"""Offline regression checks of the candidate's actual output-building functions."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

os.umask(0o077)
repo = Path('/home/dvitali/Documents/git/linux-surface-next')
out = Path('/var/tmp/spx-touch-output-bounds-20261002')
assert os.geteuid() == 0 and not (out / 'verification.json').exists()


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def function(source, name):
    m = re.search(r'^static [^;{}]*\b' + name + r'\([^;{}]*\)\n\{', source, re.M)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[m.start():end]


old = (out / 'spi-hid-core.before.c').read_text()
new = (repo / 'drivers/hid/spi-hid/spi-hid-core.c').read_text()
changed = ('spi_hid_send_output_report', 'spi_hid_ll_raw_request', 'spi_hid_ll_output_report')
restored = new
for name in changed:
    restored = restored.replace(function(new, name), function(old, name), 1)
assert restored == old
assert (out / 'spi-hid-core.before.h').read_bytes() == (repo / 'drivers/hid/spi-hid/spi-hid-core.h').read_bytes()
assert (out / 'config').read_bytes() == (repo / '.config').read_bytes()
current = subprocess.check_output(['git', '-c', 'safe.directory=' + str(repo), 'diff', '--binary', 'HEAD'], cwd=repo)


def sections(data):
    return {s.splitlines()[0]: s for s in re.split(rb'(?=^diff --git )', data, flags=re.M) if s}


before, after = sections((out / 'source-before.diff').read_bytes()), sections(current)
assert {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)} == {
    b'diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c'}
(out / 'source.diff').write_bytes(current)
(out / 'spi-hid-core.c').write_text(new)
shutil.copy2(__file__, out / Path(__file__).name)
name = 'drivers/hid/spi-hid/spi-hid-core.c'
patch = 'diff --git a/' + name + ' b/' + name + '\n' + ''.join(difflib.unified_diff(
    old.splitlines(True), new.splitlines(True), fromfile='a/' + name, tofile='b/' + name))
(out / 'output-bounds.patch').write_text(patch)
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8; typedef uint8_t __u8; typedef uint16_t u16; typedef uint32_t u32;
#define SPI_HID_OUTPUT_HEADER_OPCODE_WRITE 2
#define SPI_HID_OUTPUT_HEADER_VERSION 2
#define SPI_HID_CONTENT_TYPE_OUTPUT_REPORT 5
#define SPI_HID_CONTENT_TYPE_SET_FEATURE 3
#define HID_REQ_SET_REPORT 9
#define HID_REQ_GET_REPORT 1
#define round_up(x,y) (((x)+(y)-1)&~((y)-1))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define dev_err(d,...) ((void)(d))
struct device {int unused;};
struct spi_device {struct device dev; void *data;};
struct hid_device {void *driver_data;};
struct spi_hid_output_report {u8 content_type;u16 content_length;u8 content_id;u8 *content;};
struct spi_hid_output_buf {u8 header[6],body[4],content[8192];};
struct spi_hid {struct spi_device *spi;struct spi_hid_output_buf output;
 struct {u16 max_output_length,output_register;} desc;
 struct {u8 body[3],content[8192];} response; bool ready; int lock;};
static struct spi_hid shid;
static struct spi_device spi;
static struct hid_device hid;
static unsigned calls, sent_length, cases;
static int bus_result;
static u8 sent[sizeof(struct spi_hid_output_buf)];
static void *spi_get_drvdata(struct spi_device *s) {return s->data;}
static void mutex_lock(int *m) {assert(!*m);*m=1;}
static void mutex_unlock(int *m) {assert(*m==1);*m=0;}
static int spi_hid_output(struct spi_hid *s,void *p,u16 n) {
 assert(s==&shid && n<=sizeof(sent));calls++;sent_length=n;memcpy(sent,p,n);return bus_result;
}
static int spi_hid_get_request(struct spi_hid *s,u8 id) {(void)s;(void)id;return -EOPNOTSUPP;}
'''
names = ('spi_hid_output_header', 'spi_hid_output_body', 'spi_hid_send_output_report',
         'spi_hid_set_request', 'spi_hid_ll_raw_request', 'spi_hid_ll_output_report')
functions = '\n\n'.join(function(new, n) for n in names)
tests = r'''
static void setup(unsigned max) {
 memset(&shid,0,sizeof(shid));memset(&shid.output,0xa5,sizeof(shid.output));
 spi.data=&shid;shid.spi=&spi;hid.driver_data=&spi;shid.ready=true;
 shid.desc.max_output_length=max;shid.desc.output_register=0x1234;
 calls=0;bus_result=0;sent_length=0;memset(sent,0xee,sizeof(sent));
}
static void check_packet(unsigned payload,unsigned type,unsigned id,const u8 *data) {
 unsigned wire=(payload+10)&~3U; /* Existing round_up(payload+7,4). */
 assert(calls==1 && sent_length==6+wire);
 assert(sent[0]==2 && sent[1]==0 && sent[2]==0x12 && sent[3]==0x34);
 assert(sent[4]==(u8)(2|((wire&15)<<4)) && sent[5]==wire/16);
 assert(sent[6]==type && sent[7]==(u8)(payload+3) && sent[8]==(payload+3)/256 && sent[9]==id);
 assert(!payload || !memcmp(sent+10,data,payload));
 for(unsigned i=10+payload;i<sent_length;i++)assert(sent[i]==0);
 const u8 *raw=(const u8 *)&shid.output;
 for(unsigned i=sent_length;i<sizeof(shid.output);i++)assert(raw[i]==0xa5);
}
int main(void) {
 /* Exercise every representable in-buffer payload and descriptor-limit edges. */
 unsigned maxima[]={0,1,3,4,7,31,8192,65535};
 for(unsigned m=0;m<sizeof(maxima)/sizeof(maxima[0]);m++)
  for(unsigned n=0;n<=8192;n++) {
   setup(maxima[m]);u8 *data=n?malloc(n):NULL;assert(!n||data);
   for(unsigned i=0;i<n;i++)data[i]=(u8)(i*17+n);
   struct spi_hid_output_report r={3,n+3,0x42,data};
   unsigned wire=(n+10)&~3U, limit=(maxima[m]+10)&~3U;
   int rc=spi_hid_send_output_report(&shid,0x1234,&r);
   if(wire>limit||wire>8196||wire>4095)assert(rc==-E2BIG&&!calls);
   else {assert(rc==0);check_packet(n,3,0x42,data);}
   free(data);cases++;
  }
 /* Reject malformed metadata before bus submission. */
 for(unsigned n=0;n<3;n++) {
  setup(65535);struct spi_hid_output_report r={3,n,0,NULL};
  assert(spi_hid_send_output_report(&shid,0x1234,&r)==-EINVAL&&!calls);cases++;
 }
 setup(65535);struct spi_hid_output_report missing={3,4,0,NULL};
 assert(spi_hid_send_output_report(&shid,0x1234,&missing)==-EINVAL&&!calls);cases++;
 /* High u16 content lengths must remain wide while adding body/alignment. */
 unsigned large_lengths[]={65529,65532,65535};
 for(unsigned i=0;i<3;i++) {
  setup(65535);unsigned n=large_lengths[i];u8 *data=calloc(n-3,1);assert(data);
  struct spi_hid_output_report r={3,n,0,data};
  assert(spi_hid_send_output_report(&shid,0x1234,&r)==-E2BIG&&!calls);
  free(data);cases++;
 }
 /* Real output and SET_REPORT callers include the report ID separately. */
 for(unsigned n=1;n<=8193;n++) {
  u8 *data=malloc(n);assert(data);for(unsigned i=0;i<n;i++)data[i]=(u8)(i*29+7);
  for(unsigned raw=0;raw<2;raw++) {
   setup(65535);
   int rc=raw?spi_hid_ll_raw_request(&hid,data[0],data,n,0,HID_REQ_SET_REPORT):
              spi_hid_ll_output_report(&hid,data,n);
   if(n>4086)assert(rc==-E2BIG&&!calls);
   else {assert(rc==(int)n);check_packet(n-1,raw?3:5,data[0],data+1);}
   assert(shid.lock==0);cases++;
  }
  free(data);
 }
 setup(65535);
 assert(spi_hid_ll_output_report(&hid,NULL,0)==-EINVAL);
 assert(spi_hid_ll_raw_request(&hid,0,NULL,0,0,HID_REQ_SET_REPORT)==-EINVAL);
 assert(spi_hid_ll_raw_request(&hid,0,NULL,0,0,HID_REQ_GET_REPORT)==-EINVAL);
 assert(!calls);cases+=3;
 size_t too_big[]={8194,65536,SIZE_MAX};
 for(unsigned i=0;i<3;i++) {
  setup(65535);
  assert(spi_hid_ll_output_report(&hid,NULL,too_big[i])==-E2BIG);
  assert(spi_hid_ll_raw_request(&hid,0,NULL,too_big[i],0,HID_REQ_SET_REPORT)==-E2BIG);
  assert(!calls);cases+=2;
 }
 u8 valid[]={0x42,1,2,3};
 for(unsigned raw=0;raw<2;raw++) {
  setup(65535);shid.ready=false;
  assert((raw?spi_hid_ll_raw_request(&hid,0x42,valid,4,0,HID_REQ_SET_REPORT):spi_hid_ll_output_report(&hid,valid,4))==-ENODEV);
  assert(!calls&&!shid.lock);cases++;
  setup(65535);bus_result=-EIO;
  assert((raw?spi_hid_ll_raw_request(&hid,0x42,valid,4,0,HID_REQ_SET_REPORT):spi_hid_ll_output_report(&hid,valid,4))==-EIO);
  assert(calls==1&&!shid.lock);cases++;
 }
 setup(65535);
 assert(spi_hid_ll_raw_request(&hid,0x43,valid,4,0,HID_REQ_SET_REPORT)==-EINVAL&&!calls&&!shid.lock);cases++;
 printf("%u candidate regression cases passed; exact payload, zero trailing bytes, bounds, caller results and bus errors verified\n",cases);
 return 0;
}
'''
(out / 'candidate-regression.c').write_text(prelude + '\n' + functions + '\n' + tests)
commands = [(['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
              '-Wno-unused-parameter', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
              str(out / 'candidate-regression.c'), '-o', str(out / 'candidate-regression')], 'harness-build.log'),
            ([str(out / 'candidate-regression')], 'harness-run.log'),
            (['scripts/checkpatch.pl', '--no-tree', '--strict', str(out / 'output-bounds.patch')], 'checkpatch.log')]
for command, log in commands:
    with (out / log).open('wb') as stream:
        result = subprocess.run(command, cwd=repo, stdout=stream, stderr=subprocess.STDOUT,
                                env=os.environ | {'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1'}, timeout=120)
    assert result.returncode == 0, (log, result.returncode)
    print(log + ': passed', flush=True)
report = dict(candidate_source_sha256=sha(out/'spi-hid-core.c'), source_diff_sha256=sha(out/'source.diff'),
              changed_functions=list(changed), other_source_and_config_unchanged=True,
              sanitizers_passed=True, hardware_tested=False,
              limitations=['SPI submission is mocked; these are offline bounds/framing checks.',
                           'Existing transfer lengths are preserved; protocol size cleanup is deferred.',
                           'This does not diagnose or fix AO startup silence.'])
(out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print((out/'harness-run.log').read_text(),end='')
