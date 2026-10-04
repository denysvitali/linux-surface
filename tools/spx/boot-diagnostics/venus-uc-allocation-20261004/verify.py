#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile verbatim BF and shared-UC allocation lifecycles with mocked DMA."""
import argparse
import difflib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE=Path(__file__).resolve().parent
PRE=Path('/var/tmp/spx-venus-uc-preimage-20261004-v1')
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
VENUS='drivers/media/platform/qcom/venus/'


def block(source,marker):
    start=source.index(marker);end=source.index('{',start)+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    if source[end:end+1]==';':end+=1
    return source[start:end]


def macros(source,prefixes):
    result=[];lines=source.splitlines();n=0
    while n<len(lines):
        match=re.match(r'^#define\s+(\w+)',lines[n]);end=n
        while lines[end].endswith('\\'):end+=1
        if match and any(match[1].startswith(p) for p in prefixes):result.append('\n'.join(lines[n:end+1]))
        n=end+1
    return '\n'.join(result)


def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args()
    os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics');import bf_boot_guard as g
    a=g.load();assert a['state'].startswith('BF terminal;')
    assert g.sha(PRE/'sha256.json')=='4ba38b97927ca151dd8ecec12e992d5b152d9e3d775651979001a723d84445d7'
    assert g.files(PRE)==json.loads((PRE/'sha256.json').read_text())|{'sha256.json':g.sha(PRE/'sha256.json')}
    assert not g.recovery(a).get('next_entry','')
    out=args.output;out.mkdir(mode=0o700)
    for n in ('verify.py','native.h','checks.h'):shutil.copy2(HERE/n,out/n)
    before=(PRE/'hfi_venus.c').read_text();after=(REPO/VENUS/'hfi_venus.c').read_text()
    (out/'before-hfi_venus.c').write_text(before);(out/'linux-hfi_venus.c').write_text(after)
    rows=json.loads((g.X/'assembly/source-files.json').read_text())
    assert g.sha(PRE/'hfi_venus.c')==rows[VENUS+'hfi_venus.c']['sha256']
    for name in ('core.h','hfi_cmds.h'):
        assert g.sha(REPO/VENUS/name)==rows[VENUS+name]['sha256']
        shutil.copy2(REPO/VENUS/name,out/('linux-'+name))
    definitions=macros(after,('IFACEQ_','HFI_HOST_TO_','HFI_CTRL_TO_','QDSS_SIZE','SFR_SIZE','QUEUE_SIZE','ALIGNED_','SHARED_QSIZE'))
    for name in ('hfi_queue_table_header','hfi_queue_header','mem_desc','iface_queue'):
        definitions+='\n'+block(after,'struct '+name+' {')
    definitions+='\n'+block(after,'enum venus_state {')
    core=(REPO/VENUS/'core.h').read_text()
    definitions+='\n'+block(core,'enum vpu_version {')
    definitions+='\n'+re.search(r'^#define IS_IRIS1\(core\)[^\n]+',core,re.M)[0]
    cmds=(REPO/VENUS/'hfi_cmds.h').read_text()
    definitions+='\n'+block(cmds,'struct hfi_sfr {')
    body=block(core,'static inline void *to_hfi_priv(')+'\n'
    names=('venus_alloc','venus_free','venus_set_qhdr_defaults','venus_interface_queues_release','venus_interface_queues_init','venus_hfi_queues_reinit')
    def functions(s):
        result=[]
        for name in names:
            marker=re.search(r'^(?:static )?(?:int|void) '+name+r'\(',s,re.M)[0]
            result.append(block(s,marker))
        return '\n'.join(result)
    prior=functions(before)
    for name in names:prior=re.sub(r'\b'+name+r'\b','before_'+name,prior)
    param=re.search(r'static bool spx_uc_shared_alloc;.*?MODULE_PARM_DESC\(spx_uc_shared_alloc,[^\n]+',after,re.S)[0]
    actual=functions(after)
    body+=param+'\n'+prior+'\n'+actual
    native=(out/'native.h').read_text().replace('/* SOURCE_DEFINITIONS */',definitions).replace('/* SOURCE_HDEV */',block(after,'struct venus_hfi_device {')).replace('/* SOURCE_FUNCTIONS */',body)+'\n'+(out/'checks.h').read_text()
    commands=[];results=[]
    def run(label,argv,negative=False):
        r=subprocess.run(argv,capture_output=True,text=True,timeout=120)
        (out/(label+'.stdout')).write_text(r.stdout);(out/(label+'.stderr')).write_text(r.stderr)
        commands.append(dict(label=label,argv=argv,exit_code=r.returncode))
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if negative:assert r.returncode!=0 and ('Assertion' in r.stderr or 'AddressSanitizer' in r.stderr),label
        else:assert r.returncode==0,(label,r.stderr)
        return r
    def check(name,text,config,negative=False):
        src=out/(name+'.c');src.write_text(text)
        run(name+'-compile',['cc','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-fno-omit-frame-pointer','-fsanitize=address,undefined','-DCONFIG_IRIS='+str(config),str(src),'-o',str(out/name)])
        r=run(name,[str(out/name)],negative)
        if not negative:assert not r.stderr;results.append(json.loads(r.stdout))
    for config in (0,1):check('native-'+str(config),native,config)
    controls={'default-on':('static bool spx_uc_shared_alloc;','static bool spx_uc_shared_alloc=true;'),
        'lost-generation-gate':('IS_IRIS1(hdev->core) &&','true &&'),
        'lost-board-gate':('of_device_is_compatible(hdev->core->dev->of_node,\n\t\t\t\t\t"qcom,sc8180x-venus")','true'),
        'short-owner':('shared_uc ? SHARED_QSIZE : ALIGNED_QUEUE_SIZE','ALIGNED_QUEUE_SIZE'),
        'wrong-sfr-offset':('hdev->sfr.da += ALIGNED_QUEUE_SIZE;','hdev->sfr.da += 4096;'),
        'free-borrowed-view':('venus_free(hdev, &hdev->shared_uc);','venus_free(hdev, &hdev->ifaceq_table);')}
    for name,(old,new) in controls.items():
        candidate=(param+'\n'+actual).replace(old,new);assert candidate!=param+'\n'+actual,name
        # Mutate only candidate bodies/parameter, preserving the BF oracle.
        changed=native.replace(body,block(core,'static inline void *to_hfi_priv(')+'\n'+param.replace(old,new)+'\n'+prior+'\n'+actual.replace(old,new))
        assert changed!=native,name;check(name,changed,0,True)
    patch=''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+VENUS+'hfi_venus.c',tofile='b/'+VENUS+'hfi_venus.c'))
    (out/'candidate.diff').write_text(patch)
    run('style',[str(REPO/'scripts/checkpatch.pl'),'--no-tree','--no-signoff','--ignore','COMMIT_MESSAGE',str(out/'candidate.diff')])
    report=dict(parent='20261004bf',preimage_sha256=g.sha(PRE/'hfi_venus.c'),candidate_sha256=g.sha(REPO/VENUS/'hfi_venus.c'),actual_body_results=results,rejected_candidates=list(controls),exact_actual_lifecycle_functions=list(names),hardware_operations=0,full_kernel_built=False,boot_selected=False,hardware_acceptance_closed=False,
        limits=['DMA, OF matching, mutex and barriers are mocked; actual driver functions/types/macros are verbatim.', 'Retained optional-SFR allocation failure behavior is compared; its NULL-SFR reinit is not exercised.', 'No firmware containment requirement, device translation or successful hardware startup follows from these offline checks.'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');(out/'sha256.json').write_text(json.dumps(g.files(out),indent=2)+'\n');os.sync();print(json.dumps(report|{'manifest_sha256':g.sha(out/'sha256.json')},indent=2))


if __name__=='__main__':main()
