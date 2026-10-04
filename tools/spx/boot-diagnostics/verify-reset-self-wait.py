#!/usr/bin/python3
"""Compile and compare actual SPI-HID functions with a detected self-wait."""
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next')
out=Path('/var/tmp/spx-reset-self-wait-v2-20260930')
run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al')
assert os.geteuid()==0 and not (out/'independent-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]
old=(out/'spi-hid-core.before.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text()
guard='\t/* A failed descriptor write can enter from reset_work itself. */\n\tif (current_work() == &shid->reset_work)\n\t\tcancel_work(&shid->reset_work);\n\telse\n\t\tcancel_work_sync(&shid->reset_work);'
assert new.count(guard)==1 and new.replace(guard,'\tcancel_work_sync(&shid->reset_work);',1)==old
assert (out/'config').read_bytes()==(repo/'.config').read_bytes()
current=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)
def chunks(b):return {s.split(b'\n',1)[0]:s for s in re.split(b'(?=^diff --git )',b,flags=re.M) if s.startswith(b'diff --git ')}
a=chunks((out/'source-before.diff').read_bytes());b=chunks(current)
key=b'diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c'
assert {k:v for k,v in a.items() if k!=key}=={k:v for k,v in b.items() if k!=key}
(out/'spi-hid-core.c').write_text(new);(out/'source.diff').write_bytes(current);shutil.copy2(__file__,out/Path(__file__).name)
prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <setjmp.h>
#define SPI_HID_MAX_RESET_ATTEMPTS 3
#define SPI_HID_SOFT_RETRY_ATTEMPTS 5
#define SPI_HID_POWER_MODE_OFF 3
#define SPI_HID_POWER_MODE_ACTIVE 1
#define SPI_HID_OUTPUT_HEADER_LEN 6
#define SPI_HID_OUTPUT_BODY_LEN 4
#define READ_ONCE(x) (x)
#define round_up(x,y) (((x)+(y)-1)&~((y)-1))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define dev_err(d,...) ((void)(d))
#define dev_dbg(d,...) ((void)(d))
#define trace_spi_hid_reset_work(s) ((void)(s))
#define spin_lock_irqsave(l,f) do { (void)(l);(f)=0;assert(!locked);locked=true;record(1,0,0); } while(0)
#define spin_unlock_irqrestore(l,f) do { (void)(l);(void)(f);assert(locked);locked=false;record(2,0,0); } while(0)
struct device { struct {int unused;} kobj; };
struct spi_device {struct device dev;};
struct work_struct {int id;bool pending;};
struct spi_hid_output_buf {unsigned char header[6],body[4];};
struct spi_hid {struct spi_device *spi;bool stopping,powered,startup_active,ready;unsigned power_state,attempts,dir_count,input_lock;struct work_struct reset_work,create_device_work,refresh_device_work,error_work;void *pinctrl,*pinctrl_reset,*pinctrl_active;unsigned hid_desc_addr;struct spi_hid_output_buf output;};
struct trace {unsigned count;int events[64][3];};
static struct trace trace;
static bool locked;
static int caller,pin_ret,output_ret,flush_bits;
static struct spi_hid active;
static jmp_buf self_wait;
static bool trapped,queued_rerun;
static void record(int k,int a,int b) {assert(trace.count<64);int *e=trace.events[trace.count++];e[0]=k;e[1]=a;e[2]=b;}
static struct work_struct *current_work(void) {switch(caller){case 1:return &active.reset_work;case 2:return &active.create_device_work;case 3:return &active.refresh_device_work;case 4:return &active.error_work;default:return NULL;}}
static void cancel_work_sync(struct work_struct *w) {assert(!locked);record(3,w->id,0);w->pending=false;if(w==current_work()){trapped=true;longjmp(self_wait,1);}}
static bool cancel_work(struct work_struct *w) {assert(!locked);record(14,w->id,0);bool pending=w->pending;w->pending=false;return pending;}
static void spi_hid_stop_hid(struct spi_hid *s) {(void)s;record(4,0,0);}
static int spi_hid_power_down(struct spi_hid *s) {(void)s;record(5,0,0);return 0;}
static void sysfs_notify(void *p,void *q,const char *n) {(void)p;(void)q;(void)n;record(6,0,0);}
static void usleep_range(int a,int b){assert(!locked);record(7,a,b);}
static void msleep(int a){assert(!locked);record(8,a,0);}
static int pinctrl_select_state(void *p,void *s){(void)p;record(9,s==active.pinctrl_reset?0:1,pin_ret);return pin_ret;}
static bool flush_work(struct work_struct *w){assert(!locked);record(10,w->id,0);return (flush_bits>>(w->id-2))&1;}
static void spi_hid_output_header(unsigned char *b,unsigned a,unsigned l){memset(b,0xa5,6);record(11,a,l);}
static int spi_hid_output(struct spi_hid *s,void *b,unsigned n){(void)s;(void)b;assert(!locked);record(12,n,output_ret);return output_ret;}
#define SPI_HID_DIAG_DESC_REQUEST 1
#define SPI_HID_DIAG_DESC_SENT 2
static void spi_hid_diag(struct spi_hid *s,int k,int r,unsigned v){(void)s;record(13,k,r);(void)v;}
'''
functions=function(old,'spi_hid_error_handler').replace('spi_hid_error_handler(', 'old_error_handler(',1)+'\n'+function(new,'spi_hid_error_handler')+'\n'+function(old,'spi_hid_reset_work').replace('spi_hid_reset_work(', 'old_reset_work(',1).replace('spi_hid_error_handler(shid)','old_error_handler(shid)')+'\n'+function(new,'spi_hid_reset_work')
tests=r'''
struct outcome {struct trace trace;bool trapped,ready,pending;unsigned state,attempts,dir_count;int ret;};
static struct spi_device spi;
static void setup(int stop,int power,int startup,int state,int attempts,int ready) {
 memset(&active,0,sizeof(active));active.spi=&spi;active.stopping=stop;active.powered=power;active.startup_active=startup;active.power_state=state;active.attempts=attempts;active.ready=ready;
 active.reset_work.id=1;active.reset_work.pending=queued_rerun;active.create_device_work.id=2;active.refresh_device_work.id=3;active.error_work.id=4;active.hid_desc_addr=1;active.pinctrl_reset=(void *)1;active.pinctrl_active=(void *)2;
 memset(&trace,0,sizeof(trace));trapped=false;locked=false;
}
static struct outcome invoke(bool old,bool reset) {
 int ret=0;if(!setjmp(self_wait)){if(reset){if(old)old_reset_work(&active.reset_work);else spi_hid_reset_work(&active.reset_work);}else ret=old?old_error_handler(&active):spi_hid_error_handler(&active);}
 assert(!locked);return (struct outcome){trace,trapped,active.ready,active.reset_work.pending,active.power_state,active.attempts,active.dir_count,ret};
}
static void same(struct outcome a,struct outcome b){assert(a.trapped==b.trapped&&a.ready==b.ready&&a.pending==b.pending&&a.state==b.state&&a.attempts==b.attempts&&a.dir_count==b.dir_count&&a.ret==b.ret&&!memcmp(&a.trace,&b.trace,sizeof(a.trace)));}
static void no_self_cancel(struct outcome a){assert(!a.trapped&&!a.pending);bool canceled=false;for(unsigned i=0;i<a.trace.count;i++){assert(!(a.trace.events[i][0]==3&&a.trace.events[i][1]==1));if(a.trace.events[i][0]==14&&a.trace.events[i][1]==1)canceled=true;}assert(canceled);}
int main(void){unsigned cases=0,detected=0;int states[]={1,2,3};
 for(int queued=0;queued<2;queued++)for(caller=0;caller<5;caller++)for(int stop=0;stop<2;stop++)for(int power=0;power<2;power++)for(int startup=0;startup<2;startup++)for(int si=0;si<3;si++)for(int attempts=0;attempts<5;attempts++)for(int pi=0;pi<3;pi++)for(int ready=0;ready<2;ready++){
  queued_rerun=queued;pin_ret=pi==0?0:pi==1?-EIO:-EINVAL;setup(stop,power,startup,states[si],attempts,ready);struct outcome a=invoke(true,false);setup(stop,power,startup,states[si],attempts,ready);struct outcome b=invoke(false,false);
  bool expected=caller==1&&!stop&&power&&!startup&&states[si]!=3&&attempts<3;assert(a.trapped==expected);
  if(expected){detected++;no_self_cancel(b);assert(b.ret==0&&b.attempts==(unsigned)attempts+1&&!b.ready&&b.state==1);}else same(a,b);cases++;
 }
 assert(cases==7200);unsigned reset_cases=0;caller=1;
 for(int queued=0;queued<2;queued++)for(int stop=0;stop<2;stop++)for(int power=0;power<2;power++)for(int startup=0;startup<2;startup++)for(int si=0;si<3;si++)for(int attempts=0;attempts<5;attempts++)for(int ready=0;ready<2;ready++)for(flush_bits=0;flush_bits<4;flush_bits++)for(int oi=0;oi<3;oi++){
  queued_rerun=queued;output_ret=oi==0?0:oi==1?-EIO:-ESHUTDOWN;setup(stop,power,startup,states[si],attempts,ready);struct outcome a=invoke(true,true);setup(stop,power,startup,states[si],attempts,ready);struct outcome b=invoke(false,true);
  bool expected=!stop&&power&&!startup&&states[si]!=3&&attempts<3&&output_ret;assert(a.trapped==expected);if(expected){detected++;no_self_cancel(b);assert(b.ret==0&&b.attempts==(unsigned)attempts+1&&!b.ready&&b.state==1);}else same(a,b);reset_cases++;
 }
 assert(reset_cases==5760);printf("%u handler cases and %u descriptor-worker cases passed; %u original self-waits detected; all other return/state/call traces identical\n",cases,reset_cases,detected);
}
'''
(out/'reset-harness.c').write_text(prelude+'\n'+functions+'\n'+tests)
for label,args in [('harness-build',['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g',str(out/'reset-harness.c'),'-o',str(out/'reset-harness')]),('harness-run',[str(out/'reset-harness')]),('compile',['make','-j4','drivers/hid/spi-hid/spi-hid.o']),('diff-check',['git','diff','--check'])]:
 with (out/(label+'.log')).open('wb') as stream:r=subprocess.run(args,cwd=repo,stdout=stream,stderr=subprocess.STDOUT)
 assert r.returncode==0,(label,r.returncode,(out/(label+'.log')).read_text()[-4000:])
assert not re.search(r'warning:|error:',(out/'compile.log').read_text(),re.I)
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==current
assert (repo/'.config').read_bytes()==(out/'config').read_bytes()
shutil.copy2(repo/'drivers/hid/spi-hid/spi-hid.o',out/'spi-hid.tested.o')
report={'only_delta_is_reset_worker_self_wait_guard':True,'config_and_other_tracked_deltas_unchanged':True,'handler_differential_cases':7200,'actual_descriptor_worker_cases':5760,'queued_reset_rerun_canceled_without_self_wait':True,'sanitizers_passed':True,'native_SPI_HID_object_compile_exit_code':0,'compiler_warnings':0,'driver_sha256':sha(out/'spi-hid-core.c'),'source_diff_sha256':sha(out/'source.diff'),'config_sha256':sha(out/'config'),'hardware_deployment_performed':False,'limits':['Workqueue operations are stubbed; no exhaustive concurrency or hardware startup claim follows.','Other inherited reset/create/refresh cancellation cycles remain outside this change.','AL initial-probe zero-header timeout remains unexplained; no reboot shutdown hook or retry/reset policy changes are included.']}
(out/'independent-review.json').write_text(json.dumps(report,indent=2)+'\n');dest=run/'reset-self-wait-candidate-v2';assert not dest.exists();shutil.copytree(out,dest)
h={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()};(dest/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(dest/n)==v for n,v in h.items());os.sync();print((out/'harness-run.log').read_text());print(json.dumps(report|{'archive_files':len(h),'archive_manifest_sha256':sha(dest/'sha256.json')},indent=2))
