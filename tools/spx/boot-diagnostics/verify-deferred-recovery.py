#!/usr/bin/python3
"""Verify four recovery callers, unchanged success paths, and stopping publication."""
import ast,difflib,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');out=Path('/var/tmp/spx-deferred-recovery-20261001');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al')
assert os.geteuid()==0 and not (out/'independent-review.json').exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
old=(out/'spi-hid-core.before.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text()
helper=function(new,'spi_hid_schedule_error')
expected=old.replace(function(old,'spi_hid_input_error'),function(old,'spi_hid_input_error')+'\n\n'+helper,1)
assert expected.count('\t\tspi_hid_error_handler(shid);\n')==2
expected=expected.replace('\t\tspi_hid_error_handler(shid);\n','\t\tspi_hid_schedule_error(shid);\n')
block='\t\tret = spi_hid_error_handler(shid);\n\t\tif (ret)\n\t\t\tdev_err(dev, "%s: error handler failed\\n", __func__);'
assert expected.count(block)==2;expected=expected.replace(block,'\t\tspi_hid_schedule_error(shid);')
expected=expected.replace('\t\tdev_err(dev, "response timed out\\n");\n\t\tspi_hid_schedule_error(shid);','\t\tdev_err(dev, "response timed out\\n");\n\t\t/* Recovery can wait for the worker or mutex of this caller. */\n\t\tspi_hid_schedule_error(shid);',1)
assert new==expected
assert (out/'config').read_bytes()==(repo/'.config').read_bytes()
current=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)
def chunks(b):return {s.split(b'\n',1)[0]:s for s in re.split(b'(?=^diff --git )',b,flags=re.M) if s.startswith(b'diff --git ')}
a=chunks((out/'source-before.diff').read_bytes());b=chunks(current);key=b'diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c'
assert {k:v for k,v in a.items() if k!=key}=={k:v for k,v in b.items() if k!=key}
assert new.count('spi_hid_error_handler(shid)')==1 and 'spi_hid_error_handler(shid)' in function(new,'spi_hid_error_work')
(out/'spi-hid-core.c').write_text(new);(out/'source.diff').write_bytes(current);shutil.copy2(__file__,out/Path(__file__).name)
prev=ast.parse((repo/'tools/spx/boot-diagnostics/verify-reset-self-wait.py').read_text())
prelude=ast.literal_eval(next(n.value for n in prev.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prelude' for t in n.targets)))
prelude=prelude.replace('struct spi_device {struct device dev;};','struct spi_device {struct device dev;int irq;};\nstruct hid_device {int ll_open_lock;unsigned ll_open_count;};\nstruct spi_hid_output_report {int unused;};\nstruct desc {unsigned hid_version;};\nstruct response {char content[16];};')
prelude=prelude.replace('struct spi_hid_output_buf output;','struct spi_hid_output_buf output;struct hid_device *hid;struct desc desc;struct response response;unsigned report_descriptor_crc32;bool irq_enabled,refresh_in_progress;unsigned logic_error_count;int logic_last_error,lock,output_done,ready_done;')
prelude=prelude.replace('static bool trapped,queued_rerun;','static bool trapped;\nstatic int waiting_on,send_ret,wait_ret,create_ret,descriptor_ret,crc_ret;\nstatic bool mutex_held;\nstatic struct hid_device hid;')
prelude=prelude.replace('if(w==current_work()){trapped=true;longjmp(self_wait,1);}', 'if(w==current_work()||(w->id==1&&(waiting_on==caller||(waiting_on==9&&mutex_held)))){trapped=true;longjmp(self_wait,1);}')
prelude=prelude.replace('static void spi_hid_stop_hid(struct spi_hid *s) {(void)s;record(4,0,0);}', 'static void spi_hid_stop_hid(struct spi_hid *s);')
prelude=prelude.replace('#define dev_err(d,...) ((void)(d))','#define dev_err(d,...) ((void)(d),log_stub(__VA_ARGS__))').replace('#define dev_dbg(d,...) ((void)(d))','#define dev_dbg(d,...) ((void)(d),log_stub(__VA_ARGS__))')
extra=r'''
static void log_stub(const char *format,...){(void)format;}
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define SPI_HID_SUPPORTED_VERSION 0x100
#define SPI_HID_DIAG_READY 3
#define trace_spi_hid_create_device_work(s) ((void)(s))
#define trace_spi_hid_refresh_device_work(s) ((void)(s))
#define msecs_to_jiffies(n) (n)
static struct hid_device *spi_hid_disconnect_hid(struct spi_hid *s){struct hid_device *h=s->hid;s->hid=NULL;record(4,0,0);return h;}
static void hid_destroy_device(struct hid_device *h){assert(h);record(15,0,0);}
static bool schedule_work(struct work_struct *w){assert(locked);bool changed=!w->pending;w->pending=true;record(16,w->id,changed);return changed;}
static void mutex_lock(int *l){if(l==&active.lock){assert(!mutex_held);mutex_held=true;}record(17,l==&active.lock,0);}
static void mutex_unlock(int *l){if(l==&active.lock){assert(mutex_held);mutex_held=false;}record(18,l==&active.lock,0);}
static int spi_hid_send_output_report(struct spi_hid *s,unsigned reg,struct spi_hid_output_report *r){(void)s;(void)r;record(19,reg,send_ret);return send_ret;}
static int wait_for_completion_interruptible_timeout(int *c,unsigned time){(void)c;record(20,time,wait_ret);return wait_ret;}
static int spi_hid_create_device(struct spi_hid *s){(void)s;record(21,0,create_ret);return create_ret;}
static void disable_irq(int n){record(22,n,0);}
static const char *spi_hid_power_mode_string(u8 s){(void)s;return "stub";}
static int spi_hid_report_descriptor_request(struct spi_hid *s){(void)s;record(23,0,descriptor_ret);return descriptor_ret;}
static u32 crc32_le(u32 seed,const unsigned char *p,size_t n){(void)seed;(void)p;(void)n;return crc_ret;}
static void complete_all(int *p){(void)p;record(24,0,0);}
static void cancel_delayed_work(void *p){(void)p;record(25,0,0);}
'''
prelude=prelude.replace('unsigned logic_error_count;', 'unsigned logic_error_count;int startup_work;')
names=['spi_hid_sync_request','spi_hid_reset_work','spi_hid_create_device_work','spi_hid_refresh_device_work']
functions=function(old,'spi_hid_stop_hid')+'\n'+function(old,'spi_hid_error_handler').replace('spi_hid_error_handler(', 'old_error_handler(',1)+'\n'+helper+'\n'+function(new,'spi_hid_error_handler')+'\n'+function(new,'spi_hid_error_work')
for n in names:
 functions+='\n'+function(old,n).replace(n+'(', 'old_'+n+'(',1).replace('spi_hid_error_handler(shid)','old_error_handler(shid)')+'\n'+function(new,n)
tests=r'''
struct result {struct trace trace;bool trapped,ready,powered,hid,pending;unsigned attempts,dir,state;int ret;};
static struct spi_device spi;
static void setup(int stop,int powered,int startup,int state,int attempts,int fault,int pending){
 memset(&active,0,sizeof(active));memset(&hid,0,sizeof(hid));active.spi=&spi;spi.irq=227;active.stopping=stop;active.powered=powered;active.startup_active=startup;active.power_state=state;active.attempts=attempts;active.ready=true;active.hid=&hid;active.irq_enabled=true;hid.ll_open_count=1;active.desc.hid_version=fault?0:SPI_HID_SUPPORTED_VERSION;
 active.reset_work.id=1;active.create_device_work.id=2;active.refresh_device_work.id=3;active.error_work.id=4;active.error_work.pending=pending;active.hid_desc_addr=1;active.pinctrl_reset=(void *)1;active.pinctrl_active=(void *)2;
 memset(&trace,0,sizeof(trace));locked=false;mutex_held=false;trapped=false;output_ret=fault?-EIO:0;send_ret=0;wait_ret=fault?0:1;flush_bits=0;create_ret=0;descriptor_ret=4;crc_ret=0;pin_ret=0;
}
static struct result snapshot(int ret){return (struct result){trace,trapped,active.ready,active.powered,active.hid!=NULL,active.error_work.pending,active.attempts,active.dir_count,active.power_state,ret};}
static struct result invoke(int origin,bool old){int ret=0;if(origin==0)mutex_held=true;
 if(!setjmp(self_wait))switch(origin){
 case 0:{struct spi_hid_output_report r={0};ret=old?old_spi_hid_sync_request(&active,1,&r):spi_hid_sync_request(&active,1,&r);break;}
 case 1:if(old)old_spi_hid_reset_work(&active.reset_work);else spi_hid_reset_work(&active.reset_work);break;
 case 2:if(old)old_spi_hid_create_device_work(&active.create_device_work);else spi_hid_create_device_work(&active.create_device_work);break;
 case 3:if(old)old_spi_hid_refresh_device_work(&active.refresh_device_work);else spi_hid_refresh_device_work(&active.refresh_device_work);break;}
 assert(!locked);return snapshot(ret);
}
static void same(struct result a,struct result b){assert(a.trapped==b.trapped&&a.ready==b.ready&&a.powered==b.powered&&a.hid==b.hid&&a.pending==b.pending&&a.attempts==b.attempts&&a.dir==b.dir&&a.state==b.state&&a.ret==b.ret&&!memcmp(&a.trace,&b.trace,sizeof(a.trace)));}
static unsigned count(int k,int id){unsigned n=0;for(unsigned i=0;i<trace.count;i++)n+=trace.events[i][0]==k&&(id<0||trace.events[i][1]==id);return n;}
int main(void){unsigned cases=0,old_cycles=0;int states[]={1,2,3};
 for(int origin=0;origin<4;origin++)for(int stop=0;stop<2;stop++)for(int power=0;power<2;power++)for(int startup=0;startup<2;startup++)for(int si=0;si<3;si++)for(int attempts=0;attempts<4;attempts++)for(int fault=0;fault<2;fault++)for(int pending=0;pending<2;pending++){
  caller=origin;waiting_on=origin==0?9:origin;setup(stop,power,startup,states[si],attempts,fault,pending);struct result a=invoke(origin,true);old_cycles+=a.trapped;
  setup(stop,power,startup,states[si],attempts,fault,pending);struct result b=invoke(origin,false);assert(!b.trapped&&b.attempts==(unsigned)((origin==2&&!fault&&!stop&&power)?0:attempts)&&count(3,-1)==0&&count(14,-1)==0);
  bool eligible=!stop&&power&&!startup&&states[si]!=3;
  bool path_fault=fault&&(origin==0||(!stop&&power&&(origin!=1||states[si]!=3)));
  assert(count(16,4)==(unsigned)(eligible&&path_fault));assert(b.pending==(bool)(pending||(eligible&&path_fault)));
  if(!fault)same(a,b);
  if(origin==0)assert(b.ret==(fault?-ETIMEDOUT:0));
  if(eligible&&path_fault){assert(b.ready==(origin==1?false:true));assert(b.hid);mutex_held=false;caller=4;waiting_on=-1;active.error_work.pending=false;spi_hid_error_work(&active.error_work);assert(!trapped&&!locked&&active.attempts==(unsigned)attempts+1);if(attempts>=3){assert(!active.hid&&count(3,2)==1&&count(3,3)==1);}else assert(count(3,1)==1);}
  cases++;
 }
 assert(cases==1536);assert(old_cycles>0);
 /* Request return behavior beyond timeout, and worker success/failure paths. */
 caller=0;waiting_on=-1;for(int send=0;send<2;send++)for(int wait=-1;wait<=1;wait++){
  setup(0,1,0,1,0,0,0);send_ret=send?-EIO:0;wait_ret=wait;struct result a=invoke(0,true);setup(0,1,0,1,0,0,0);send_ret=send?-EIO:0;wait_ret=wait;struct result b=invoke(0,false);assert(a.ret==b.ret);if(send||wait)same(a,b);
 }
 caller=2;for(int ret=-1;ret<=0;ret++){setup(0,1,0,1,0,0,0);create_ret=ret;struct result a=invoke(2,true);setup(0,1,0,1,0,0,0);create_ret=ret;struct result b=invoke(2,false);same(a,b);}
 caller=3;for(int desc=-1;desc<=4;desc++)for(int crc=0;crc<2;crc++)for(int create=-1;create<=0;create++){
  setup(0,1,0,1,0,0,0);descriptor_ret=desc;crc_ret=crc;create_ret=create;struct result a=invoke(3,true);setup(0,1,0,1,0,0,0);descriptor_ret=desc;crc_ret=crc;create_ret=create;struct result b=invoke(3,false);same(a,b);
 }
 printf("%u four-caller cases and 32 additional unchanged-path cases passed; %u old modeled wait cycles detected; fault callers return before queued recovery, gates/coalescing/budget verified\n",cases,old_cycles);
}
'''
(out/'recovery-harness.c').write_text(prelude+'\n'+extra+'\n'+functions+'\n'+tests)
publication=r'''
#include <assert.h>
#include <stdbool.h>
#include <pthread.h>
#include <stdio.h>
#include <sched.h>
struct work_struct {bool pending;};
struct spi_hid {pthread_mutex_t input_lock;bool stopping,powered,startup_active;unsigned power_state;struct work_struct error_work;};
#define SPI_HID_POWER_MODE_OFF 3
#define spin_lock_irqsave(l,f) do{(f)=0;assert(!pthread_mutex_lock(l));}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(f);assert(!pthread_mutex_unlock(l));}while(0)
static struct spi_hid shid={.input_lock=PTHREAD_MUTEX_INITIALIZER,.powered=true,.power_state=1};
static pthread_barrier_t start;
static unsigned queued;
static bool schedule_work(struct work_struct *w){assert(!shid.stopping);queued++;bool changed=!w->pending;w->pending=true;return changed;}
'''+helper+r'''
static void *publisher(void *unused){(void)unused;spi_hid_schedule_error(&shid);pthread_barrier_wait(&start);for(int i=0;i<20000;i++)spi_hid_schedule_error(&shid);return NULL;}
int main(void){assert(!pthread_barrier_init(&start,NULL,2));pthread_t thread;assert(!pthread_create(&thread,NULL,publisher,NULL));pthread_barrier_wait(&start);sched_yield();assert(!pthread_mutex_lock(&shid.input_lock));shid.stopping=true;assert(!pthread_mutex_unlock(&shid.input_lock));/* Existing shutdown cancels after setting stopping. */assert(!pthread_mutex_lock(&shid.input_lock));shid.error_work.pending=false;assert(!pthread_mutex_unlock(&shid.input_lock));assert(!pthread_join(thread,NULL));assert(!shid.error_work.pending&&queued>=1);for(int i=0;i<20000;i++)spi_hid_schedule_error(&shid);assert(!shid.error_work.pending);printf("Stopping/publication lock ordering passed with concurrent requests and 20000 post-stop requests; no work queued after cancellation\n");}
'''
(out/'publication-harness.c').write_text(publication)
(out/'deferred-recovery.patch').write_text('diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c\n'+''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/drivers/hid/spi-hid/spi-hid-core.c',tofile='b/drivers/hid/spi-hid/spi-hid-core.c')))
steps=[]
for n in ('recovery','publication'):
 steps.extend([(n+'-build',['cc','-D_XOPEN_SOURCE=700','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-pthread',str(out/(n+'-harness.c')),'-o',str(out/(n+'-harness'))]),(n+'-run',[str(out/(n+'-harness'))])])
steps.extend([('compile',['make','-j4','drivers/hid/spi-hid/spi-hid.o']),('checkpatch',['perl','scripts/checkpatch.pl','--no-tree','--strict','--no-signoff',str(out/'deferred-recovery.patch')]),('diff-check',['git','diff','--check'])])
for label,args in steps:
 with (out/(label+'.log')).open('wb') as f:r=subprocess.run(args,cwd=repo,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==0,(label,r.returncode,(out/(label+'.log')).read_text()[-4500:])
assert not re.search(r'warning:|error:',(out/'compile.log').read_text(),re.I)
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==current and (repo/'.config').read_bytes()==(out/'config').read_bytes()
shutil.copy2(repo/'drivers/hid/spi-hid/spi-hid.o',out/'spi-hid.tested.o')
report={'only_delta_four_deferred_callers_and_stopping_locked_gate':True,'direct_handler_only_called_by_error_work':True,'config_and_other_tracked_source_unchanged':True,'four_caller_cases':1536,'additional_unchanged_path_cases':32,'publication_shutdown_stress_passed':True,'sanitizers_passed':True,'native_compile_exit_code':0,'compiler_warnings':0,'style_exit_code':0,'driver_sha256':sha(out/'spi-hid-core.c'),'source_diff_sha256':sha(out/'source.diff'),'config_sha256':sha(out/'config'),'live_device_operations_or_deployment_performed':False,'limits':['Workqueue/HID/SPI interfaces and wait-cycle detection are modeled; tests are not exhaustive kernel concurrency or hardware proof.','Recovery is deferred and requests can coalesce; the existing error-worker budget applies per executed handler.','AL initial-probe timeout is not repaired; shutdown callback and bootstrap/reset policy are unchanged.']}
(out/'independent-review.json').write_text(json.dumps(report,indent=2)+'\n');dest=run/'deferred-recovery-candidate-20261001';assert not dest.exists();shutil.copytree(out,dest);h={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()};(dest/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(dest/n)==v for n,v in h.items());os.sync()
print((out/'recovery-run.log').read_text());print((out/'publication-run.log').read_text());print(json.dumps(report|{'archive_files':len(h),'archive_manifest_sha256':sha(dest/'sha256.json')},indent=2))
