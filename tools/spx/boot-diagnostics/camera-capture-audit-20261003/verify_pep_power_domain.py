#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replay PEP power contracts and test the actual Linux GDSC helpers offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(text,name):
    start=text.index('static int '+name+'(')
    at=text.index('{',start)
    depth=1;end=at+1
    while depth:
        if text[end]=='{':depth+=1
        elif text[end]=='}':depth-=1
        end+=1
    return text[start:end]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args();root=args.inventory;out=args.output;out.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__),out/Path(__file__).name)
    manifest={}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ',1)
        assert Path(name).name==name and name not in manifest
        assert sha(root/name)==digest;manifest[name]=digest
    assert set(manifest)=={p.name for p in root.iterdir()}-{'SHA256SUMS'}
    report=json.loads((root/'pep-power-domain.json').read_text())
    import importlib.util
    import sys
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('review_domain',root/'audit_pep_power_domain.py')
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    helper=audit.module(root/'audit_pep_loader.py')
    image=helper.Image((root/'qcpep8180.sys').read_bytes())
    assert audit.metadata(image)==report['metadata']
    assert audit.instructions(image)==report['instruction_checks'] and len(report['instruction_checks'])==105
    camcc,gdsc,header=[(root/name).read_text() for name in ('camcc-sc8180x.c','gdsc.c','gdsc.h')]
    assert audit.linux(camcc,gdsc,header)==report['linux']
    assert len(report['requests'])==64 and report['hardware_operations']==0
    assert len(report['ranges'])==24 and report['exception_records']==2442
    for row in report['ranges']:
        start,end=row['start_rva'],row['end_rva']
        assert hashlib.sha256(image.read(start,end-start)).hexdigest()==row['sha256']
        if row['exception_bounded']:assert image.functions[start]==end
        else:assert (start,end)==(0xfe1e8,0xfe1f0) and start not in image.functions
    raw=json.loads((root/'receiver-power.json').read_text());requests=[]
    for package,p in raw['packages'].items():
        for device,states in p['devices'].items():
            for state in states:
                for action in state['actions']:
                    if action['operation']=='FOOTSWITCH' and action['arguments'][0] in {d['name'] for d in report['metadata']['camera_domains']}:
                        requests.append((package,device,state['component'],state['state'],action['line'],*action['arguments']))
    assert requests==[(r['package'],r['device'],r['component'],r['state'],r['line'],r['name'],r['raw_action']) for r in report['requests']]

    names=('PWR_ON_MASK','HW_CONTROL_MASK','SW_COLLAPSE_MASK','GDSC_POWER_UP_COMPLETE',
           'GDSC_POWER_DOWN_COMPLETE','CFG_GDSCR_OFFSET')
    definitions='\n'.join(re.search(r'^#define '+n+r'\s+.*$',gdsc,re.M).group() for n in names)
    definitions+='\n'+re.search(r'^#define POLL_CFG_GDSCR\s+.*$',header,re.M).group()
    bodies='\n'.join(function(gdsc,n) for n in ('gdsc_check_status','gdsc_hwctrl','gdsc_update_collapse_bit'))
    code='''#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#include <assert.h>
#define BIT(n) (1U << (n))
typedef uint32_t u32;
struct regmap { u32 word, reg, mask, value; int read_error,write_error; };
struct gdsc { struct regmap *regmap; u32 gdscr,flags,gds_hw_ctrl,collapse_mask,collapse_ctrl; };
enum gdsc_status {GDSC_OFF,GDSC_ON};
static int regmap_read(struct regmap *map,u32 reg,u32 *value) {
    map->reg=reg;if(map->read_error)return map->read_error;*value=map->word;return 0;
}
static int regmap_update_bits(struct regmap *map,u32 reg,u32 mask,u32 value) {
    map->reg=reg;map->mask=mask;map->value=value;
    if(map->write_error)return map->write_error;
    map->word=(map->word&~mask)|(value&mask);return 0;
}
'''+definitions+'\n'+bodies+'''
int main(void) {
 const u32 words[]={0,1,2,3,0x80000000U,0x80000001U,0x80000002U,UINT32_MAX,
                    0x18000,0x10000,0x8000,0xf0f0f0f0U,0xaaaaaaaaU,0x55555555U};
 unsigned cases=0;
 for(unsigned mode=0;mode<3;mode++) {
  for(unsigned status=0;status<2;status++) {
   for(unsigned w=0;w<sizeof(words)/sizeof(words[0]);w++) {
    struct regmap map={.word=words[w]};
    struct gdsc sc={.regmap=&map,.gdscr=0xc1bc,.gds_hw_ctrl=mode==1?0x9000:0,
                    .flags=mode==2?POLL_CFG_GDSCR:0};
    unsigned bit=mode==2?(status?16:15):31;
    int expected=(int)((words[w]>>bit)&1U);
    if(mode!=2 && !status)expected=!expected;
    assert(gdsc_check_status(&sc,(enum gdsc_status)status)==expected);
    assert(map.reg==(mode==2?0xc1c0U:mode==1?0x9000U:0xc1bcU));cases++;
   }
   struct regmap map={.read_error=-EIO};
   struct gdsc sc={.regmap=&map,.gdscr=0xc1bc,.flags=mode==2?POLL_CFG_GDSCR:0};
   assert(gdsc_check_status(&sc,(enum gdsc_status)status)==-EIO);cases++;
  }
  struct regmap map={0};struct gdsc sc={.regmap=&map,.flags=mode==2?POLL_CFG_GDSCR:0};
  assert(gdsc_check_status(&sc,(enum gdsc_status)99)==-EINVAL);cases++;
 }
 for(unsigned kind=0;kind<3;kind++) {
  for(unsigned en=0;en<2;en++) {
   for(unsigned w=0;w<sizeof(words)/sizeof(words[0]);w++) {
    struct regmap map={.word=words[w]};
    struct gdsc sc={.regmap=&map,.gdscr=0xc1bc,.collapse_mask=kind==2?0x10:0,.collapse_ctrl=0x9000};
    int ret=kind==0?gdsc_hwctrl(&sc,en):gdsc_update_collapse_bit(&sc,en);
    u32 mask=kind==0?2U:kind==1?1U:0x10U;
    u32 expected=words[w]^((words[w]^(en?mask:0U))&mask);
    assert(ret==0 && map.word==expected && map.mask==mask);
    assert(map.value==(en?mask:0U));assert(map.reg==(kind==2?0x9000U:0xc1bcU));cases++;
   }
   struct regmap map={.word=0x12345678,.write_error=-EIO};
   struct gdsc sc={.regmap=&map};
   int ret=kind==0?gdsc_hwctrl(&sc,en):gdsc_update_collapse_bit(&sc,en);
   assert(ret==-EIO && map.word==0x12345678);cases++;
  }
 }
 printf("%u\\n",cases);return 0;
}
'''
    source=out/'linux-gdsc-helpers.c';source.write_text(code)
    command=['gcc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(source),'-o',str(out/'linux-gdsc-helpers')]
    compiled=subprocess.run(command,text=True,capture_output=True,timeout=30)
    (out/'compile.stdout').write_text(compiled.stdout);(out/'compile.stderr').write_text(compiled.stderr)
    assert compiled.returncode==0 and not compiled.stderr
    tested=subprocess.run([str(out/'linux-gdsc-helpers')],text=True,capture_output=True,timeout=10)
    (out/'native.stdout').write_text(tested.stdout);(out/'native.stderr').write_text(tested.stderr)
    assert tested.returncode==0 and tested.stdout=='183\n' and not tested.stderr

    original=(root/'qcpep8180.sys').read_bytes()
    mutations=[('wrong-titan-address',0x19c758,struct.pack('<Q',0xac0c1bc),'metadata'),
               ('wrong-domain-hal',0x19c760,struct.pack('<Q',image.base+0x19f930),'metadata'),
               ('wrong-mmcx-alias',0x19c780,struct.pack('<Q',image.base+0x198f50),'metadata'),
               ('raw-enable-becomes-hw',0x2070f4,image.read(0x2070f6,1),'metadata'),
               ('camera-always-on',0x19f130,image.read(0x18b340,8),'metadata'),
               ('wrong-collapse-mask',0xff438,image.read(0xff538,4),'instructions'),
               ('wrong-power-poll',0xff44c,image.read(0xff4a4,4),'instructions'),
               ('wrong-absent-client-limit',0x19f258,struct.pack('<I',48),'metadata')]
    rejected=[]
    for name,rva,value,kind in mutations:
        sec=next(s for s in image.sections if s['rva']<=rva< s['rva']+s['size'])
        at=sec['raw']+rva-sec['rva'];data=bytearray(original);data[at:at+len(value)]=value
        path=out/(name+'.sys');path.write_bytes(data)
        try:
            getattr(audit,kind)(helper.Image(bytes(data)))
        except AssertionError as error:
            rejected.append(dict(name=name,sha256=sha(path),reason=str(error)))
        else:raise AssertionError('accepted '+name)
    for name,cc,text in [('wrong-linux-domain-poll',camcc.replace('.flags = POLL_CFG_GDSCR','.flags = HW_CTRL'),gdsc),
                         ('wrong-linux-collapse-bit',camcc,re.sub(r'(#define SW_COLLAPSE_MASK\s+BIT\()0',r'\g<1>1',gdsc))]:
        path=out/(name+'.c');path.write_text(cc if name=='wrong-linux-domain-poll' else text)
        try:audit.linux(cc,text,header)
        except AssertionError as error:rejected.append(dict(name=name,sha256=sha(path),reason=str(error)))
        else:raise AssertionError('accepted '+name)
    result=dict(inventory_files_verified=len(manifest),inventory_manifest_sha256=sha(root/'SHA256SUMS'),
                selected_instruction_checks=105,selected_ranges_verified=24,firmware_actions_replayed=64,
                actual_linux_helpers=['gdsc_check_status','gdsc_hwctrl','gdsc_update_collapse_bit'],
                native_cases=183,native_asan_ubsan_clean=True,compile_argv=command,
                rejected_fixtures=rejected,hardware_operations=0,
                limits=['Native tests use fake register access and do not execute PEP or touch hardware.',
                        'Matching control masks do not prove equivalent polling/timing or analog supply wiring.'])
    (out/'review.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    print(json.dumps(dict(files_verified=len(manifest),native_cases=183,rejected_fixtures=len(rejected),manifest_sha256=sha(out/'SHA256SUMS'))))


if __name__=='__main__':
    main()
