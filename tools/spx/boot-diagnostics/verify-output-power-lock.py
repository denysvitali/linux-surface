#!/usr/bin/python3
"""Extract output/power/reset code and test controlled ownership interleavings."""
import difflib,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');out=Path('/var/tmp/spx-output-power-lock-20261001');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al')
assert os.geteuid()==0 and not (out/'independent-review.json').exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
old=(out/'spi-hid-core.before.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text();oh=(out/'spi-hid-core.before.h').read_text();nh=(repo/'drivers/hid/spi-hid/spi-hid-core.h').read_text()
names=('spi_hid_output','spi_hid_power_down','spi_hid_power_up','spi_hid_reset_work')
restored=new
for n in names:restored=restored.replace(function(new,n),function(old,n),1)
assert restored.replace('\tmutex_init(&shid->output_lock);\n','',1)==old
assert nh.replace('\t/* Serializes output transfers and supply transitions. */\n\tstruct mutex output_lock;\n','',1)==oh
assert (repo/'.config').read_bytes()==(out/'config').read_bytes()
current=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)
def chunks(b):return {s.split(b'\n',1)[0]:s for s in re.split(b'(?=^diff --git )',b,flags=re.M) if s.startswith(b'diff --git ')}
a=chunks((out/'source-before.diff').read_bytes());b=chunks(current);keys={b'diff --git a/drivers/hid/spi-hid/spi-hid-core.'+s+b' b/drivers/hid/spi-hid/spi-hid-core.'+s for s in (b'c',b'h')}
assert {k:v for k,v in a.items() if k not in keys}=={k:v for k,v in b.items() if k not in keys}
(out/'spi-hid-core.c').write_text(new);(out/'spi-hid-core.h').write_text(nh);(out/'source.diff').write_bytes(current);shutil.copy2(__file__,out/Path(__file__).name)
prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint8_t __u8;
#define READ_ONCE(x) (x)
#define SPI_HID_INPUT_STAGE_IDLE 0
#define SPI_HID_POWER_MODE_OFF 3
#define SPI_HID_OUTPUT_HEADER_LEN 6
#define SPI_HID_OUTPUT_BODY_LEN 4
#define SPI_HID_OUTPUT_HEADER_OPCODE_WRITE 2
#define SPI_HID_OUTPUT_HEADER_VERSION 2
#define SPI_HID_DIAG_DOWN 1
#define SPI_HID_DIAG_REGULATOR 2
#define SPI_HID_DIAG_DESC_REQUEST 3
#define SPI_HID_DIAG_DESC_SENT 4
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define round_up(x,y) (((x)+(y)-1)&~((y)-1))
#define dev_err(d,...) ((void)(d))
#define dev_dbg(d,...) ((void)(d))
#define trace_spi_hid_output_begin(...) ((void)0)
#define trace_spi_hid_output_end(...) ((void)0)
#define trace_spi_hid_reset_work(s) ((void)(s))
#define spin_lock_irqsave(l,f) do{(f)=0;assert(!pthread_mutex_lock(l));}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(f);assert(!pthread_mutex_unlock(l));}while(0)
struct device {int unused;};struct spi_device {struct device dev;};
struct work_struct {int id;};struct spi_hid_output_buf {unsigned char header[6],body[4],content[64];};
struct spi_transfer {void *tx_buf;unsigned len;};struct spi_message {struct spi_transfer *transfers;unsigned count;};
struct spi_hid_output_report {u8 content_type;u16 content_length;u8 content_id;u8 *content;};
struct spi_hid {struct spi_device *spi;pthread_mutex_t input_lock,output_lock,lock;_Atomic bool stopping,powered;bool startup_active,ready;unsigned power_state,input_transfer_pending,input_stage,bus_error_count,regulator_error_count,dir_count;int bus_last_error,regulator_last_error,input_idle,startup_work;void *pinctrl,*pinctrl_sleep,*supply;struct work_struct create_device_work,refresh_device_work,reset_work;struct spi_hid_output_buf output;unsigned hid_desc_addr;struct {unsigned max_output_length;} desc;};
static struct spi_hid active;static struct spi_device spi;
static pthread_mutex_t control=PTHREAD_MUTEX_INITIALIZER,bus=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static _Thread_local int role;
static int mode,spi_ret,enable_ret,disable_ret;
static bool block_spi,block_enable,release_spi,release_enable,spi_entered,enable_entered,down_waiting,reset_waiting,second_spi,drain_waiting,release_input,flip_stop;
static unsigned spi_calls,enable_calls,disable_calls,overlap,payload_changed;
static _Atomic bool physical,writing;
static unsigned char saved[64],packet[64];static unsigned packet_length;
static void mutex_lock(pthread_mutex_t *p){assert(!pthread_mutex_lock(&control));if(p==&active.output_lock&&role==2){down_waiting=true;pthread_cond_broadcast(&condition);}if(p==&active.lock&&role==3){reset_waiting=true;pthread_cond_broadcast(&condition);}assert(!pthread_mutex_unlock(&control));assert(!pthread_mutex_lock(p));}
static void mutex_unlock(pthread_mutex_t *p){assert(!pthread_mutex_unlock(p));}
static void spi_message_init_with_transfers(struct spi_message *m,struct spi_transfer *t,unsigned n){m->transfers=t;m->count=n;}
static int spi_sync(struct spi_device *s,struct spi_message *m){(void)s;assert(m->count==1);assert(!pthread_mutex_lock(&control));if(role==3){second_spi=true;pthread_cond_broadcast(&condition);}assert(!pthread_mutex_unlock(&control));assert(!pthread_mutex_lock(&bus));writing=true;
 assert(!pthread_mutex_lock(&control));spi_calls++;if(block_spi&&role==1){spi_entered=true;pthread_cond_broadcast(&condition);while(!release_spi)pthread_cond_wait(&condition,&control);if(mode==3&&memcmp(saved,m->transfers->tx_buf,m->transfers->len))payload_changed++;}packet_length=m->transfers->len;assert(packet_length<=sizeof(packet));memcpy(packet,m->transfers->tx_buf,packet_length);assert(!pthread_mutex_unlock(&control));writing=false;assert(!pthread_mutex_unlock(&bus));return spi_ret;}
static int regulator_enable(void *p){(void)p;assert(!pthread_mutex_lock(&control));enable_calls++;if(block_enable){enable_entered=true;pthread_cond_broadcast(&condition);while(!release_enable)pthread_cond_wait(&condition,&control);}if(!enable_ret)physical=true;if(flip_stop)active.stopping=true;assert(!pthread_mutex_unlock(&control));return enable_ret;}
static int regulator_disable(void *p){(void)p;assert(!pthread_mutex_lock(&control));disable_calls++;if(writing)overlap++;if(!disable_ret)physical=false;assert(!pthread_mutex_unlock(&control));return disable_ret;}
static int pinctrl_select_state(void *p,void *s){(void)p;(void)s;return 0;}
static void cancel_delayed_work_sync(int *p){(void)p;}
static void wait_for_completion(int *p){(void)p;assert(!pthread_mutex_lock(&control));if(mode==4){drain_waiting=true;pthread_cond_broadcast(&condition);while(!release_input)pthread_cond_wait(&condition,&control);}assert(!pthread_mutex_unlock(&control));}
static void usleep_range(unsigned a,unsigned b){assert(a==5000&&b==6000);}
static void spi_hid_diag(struct spi_hid *s,int e,int r,unsigned v){(void)s;(void)e;(void)r;(void)v;}
static bool flush_work(struct work_struct *w){(void)w;return false;}
static void sysfs_notify(void *p,void *q,const char *n){(void)p;(void)q;(void)n;}
static void spi_hid_schedule_error(struct spi_hid *s){(void)s;}
'''
# reset's optional notification uses dev.kobj; preserved in the fixture.
prelude=prelude.replace('struct device {int unused;};','struct device {struct {int unused;} kobj;};')
functions=function(new,'spi_hid_output_header')+'\n'+function(new,'spi_hid_output_body')
for n in names:
 f=function(old,n).replace(n+'(', 'old_'+n+'(',1)
 if n=='spi_hid_reset_work':f=f.replace('spi_hid_output(shid','old_spi_hid_output(shid')
 functions+='\n'+f+'\n'+function(new,n)
functions+='\n'+function(old,'spi_hid_send_output_report').replace('spi_hid_send_output_report(', 'old_send_output_report(',1).replace('spi_hid_output(shid','old_spi_hid_output(shid')+'\n'+function(new,'spi_hid_send_output_report')
tests=r'''
static void setup(bool powered,bool stop){memset(&active,0,sizeof(active));assert(!pthread_mutex_init(&active.input_lock,NULL));assert(!pthread_mutex_init(&active.output_lock,NULL));assert(!pthread_mutex_init(&active.lock,NULL));active.spi=&spi;active.powered=powered;active.stopping=stop;active.startup_active=true;active.power_state=1;active.hid_desc_addr=1;active.desc.max_output_length=32;physical=powered;writing=false;
 mode=spi_ret=enable_ret=disable_ret=0;spi_calls=enable_calls=disable_calls=overlap=payload_changed=0;block_spi=block_enable=release_spi=release_enable=spi_entered=enable_entered=down_waiting=reset_waiting=second_spi=drain_waiting=release_input=flip_stop=false;memset(saved,0,sizeof(saved));memset(packet,0,sizeof(packet));role=0;}
static void cleanup(void){assert(!pthread_mutex_trylock(&active.output_lock));assert(!pthread_mutex_unlock(&active.output_lock));assert(!pthread_mutex_destroy(&active.output_lock));assert(!pthread_mutex_destroy(&active.input_lock));assert(!pthread_mutex_destroy(&active.lock));}
struct result {int ret;bool powered,physical;unsigned bus_errors,reg_errors,enable,disable;int bus_errno,reg_errno;unsigned len;unsigned char packet[64];};
static struct result snapshot(int ret){struct result r={ret,active.powered,physical,active.bus_error_count,active.regulator_error_count,enable_calls,disable_calls,active.bus_last_error,active.regulator_last_error,packet_length,{0}};memcpy(r.packet,packet,sizeof(packet));return r;}
static void same(struct result a,struct result b){assert(a.ret==b.ret&&a.powered==b.powered&&a.physical==b.physical&&a.bus_errors==b.bus_errors&&a.reg_errors==b.reg_errors&&a.enable==b.enable&&a.disable==b.disable&&a.bus_errno==b.bus_errno&&a.reg_errno==b.reg_errno&&a.len==b.len&&!memcmp(a.packet,b.packet,64));}
static void signal_release(bool enable){assert(!pthread_mutex_lock(&control));if(enable)release_enable=true;else release_spi=true;pthread_cond_broadcast(&condition);assert(!pthread_mutex_unlock(&control));}
static void wait_flag(bool *p){assert(!pthread_mutex_lock(&control));while(!*p)pthread_cond_wait(&condition,&control);assert(!pthread_mutex_unlock(&control));}
static bool use_old;static int writer_result,down_result,up_result;
static unsigned char raw[16]={0x91,0x42,0x73};
static void *writer(void *p){(void)p;role=1;writer_result=use_old?old_spi_hid_output(&active,raw,10):spi_hid_output(&active,raw,10);return NULL;}
static void *down(void *p){(void)p;role=2;down_result=use_old?old_spi_hid_power_down(&active):spi_hid_power_down(&active);return NULL;}
static void *up(void *p){(void)p;role=4;up_result=use_old?old_spi_hid_power_up(&active):spi_hid_power_up(&active);return NULL;}
static void *normal(void *p){(void)p;role=1;u8 bytes[6]={1,2,3,4,5,6};struct spi_hid_output_report r={2,6,0x11,bytes};mutex_lock(&active.lock);/* Real caller owns request mutex before preparing the shared packet. */writer_result=use_old?old_send_output_report(&active,0x4321,&r):spi_hid_send_output_report(&active,0x4321,&r);mutex_unlock(&active.lock);return NULL;}
static void *reset(void *p){(void)p;role=3;if(use_old)old_spi_hid_reset_work(&active.reset_work);else spi_hid_reset_work(&active.reset_work);return NULL;}
int main(void){unsigned output_cases=0,power_cases=0;
 for(int stop=0;stop<2;stop++)for(int powered=0;powered<2;powered++)for(int err=0;err<3;err++)for(int len=0;len<=16;len+=4){
  int rc=err==0?0:err==1?-EIO:-ESHUTDOWN;setup(powered,stop);spi_ret=rc;struct result a=snapshot(old_spi_hid_output(&active,raw,len));cleanup();setup(powered,stop);spi_ret=rc;struct result b=snapshot(spi_hid_output(&active,raw,len));if(stop||!powered)assert(b.ret==-ESHUTDOWN&&spi_calls==0&&b.bus_errors==0);else same(a,b);cleanup();output_cases++;
 }
 for(int stop=0;stop<2;stop++)for(int powered=0;powered<2;powered++)for(int err=0;err<2;err++)for(int late_stop=0;late_stop<2;late_stop++){
  setup(powered,stop);enable_ret=err?-EIO:0;flip_stop=late_stop;struct result a=snapshot(old_spi_hid_power_up(&active));cleanup();setup(powered,stop);enable_ret=err?-EIO:0;flip_stop=late_stop;struct result b=snapshot(spi_hid_power_up(&active));same(a,b);cleanup();power_cases++;
 }
 for(int stop=0;stop<2;stop++)for(int powered=0;powered<2;powered++)for(int err=0;err<2;err++){
  setup(powered,stop);disable_ret=err?-EIO:0;struct result a=snapshot(old_spi_hid_power_down(&active));cleanup();setup(powered,stop);disable_ret=err?-EIO:0;struct result b=snapshot(spi_hid_power_down(&active));same(a,b);cleanup();power_cases++;
 }
 assert(output_cases==60&&power_cases==24);
 pthread_t a,b;
 /* Existing write must finish before the rail is disabled. */
 for(int old=0;old<2;old++){setup(true,false);use_old=old;block_spi=true;assert(!pthread_create(&a,NULL,writer,NULL));wait_flag(&spi_entered);assert(!pthread_create(&b,NULL,down,NULL));if(old){assert(!pthread_join(b,NULL));assert(overlap==1);}else{wait_flag(&down_waiting);assert(disable_calls==0&&physical);}signal_release(false);assert(!pthread_join(a,NULL));if(!old)assert(!pthread_join(b,NULL));assert(writer_result==0&&down_result==0&&!physical&&!active.powered);if(!old)assert(overlap==0);cleanup();}
 /* A power-up in flight cannot leak an enabled rail past power-down. */
 for(int old=0;old<2;old++){setup(false,false);use_old=old;block_enable=true;assert(!pthread_create(&a,NULL,up,NULL));wait_flag(&enable_entered);assert(!pthread_create(&b,NULL,down,NULL));if(old){assert(!pthread_join(b,NULL));assert(!disable_calls);}else wait_flag(&down_waiting);signal_release(true);assert(!pthread_join(a,NULL));if(!old)assert(!pthread_join(b,NULL));assert(up_result==0&&down_result==0);if(old)assert(physical&&active.powered);else assert(!physical&&!active.powered&&disable_calls==1);cleanup();}
 /* Reset cannot overwrite a normal request's in-flight packet. */
 for(int old=0;old<2;old++){setup(true,false);use_old=old;mode=3;block_spi=true;assert(!pthread_create(&a,NULL,normal,NULL));wait_flag(&spi_entered);memcpy(saved,&active.output,18);assert(!pthread_create(&b,NULL,reset,NULL));if(old)wait_flag(&second_spi);else wait_flag(&reset_waiting);if(old)assert(memcmp(saved,&active.output,18));else assert(!memcmp(saved,&active.output,18));signal_release(false);assert(!pthread_join(a,NULL));assert(!pthread_join(b,NULL));assert(writer_result==0&&spi_calls==2);assert(payload_changed==(unsigned)old);cleanup();}
 /* Input drain completes without needing the output mutex. */
 setup(true,false);use_old=false;mode=4;assert(!pthread_create(&a,NULL,down,NULL));wait_flag(&drain_waiting);assert(!active.powered&&disable_calls==0);assert(pthread_mutex_trylock(&active.output_lock)==EBUSY);assert(!pthread_mutex_lock(&active.input_lock));assert(!pthread_mutex_unlock(&active.input_lock));assert(!pthread_mutex_lock(&control));release_input=true;pthread_cond_broadcast(&condition);assert(!pthread_mutex_unlock(&control));assert(!pthread_join(a,NULL));assert(!physical);cleanup();
 /* Permanent stop still rejects writes when regulator-disable fails. */
 setup(true,true);disable_ret=-EIO;assert(spi_hid_power_down(&active)==-EIO&&active.powered);assert(spi_hid_output(&active,raw,10)==-ESHUTDOWN&&spi_calls==0);cleanup();
 printf("%u output cases and %u unchanged power cases passed; controlled write/power-down, power-up/power-down, shared-packet, input-drain and failed-power-off scenarios passed; old ordering witnesses reproduced\n",output_cases,power_cases);
}
'''
(out/'output-power-harness.c').write_text(prelude+'\n'+functions+'\n'+tests)
patch=''
for suffix,before,after in [('c',old,new),('h',oh,nh)]:
 name='drivers/hid/spi-hid/spi-hid-core.'+suffix;patch+='diff --git a/'+name+' b/'+name+'\n'+''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
(out/'output-power.patch').write_text(patch)
steps=[('harness-build',['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-pthread',str(out/'output-power-harness.c'),'-o',str(out/'output-power-harness')]),('harness-run',[str(out/'output-power-harness')]),('compile',['make','-j4','drivers/hid/spi-hid/spi-hid.o']),('checkpatch',['perl','scripts/checkpatch.pl','--no-tree','--strict','--no-signoff',str(out/'output-power.patch')]),('diff-check',['git','diff','--check'])]
for label,args in steps:
 with (out/(label+'.log')).open('wb') as f:r=subprocess.run(args,cwd=repo,stdout=f,stderr=subprocess.STDOUT,timeout=180)
 assert r.returncode==0,(label,r.returncode,(out/(label+'.log')).read_text()[-4500:])
assert not re.search(r'warning:|error:',(out/'compile.log').read_text(),re.I)
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==current and (repo/'.config').read_bytes()==(out/'config').read_bytes()
shutil.copy2(repo/'drivers/hid/spi-hid/spi-hid.o',out/'spi-hid.tested.o')
report={'only_delta_output_power_mutex_reset_buffer_ownership_and_initialization':True,'output_cases':60,'unchanged_power_cases':24,'controlled_interleaving_and_shutdown_gate_scenarios_passed':True,'sanitizers_passed':True,'native_compile_exit_code':0,'compiler_warnings':0,'style_exit_code':0,'driver_sha256':sha(out/'spi-hid-core.c'),'header_sha256':sha(out/'spi-hid-core.h'),'source_diff_sha256':sha(out/'source.diff'),'config_unchanged':True,'other_tracked_chunks_unchanged':True,'boot_or_live_device_changes_performed':False,'limits':['SPI/regulator/workqueue interfaces are mocked; thread ordering checks are not hardware or exhaustive concurrency proof.','Response ownership while sync_request releases the request mutex remains an inherited separate issue.','No new input transfer, reset timing, retry budget, bootstrap or audio policy is introduced.']}
(out/'independent-review.json').write_text(json.dumps(report,indent=2)+'\n');dest=run/'output-power-lock-candidate-20261001';assert not dest.exists();shutil.copytree(out,dest);h={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()};(dest/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(dest/n)==v for n,v in h.items());os.sync();print((out/'harness-run.log').read_text());print(json.dumps(report|{'archive_files':len(h),'archive_manifest_sha256':sha(dest/'sha256.json')},indent=2))
