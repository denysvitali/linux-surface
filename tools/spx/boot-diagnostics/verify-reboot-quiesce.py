#!/usr/bin/python3
"""Verify actual SPI bus shutdown dispatch and SPI-HID callback teardown."""
import ast,difflib,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
os.umask(0o077);os.environ['GIT_OPTIONAL_LOCKS']='0'
repo=Path('/home/dvitali/Documents/git/linux-surface-next');out=Path('/var/tmp/spx-reboot-quiesce-20261001');run=Path('/var/lib/spx-boot-diagnostics/attempts/20260930al')
assert os.geteuid()==0 and not (out/'independent-review.json').exists()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def function(s,name):
 m=re.search(r'^static [^;{}]*\b'+name+r'\([^;{}]*\)\n\{',s,re.M);assert m,name
 pos=m.end();depth=1
 while depth:depth+=(s[pos]=='{')-(s[pos]=='}');pos+=1
 return s[m.start():pos]
old=(out/'spi-hid-core.before.c').read_text();new=(repo/'drivers/hid/spi-hid/spi-hid-core.c').read_text();callback=function(new,'spi_hid_spi_shutdown')
assert new.replace(callback+'\n\n','',1).replace('\t.shutdown\t= spi_hid_spi_shutdown,\n','',1)==old
assert sha(repo/'drivers/hid/spi-hid/spi-hid-core.h')==sha(run/'output-power-lock-candidate-20261001/spi-hid-core.h')
assert (repo/'.config').read_bytes()==(out/'config').read_bytes()
current=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)
def chunks(b):return {s.split(b'\n',1)[0]:s for s in re.split(b'(?=^diff --git )',b,flags=re.M) if s.startswith(b'diff --git ')}
a=chunks((out/'source-before.diff').read_bytes());b=chunks(current);key=b'diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c';assert {k:v for k,v in a.items() if k!=key}=={k:v for k,v in b.items() if k!=key}
(out/'spi-hid-core.c').write_text(new);(out/'source.diff').write_bytes(current);shutil.copy2(__file__,out/Path(__file__).name);shutil.copy2(repo/'drivers/hid/spi-hid/spi-hid-core.h',out/'spi-hid-core.h')
# Reuse the controlled publisher fixture, exercising the final unchanged teardown.
t=ast.parse((repo/'tools/spx/boot-diagnostics/verify-hid-publisher-stop.py').read_text())
def literal(name):return ast.literal_eval(next(n.value for n in t.body if isinstance(n,ast.Assign) and any(isinstance(v,ast.Name) and v.id==name for v in n.targets)))
prelude=literal('prelude').replace('struct device {struct', 'struct device_driver;\nstruct device {struct device_driver *driver;struct').replace('struct spi_device {struct device dev;int irq;};','struct spi_device {struct device dev;int irq;void *data;};')
prelude=prelude.replace('static bool initial_hid,disable_fails;', 'static bool initial_hid,disable_fails,shutdown_context;').replace('return &active.error_work;', 'return shutdown_context?NULL:&active.error_work;')
extra=r'''
struct device_driver {int unused;};
struct spi_driver {struct device_driver driver;void (*shutdown)(struct spi_device *);};
#define to_spi_driver(p) container_of(p,struct spi_driver,driver)
#define to_spi_device(p) container_of(p,struct spi_device,dev)
static unsigned marker_begin,marker_complete;
static void *spi_get_drvdata(struct spi_device *p){assert(p==&spi&&p->data==&active);return p->data;}
static void info(struct device *d,const char *s){assert(d==&spi.dev);if(!strcmp(s,"SPX: shutdown quiesce begin\n")){assert(!marker_begin&&!freed);marker_begin++;}else {assert(!strcmp(s,"SPX: shutdown quiesce complete\n")&&marker_begin==1&&!marker_complete&&freed==1&&!active.irq_enabled&&!active.hid);marker_complete++;}}
#define dev_info(d,s) info(d,s)
'''
functions='\n'.join(function(new,n) for n in ('spi_hid_disconnect_hid','spi_hid_stop_hid','spi_hid_schedule_error','spi_hid_error_handler','spi_hid_error_work','spi_hid_shutdown'))+'\n'+callback+'\n'+function((repo/'drivers/spi/spi.c').read_text(),'spi_shutdown')
setup=literal('tests').split('int main(void)',1)[0]
setup=setup.replace('publisher,&active.create_device_work));if(refresh==2)', 'publisher,&active.create_device_work));\n if(refresh==2)')
tests=setup+r'''
int main(void){unsigned cases=0;struct spi_driver driver={.shutdown=spi_hid_spi_shutdown};
 for(int present=0;present<2;present++)for(int create=0;create<3;create++)for(int refresh=0;refresh<3;refresh++)for(int fail=0;fail<2;fail++)for(int path=0;path<4;path++){
  setup(present,create,refresh,fail);marker_begin=marker_complete=0;spi.data=&active;spi.dev.driver=&driver.driver;
  if(path==0)spi_hid_stop_hid(&active);else if(path==1)spi_hid_error_work(&active.error_work);else {shutdown_context=true;if(path==2)spi_hid_shutdown(&active);else spi_shutdown(&spi.dev);}
  assert(active.stopping&&!active.hid&&!stale_access&&active.create_device_work.state==0&&active.refresh_device_work.state==0&&!active.create_device_work.pending&&!active.refresh_device_work.pending);
  assert(cancels[2]>=1&&cancels[3]>=1&&destroyed==(unsigned)(present||create==2));spi_hid_schedule_error(&active);assert(!queued);
  if(path>=2)assert(freed==1&&!active.irq_enabled&&active.powered==(bool)fail);
  assert(marker_begin==(unsigned)(path==3)&&marker_complete==marker_begin);cleanup();cases++;
 }
 for(int missing=0;missing<2;missing++){setup(true,0,0,false);marker_begin=marker_complete=0;shutdown_context=true;spi.data=&active;driver.shutdown=NULL;spi.dev.driver=missing?NULL:&driver.driver;spi_shutdown(&spi.dev);assert(!active.stopping&&active.hid&&!freed&&!marker_begin&&!marker_complete);cleanup();}
 assert(cases==144);printf("%u actual stop/abort/shutdown/SPI-dispatch cases and 2 absent-driver/callback cases passed; correct drvdata, two ordered markers, drained publishers and IRQ teardown verified, including failed power-off\n",cases);
}
'''
(out/'reboot-quiesce-harness.c').write_text(prelude+'\n'+extra+'\n'+functions+'\n'+tests)
(out/'reboot-quiesce.patch').write_text('diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c\n'+''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/drivers/hid/spi-hid/spi-hid-core.c',tofile='b/drivers/hid/spi-hid/spi-hid-core.c')))
steps=[('harness-build',['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-pthread',str(out/'reboot-quiesce-harness.c'),'-o',str(out/'reboot-quiesce-harness')]),('harness-run',[str(out/'reboot-quiesce-harness')]),('compile',['make','-j4','drivers/hid/spi-hid/spi-hid.o']),('checkpatch',['perl','scripts/checkpatch.pl','--no-tree','--strict','--no-signoff',str(out/'reboot-quiesce.patch')]),('diff-check',['git','diff','--check'])]
for label,args in steps:
 with (out/(label+'.log')).open('wb') as f:r=subprocess.run(args,cwd=repo,stdout=f,stderr=subprocess.STDOUT,timeout=180)
 assert r.returncode==0,(label,r.returncode,(out/(label+'.log')).read_text()[-4000:])
assert not re.search(r'warning:|error:',(out/'compile.log').read_text(),re.I)
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=repo)==current and (repo/'.config').read_bytes()==(out/'config').read_bytes()
shutil.copy2(repo/'drivers/hid/spi-hid/spi-hid.o',out/'spi-hid.tested.o');shutil.copy2(repo/'drivers/spi/spi.c',out/'spi-core.c')
report={'only_delta_callback_registration_and_two_outgoing_markers':True,'actual_dispatch_cleanup_cases':144,'absent_driver_or_callback_cases':2,'sanitizers_passed':True,'native_compile_exit_code':0,'compiler_warnings':0,'style_exit_code':0,'driver_sha256':sha(out/'spi-hid-core.c'),'header_sha256':sha(out/'spi-hid-core.h'),'source_diff_sha256':sha(out/'source.diff'),'config_and_other_tracked_chunks_unchanged':True,'callback_executed_on_hardware':False,'boot_payloads_installed_or_selected':False,'limits':['Workqueue, publishers, HID and power-down effects are modeled; real output/power ordering was tested separately with extracted functions.','Two completion markers show software callback progress, not electrical power-off success or a touch startup fix.','Actual outgoing callback and log persistence across reboot remain hardware checkpoints.']}
(out/'independent-review.json').write_text(json.dumps(report,indent=2)+'\n');dest=run/'reboot-quiesce-candidate-20261001';assert not dest.exists();shutil.copytree(out,dest);h={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()};(dest/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(dest/n)==v for n,v in h.items());os.sync();print((out/'harness-run.log').read_text());print(json.dumps(report|{'archive_files':len(h),'archive_manifest_sha256':sha(dest/'sha256.json')},indent=2))
