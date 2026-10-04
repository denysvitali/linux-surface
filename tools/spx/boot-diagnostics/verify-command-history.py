#!/usr/bin/python3
"""Verify actual C history helpers and the isolated no-new-I/O source delta."""
import hashlib,json,os,re,subprocess
from pathlib import Path
os.umask(0o077)
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
OLD=Path('/var/lib/spx-boot-diagnostics/attempts/20260930ah/post-result-records')
OUT=Path('/var/tmp/spx-command-history-review-20260930')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^\n]*\b'+name+r'\([^;]*?\)\n\{',s,re.M);assert m,name
 start=m.start();pos=m.end();depth=1
 while depth:
  if s[pos]=='{':depth+=1
  if s[pos]=='}':depth-=1
  pos+=1
 return s[start:pos]
def chunks(s):return {p.split(b'\n',1)[0]:p for p in re.split(b'(?=^diff --git )',s,flags=re.M) if p.startswith(b'diff --git ')}
assert os.geteuid()==0 and not (OUT/'independent-review.json').exists()
old=(OLD/'qcom-before.c').read_text();new=(REPO/'drivers/soundwire/qcom.c').read_text()
assert (OUT/'qcom.c').read_text()==new and sha(REPO/'.config')==sha(OLD/'config-before')
compile_result=json.loads((OUT/'compile-result.json').read_text())
assert compile_result['exit_code']==0 and compile_result['driver_sha256']==sha(REPO/'drivers/soundwire/qcom.c')
assert not re.search(r'warning:|error:',(OUT/'compile.log').read_text(),re.I)
before=chunks((OLD/'source-before.diff').read_bytes());current=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO,env=os.environ|{'GIT_OPTIONAL_LOCKS':'0'})
after=chunks(current);key=b'diff --git a/drivers/soundwire/qcom.c b/drivers/soundwire/qcom.c'
assert {k:v for k,v in before.items() if k!=key}=={k:v for k,v in after.items() if k!=key}
assert (OUT/'source.diff').read_bytes()==current
names=('spx_cmd_diag_record','spx_cmd_diag_snapshot','spx_cmd_diag_print')
helpers='\n\n'.join(function(new,n) for n in names)
assert not re.search(r'regmap_|reg_read\(|reg_write\(|[um]delay|[fm]sleep|usleep|wait_for_|schedule',helpers)
assert 'static bool spx_cmd_diag;' in new and 'module_param(spx_cmd_diag, bool, 0444);' in new
assert 'ctrl->spx_cmd_diag_enabled = spx_cmd_diag &&\n\t\tof_machine_is_compatible("microsoft,surface-pro-x");' in new
assert '#define SPX_CMD_DIAG_RECORDS 16' in new and '#define SPX_CMD_DIAG_DUMPS 2' in new
for name in ('qcom_swrm_cmd_fifo_wr_cmd','qcom_swrm_cmd_fifo_rd_cmd','__qcom_swrm_ahb_reg_write','qcom_swrm_xfer_msg'):
 assert function(old,name)==function(new,name),name
wrapper=function(new,'qcom_swrm_ahb_reg_write')
assert wrapper.replace('\n\tspx_cmd_diag_record(ctrl, reg, val, ret);','')==function(old,'qcom_swrm_ahb_reg_write')
assert wrapper.index('ret = __qcom_swrm_ahb_reg_write')<wrapper.index('spx_cmd_diag_record')<wrapper.index('mutex_unlock')
irq_new=function(new,'qcom_swrm_irq_handler');irq_old=function(old,'qcom_swrm_irq_handler')
start=irq_new.index('case SWRM_INTERRUPT_STATUS_CMD_ERROR:');end=irq_new.index('case SWRM_INTERRUPT_STATUS_DOUT_PORT_COLLISION:',start)
segment=irq_new[start:end]
assert segment.index('spx_cmd_diag_snapshot')<segment.index('ctrl->reg_read')
assert segment.index('ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, 0x1);')<segment.index('spx_cmd_diag_print')
segment=segment.replace('\n\t\t\t{','',1).replace('\n\t\t\t\tstruct spx_cmd_diag_record snapshot[SPX_CMD_DIAG_RECORDS];','').replace('\n\t\t\t\tunsigned int count;\n','').replace('\n\t\t\t\tcount = spx_cmd_diag_snapshot(ctrl, snapshot);','').replace('\n\t\t\t\tspx_cmd_diag_print(ctrl, snapshot, count);','').replace('\n\t\t\t}\n','\n',1)
assert irq_new[:start]+segment+irq_new[end:]==irq_old
# Compile the exact helper bodies against a small userspace synchronization shim.
struct=re.search(r'struct spx_cmd_diag_record \{.*?\n\};',new,re.S)[0]
harness=r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
typedef uint64_t u64;
typedef uint32_t u32;
#define SPX_CMD_DIAG_RECORDS 16
#define SPX_CMD_DIAG_DUMPS 2
#define SWRM_REG_CMD_FIFO_WR_CMD 0
#define SWRM_REG_CMD_FIFO_RD_CMD 1
#define spin_lock_irqsave(lock, flags) do { (flags)=0; assert(!pthread_mutex_lock(lock)); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); assert(!pthread_mutex_unlock(lock)); } while (0)
static uint64_t ktime_get_ns(void) { static atomic_uint_fast64_t n; return atomic_fetch_add(&n,1); }
static unsigned log_lines;
static void dev_info(void *dev, const char *fmt,...) { (void)dev;(void)fmt;log_lines++; }
'''+struct+r'''
struct qcom_swrm_ctrl {
 void *dev; bool spx_cmd_diag_enabled; pthread_mutex_t spx_cmd_diag_lock;
 unsigned reg_layout[2]; struct spx_cmd_diag_record spx_cmd_history[16];
 u64 spx_cmd_sequence; unsigned spx_cmd_head,spx_cmd_count,spx_cmd_dumps_left;
};
'''+helpers+r'''
static void init(struct qcom_swrm_ctrl *c,bool enabled) {
 memset(c,0,sizeof(*c)); assert(!pthread_mutex_init(&c->spx_cmd_diag_lock,0));
 c->spx_cmd_diag_enabled=enabled;c->reg_layout[0]=0x300;c->reg_layout[1]=0x304;c->spx_cmd_dumps_left=2;
}
static struct qcom_swrm_ctrl shared;
static void *writer(void *p) {
 unsigned base=(uintptr_t)p;
 for(unsigned i=0;i<10000;i++) spx_cmd_diag_record(&shared,i&1?0x300:0x304,base+i,-7);
 return 0;
}
int main(void) {
 struct qcom_swrm_ctrl c; struct spx_cmd_diag_record s[16],saved[16];unsigned n;
 init(&c,false);spx_cmd_diag_record(&c,0x300,0x123,0);assert(!c.spx_cmd_sequence&&!c.spx_cmd_count);assert(!spx_cmd_diag_snapshot(&c,s)&&c.spx_cmd_dumps_left==2);
 pthread_mutex_destroy(&c.spx_cmd_diag_lock);
 init(&c,true);spx_cmd_diag_record(&c,0x999,1,0);assert(!c.spx_cmd_sequence);assert(!spx_cmd_diag_snapshot(&c,s));assert(c.spx_cmd_dumps_left==1);
 pthread_mutex_destroy(&c.spx_cmd_diag_lock);
 init(&c,true);
 for(unsigned i=1;i<=35;i++) spx_cmd_diag_record(&c,i&1?0x300:0x304,i,(int)i-20);
 n=spx_cmd_diag_snapshot(&c,s);assert(n==16);
 for(unsigned i=0;i<n;i++){assert(s[i].sequence==i+20&&s[i].packed==i+20&&s[i].bridge_result==(int)i);assert(s[i].read==((i+20)%2==0));}
 memcpy(saved,s,sizeof(s));spx_cmd_diag_print(&c,s,n);assert(log_lines==17);
 for(unsigned i=36;i<=70;i++)spx_cmd_diag_record(&c,0x300,i,0);
 assert(!memcmp(saved,s,sizeof(s)));n=spx_cmd_diag_snapshot(&c,s);assert(n==16&&s[0].sequence==55&&s[15].sequence==70);spx_cmd_diag_print(&c,s,n);assert(log_lines==34);
 assert(!spx_cmd_diag_snapshot(&c,s));spx_cmd_diag_print(&c,s,0);assert(log_lines==34);
 pthread_mutex_destroy(&c.spx_cmd_diag_lock);
 init(&shared,true);pthread_t a,b;assert(!pthread_create(&a,0,writer,(void *)100));assert(!pthread_create(&b,0,writer,(void *)200));
 for(unsigned j=0;j<1000;j++){unsigned count=spx_cmd_diag_snapshot(&shared,s);for(unsigned i=1;i<count;i++)assert(s[i].sequence==s[i-1].sequence+1);}
 assert(!pthread_join(a,0)&&!pthread_join(b,0));assert(shared.spx_cmd_sequence==20000&&shared.spx_cmd_count==16);
 pthread_mutex_destroy(&shared.spx_cmd_diag_lock);puts("actual C helpers passed: default-off, empty/filtering, wrap, payload/return capture, immutable snapshot, concurrent writers/snapshot and34-line cap");
}
'''
(OUT/'history-harness.c').write_text(harness)
with (OUT/'harness-build.log').open('wb') as stream:
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-fsanitize=address,undefined','-g',str(OUT/'history-harness.c'),'-o',str(OUT/'history-harness')],stdout=stream,stderr=subprocess.STDOUT,check=True)
with (OUT/'harness-run.log').open('wb') as stream:
 subprocess.run([str(OUT/'history-harness')],stdout=stream,stderr=subprocess.STDOUT,check=True)
subprocess.run(['git','diff','--check'],cwd=REPO,env=os.environ|{'GIT_OPTIONAL_LOCKS':'0'},check=True)
report={'default_off_surface_only_read_only_selector':True,'native_object_compile_exit_code':0,'actual_C_helper_harness_sanitizers_passed':True,'no_diagnostic_register_access_or_delay':True,'fifo_submission_and_caller_returns_unchanged':True,'existing_irq_IO_order_unchanged_print_after_flush':True,'history_records':16,'dumps_per_controller':2,'maximum_printed_lines_per_controller':34,'other_source_diff_chunks_unchanged':True,'config_unchanged':True,'driver_sha256':sha(REPO/'drivers/soundwire/qcom.c'),'ah_post_result_manifest_sha256':sha(OLD/'sha256.json'),'hardware_trial_performed':False,'limits':['Timestamp is captured after the existing bridge submission returns, not a hardware completion time.','Recent software submissions and return codes do not identify the command responsible for an asynchronous error.','Default-off instrumentation still changes structure size; enabled history recording and printing can affect timing.']}
(OUT/'independent-review.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();print(json.dumps(report,indent=2))
