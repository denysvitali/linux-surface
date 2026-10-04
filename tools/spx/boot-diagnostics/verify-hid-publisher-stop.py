#!/usr/bin/python3
"""Exercise actual stop/abort/shutdown functions against controlled publishers."""
import difflib,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');out=Path('/var/tmp/spx-hid-publisher-stop-20261001');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al')
assert os.geteuid()==0 and not (out/'independent-review.json').exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
old=(out/'spi-hid-core.before.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text();assert new==old.replace(function(old,'spi_hid_stop_hid'),function(new,'spi_hid_stop_hid'),1)
assert new.count('spi_hid_stop_hid(shid)')==2
assert 'spi_hid_stop_hid(shid)' in function(new,'spi_hid_error_handler') and 'spi_hid_stop_hid(shid)' in function(new,'spi_hid_shutdown')
assert new.count('spi_hid_error_handler(shid)')==1
assert (repo/'.config').read_bytes()==(out/'config').read_bytes()
current=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)
def chunks(b):return {s.split(b'\n',1)[0]:s for s in re.split(b'(?=^diff --git )',b,flags=re.M) if s.startswith(b'diff --git ')}
a=chunks((out/'source-before.diff').read_bytes());b=chunks(current);key=b'diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c';assert {k:v for k,v in a.items() if k!=key}=={k:v for k,v in b.items() if k!=key}
(out/'spi-hid-core.c').write_text(new);(out/'source.diff').write_bytes(current);shutil.copy2(__file__,out/Path(__file__).name)
prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <pthread.h>
#include <errno.h>
#define SPI_HID_MAX_RESET_ATTEMPTS 3
#define SPI_HID_SOFT_RETRY_ATTEMPTS 5
#define SPI_HID_POWER_MODE_OFF 3
#define SPI_HID_POWER_MODE_ACTIVE 1
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define dev_err(d,...) ((void)(d))
#define spin_lock_irqsave(l,f) do{(f)=0;assert(!pthread_mutex_lock(l));}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(f);assert(!pthread_mutex_unlock(l));}while(0)
struct device {struct {int unused;} kobj;};
struct spi_device {struct device dev;int irq;};
struct hid_device {int id;};
struct work_struct {int id,state;bool pending,permit;pthread_t thread;};
struct spi_hid {pthread_mutex_t input_lock;struct spi_device *spi;struct hid_device *hid;bool stopping,powered,startup_active,ready,irq_enabled;unsigned attempts,power_state;struct work_struct create_device_work,refresh_device_work,reset_work,error_work;void *pinctrl,*pinctrl_reset,*pinctrl_active;};
static struct spi_hid active;
static struct hid_device original={1},replacement={2};
static struct spi_device spi;
static pthread_mutex_t control=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static unsigned stale_access,destroyed,cancels[5],queued,freed;
static bool initial_hid,disable_fails;
static struct work_struct *current_work(void){return &active.error_work;}
static void *publisher(void *arg){struct work_struct *w=arg;assert(!pthread_mutex_lock(&control));while(!w->permit)assert(!pthread_cond_wait(&condition,&control));assert(!pthread_mutex_unlock(&control));
 /* This models a publisher that passed its entry gate before stop began. */
 if(initial_hid){if(active.hid!=&original)stale_access++;}else if(w->id==2){active.hid=&replacement;}
 return NULL;
}
static void release_running(struct work_struct *w){if(w->state!=2)return;assert(!pthread_mutex_lock(&control));w->permit=true;assert(!pthread_cond_broadcast(&condition));assert(!pthread_mutex_unlock(&control));assert(!pthread_join(w->thread,NULL));w->state=0;}
static bool cancel_work_sync(struct work_struct *w){assert(w!=current_work());cancels[w->id]++;bool pending=w->pending;w->pending=false;release_running(w);w->state=0;return pending;}
static bool cancel_work(struct work_struct *w){cancels[w->id]++;bool pending=w->pending;w->pending=false;return pending;}
static bool schedule_work(struct work_struct *w){assert(!active.stopping);queued++;bool fresh=!w->pending;w->pending=true;return fresh;}
static void hid_destroy_device(struct hid_device *h){assert(h&&active.create_device_work.state!=2&&active.refresh_device_work.state!=2);destroyed++;}
static int spi_hid_power_down(struct spi_hid *s){s->powered=disable_fails;s->startup_active=false;return disable_fails?-EIO:0;}
static void sysfs_notify(void *p,void *q,const char *n){(void)p;(void)q;(void)n;}
static void usleep_range(unsigned a,unsigned b){(void)a;(void)b;}
static int pinctrl_select_state(void *p,void *s){(void)p;(void)s;return 0;}
static void msleep(unsigned n){(void)n;}
static void free_irq(int n,void *p){(void)n;(void)p;assert(!active.hid&&active.create_device_work.state!=2&&active.refresh_device_work.state!=2);freed++;}
'''
# Shutdown cancels its own error item from process context, not from error_work.
prelude=prelude.replace('static bool initial_hid,disable_fails;', 'static bool initial_hid,disable_fails,shutdown_context;').replace('return &active.error_work;', 'return shutdown_context?NULL:&active.error_work;')
functions=function(new,'spi_hid_disconnect_hid')+'\n'+function(old,'spi_hid_stop_hid').replace('spi_hid_stop_hid(', 'old_stop_hid(',1)+'\n'+function(new,'spi_hid_stop_hid')+'\n'+function(new,'spi_hid_schedule_error')+'\n'+function(new,'spi_hid_error_handler')+'\n'+function(new,'spi_hid_error_work')+'\n'+function(new,'spi_hid_shutdown')
tests=r'''
static void setup(bool present,int create,int refresh,bool fail){
 memset(&active,0,sizeof(active));assert(!pthread_mutex_init(&active.input_lock,NULL));active.spi=&spi;spi.irq=227;active.hid=present?&original:NULL;active.powered=true;active.ready=true;active.irq_enabled=true;active.power_state=1;active.attempts=3;initial_hid=present;disable_fails=fail;shutdown_context=false;
 stale_access=destroyed=queued=freed=0;memset(cancels,0,sizeof(cancels));active.reset_work.id=1;active.error_work.id=4;active.create_device_work.id=2;active.refresh_device_work.id=3;
 active.create_device_work.state=create;active.refresh_device_work.state=refresh;active.create_device_work.pending=create==1;active.refresh_device_work.pending=refresh==1;
 if(create==2)assert(!pthread_create(&active.create_device_work.thread,NULL,publisher,&active.create_device_work));
 if(refresh==2)assert(!pthread_create(&active.refresh_device_work.thread,NULL,publisher,&active.refresh_device_work));
}
static void cleanup(void){release_running(&active.create_device_work);release_running(&active.refresh_device_work);assert(!pthread_mutex_destroy(&active.input_lock));}
int main(void){unsigned cases=0,old_stale_cases=0,old_live_cases=0;
 for(int present=0;present<2;present++)for(int create=0;create<3;create++)for(int refresh=0;refresh<3;refresh++)for(int fail=0;fail<2;fail++){
  setup(present,create,refresh,fail);old_stop_hid(&active);release_running(&active.create_device_work);release_running(&active.refresh_device_work);old_stale_cases+=stale_access!=0;old_live_cases+=active.hid!=NULL||active.create_device_work.pending||active.refresh_device_work.pending;cleanup();
  for(int path=0;path<3;path++){
   setup(present,create,refresh,fail);if(path==0)spi_hid_stop_hid(&active);else if(path==1)spi_hid_error_work(&active.error_work);else {shutdown_context=true;spi_hid_shutdown(&active);}
   assert(active.stopping&&!active.hid&&!stale_access&&active.create_device_work.state==0&&active.refresh_device_work.state==0&&!active.create_device_work.pending&&!active.refresh_device_work.pending);
   assert(cancels[2]>=1&&cancels[3]>=1);assert(destroyed==(unsigned)(present||create==2));spi_hid_schedule_error(&active);assert(!queued);
   if(path==1){assert(active.attempts==4&&active.powered==(bool)fail);}if(path==2){assert(freed==1&&!active.irq_enabled&&active.powered==(bool)fail);}
   cleanup();cases++;
  }
 }
 assert(cases==108&&old_stale_cases>0&&old_live_cases>0);printf("%u actual stop/abort/shutdown cases passed with idle/pending/running publishers, absent/present HID, and power-off failure; old order produced %u stale-pointer cases and %u surviving-publication cases\n",cases,old_stale_cases,old_live_cases);
}
'''
(out/'publisher-stop-harness.c').write_text(prelude+'\n'+functions+'\n'+tests)
(out/'publisher-stop.patch').write_text('diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c\n'+''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/drivers/hid/spi-hid/spi-hid-core.c',tofile='b/drivers/hid/spi-hid/spi-hid-core.c')))
steps=[('harness-build',['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-pthread',str(out/'publisher-stop-harness.c'),'-o',str(out/'publisher-stop-harness')]),('harness-run',[str(out/'publisher-stop-harness')]),('compile',['make','-j4','drivers/hid/spi-hid/spi-hid.o']),('checkpatch',['perl','scripts/checkpatch.pl','--no-tree','--strict','--no-signoff',str(out/'publisher-stop.patch')]),('diff-check',['git','diff','--check'])]
for label,args in steps:
 with (out/(label+'.log')).open('wb') as f:r=subprocess.run(args,cwd=repo,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==0,(label,r.returncode,(out/(label+'.log')).read_text()[-4000:])
assert not re.search(r'warning:|error:',(out/'compile.log').read_text(),re.I)
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==current and (repo/'.config').read_bytes()==(out/'config').read_bytes()
shutil.copy2(repo/'drivers/hid/spi-hid/spi-hid.o',out/'spi-hid.tested.o')
report={'only_delta_is_stopping_gate_and_publisher_drain_before_disconnect':True,'direct_stop_callers_are_error_worker_and_external_shutdown':True,'actual_stop_abort_shutdown_cases':108,'sanitizers_passed':True,'native_compile_exit_code':0,'compiler_warnings':0,'style_exit_code':0,'config_and_other_tracked_source_unchanged':True,'driver_sha256':sha(out/'spi-hid-core.c'),'source_diff_sha256':sha(out/'source.diff'),'config_sha256':sha(out/'config'),'boot_artifacts_installed_or_live_device_operations':False,'limits':['Publisher behavior, workqueue and HID interfaces are modeled; tests do not prove all kernel interleavings.','Terminal abort now permanently stops new work/opens, including if power-off fails.','AL no-IRQ initial-probe failure remains unresolved; no new shutdown callback, reset retry or bootstrap is implemented.']}
(out/'independent-review.json').write_text(json.dumps(report,indent=2)+'\n');dest=run/'hid-publisher-stop-candidate-20261001';assert not dest.exists();shutil.copytree(out,dest);h={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()};(dest/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(dest/n)==v for n,v in h.items());os.sync();print((out/'harness-run.log').read_text());print(json.dumps(report|{'archive_files':len(h),'archive_manifest_sha256':sha(dest/'sha256.json')},indent=2))
