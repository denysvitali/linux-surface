#!/usr/bin/python3
"""Exercise extracted AM guard bodies with controlled boot/state failures, without reboot."""
import ast,io,json,re,types
from pathlib import Path
SRC=Path(__file__).resolve().parent
class F:
 def __init__(self,name):self.name=str(name)
 def __truediv__(self,n):return F(self.name+'/'+n)
 def read_text(self):
  if self.name.endswith('/boot_id'):
   counts['bid']+=1
   return ('changed' if state.get('changed_late') and counts['bid']>1 else state['bid'])+'\n'
  if self.name=='/proc/cmdline':return state['cmdline']+'\n'
  if self.name=='/proc/uptime':return str(state['age'])+' 0\n'
  if self.name.endswith('exclude.conf'):return '[Unit]\nConditionKernelCommandLine='+state['exclude']+'\n'
  raise AssertionError(self.name)
 def exists(self):return state.get('marker',False)
 def open(self,mode):assert mode=='x';return Stream()
class Stream(io.StringIO):
 def fileno(self):return 123
 def close(self):pass
class OS:
 def uname(self):return types.SimpleNamespace(release=state['release'])
 def umask(self,n):pass
 def fsync(self,n):assert n==123
 def sync(self):pass
class Subprocess:
 def run(self,args,**kw):calls.append(args);return types.SimpleNamespace(returncode=0)
def recovery(a):
 if state.get('bad_recovery'):raise AssertionError('recovery mismatch')
 return {'saved_entry':'spx-known-good','next_entry':state['pending']}
def artifacts(a):
 if state.get('bad_artifact'):raise AssertionError('artifact mismatch')
def parent_pass(a):
 if state.get('bad_parent'):raise AssertionError('parent result mismatch')
def command(*args):assert args[:2]==('systemctl','show');return state['timer']
module=ast.parse((SRC/'an_boot_guard.py').read_text());pre=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='preboot')
ns={'Path':F,'os':OS(),'recovery':recovery,'artifacts':artifacts,'command':command,'parent_pass':parent_pass};exec(compile(ast.Module(body=[pre],type_ignores=[]),'actual-AN-preboot','exec'),ns)
def reset(preboot=True):
 global state,counts,calls
 state={'bid':'known' if preboot else 'trial','cmdline':'known cmd spx_attempt=20261001am' if preboot else 'BOOT_IMAGE=/spx-trial-20261001am/vmlinuz trial cmd','age':1000,'release':'AM-release','pending':'','exclude':'!spx_attempt=20261002an','timer':'inactive'};counts={'bid':0};calls=[]
def rejected(fn):
 try:fn()
 except AssertionError:return
 raise AssertionError('unsafe input was accepted')
a={'release':'AM-release','preboot_id':'known','preboot_cmdline':'known cmd spx_attempt=20261001am','release':'AM-release','cmdline':'trial cmd'}
reset();assert ns['preboot'](a)['saved_entry']=='spx-known-good'
prebad=[{'bid':'other'},{'release':'other'},{'cmdline':'wrong'},{'age':619.99},{'pending':'other'},{'timer':'active'},{'exclude':'wrong'},{'bad_recovery':True},{'bad_artifact':True},{'bad_parent':True},{'changed_late':True}]
for patch in prebad:reset();state.update(patch);rejected(lambda:ns['preboot'](a))
reset();state['pending']='spx-trial-20261002an';assert ns['preboot'](a,'spx-trial-20261002an')['next_entry']==state['pending']
# Execute actual fallback statements with fake paths/OS and a recording subprocess.
t=ast.parse((SRC/'an-return.py').read_text());body=[n for n in t.body if not isinstance(n,(ast.Import,ast.ImportFrom)) and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='insert')]
code=compile(ast.Module(body=body,type_ignores=[]),'actual-AN-return','exec');fallbackns={'os':OS(),'Path':F,'load':lambda:a,'X':F('/attempt/AM'),'recovery':recovery,'json':json,'subprocess':Subprocess()}
reset(False);exec(code,fallbackns);assert calls==[['/usr/local/lib/spx-boot-diagnostics/return.sh']]
fallbad=[{'bid':'known'},{'release':'known'},{'cmdline':'wrong'},{'age':899.99},{'marker':True},{'pending':'other'},{'bad_recovery':True},{'changed_late':True}]
for patch in fallbad:
 reset(False);state.update(patch);rejected(lambda:exec(code,fallbackns));assert not calls
print(json.dumps({'actual_preboot_positive_cases':2,'actual_preboot_negative_cases':len(prebad),'actual_fallback_positive_cases':1,'actual_fallback_negative_cases':len(fallbad),'unsafe_state_never_called_return':True,'live_boot_or_file_mutations':False},indent=2))
