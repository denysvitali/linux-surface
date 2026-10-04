#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash D03 evidence and evaluate actual Linux MDT/register definitions offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(source, name):
    match=re.search(r'^(?:static )?(?:bool|ssize_t) '+name+r'\([^\n]+\)\n\{',source,re.M)
    assert match, name
    depth=1
    for at in range(match.end(),len(source)):
        depth+=(source[at]=='{')-(source[at]=='}')
        if not depth:return source[match.start():at+1]
    raise ValueError('function boundary')


def verify(root, expected):
    assert sha(root/'sha256.json')==expected
    hashes=json.loads((root/'sha256.json').read_text())
    assert set(hashes)=={p.name for p in root.iterdir() if p.is_file()}-{'sha256.json'}
    for name,digest in hashes.items():
        assert Path(name).name==name and sha(root/name)==digest,name
    return hashes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('inventory',type=Path)
    p.add_argument('state',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--inventory-sha256',required=True)
    p.add_argument('--state-sha256',required=True)
    args=p.parse_args()
    inventory=verify(args.inventory,args.inventory_sha256)
    state_hashes=verify(args.state,args.state_sha256)
    out=args.output;out.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__),out/'verify_video.py')
    r=json.loads((args.inventory/'inventory.json').read_text())
    state=json.loads((args.state/'result.json').read_text())
    assert state['boot_id']=='b6b4f20b-376f-4577-b282-677ad4ae0ec8'
    assert state['codec_nodes_opened']==0 and not state['hardware_acceptance_closed']
    assert all(not nodes for nodes in state['nodes'].values()) and not state['codec_platforms']
    assert state['configuration']['known_good']['CONFIG_VIDEO_QCOM_VENUS']=='CONFIG_VIDEO_QCOM_VENUS=m'
    assert state['configuration']['ax']['CONFIG_V4L_MEM2MEM_DRIVERS']=='# CONFIG_V4L_MEM2MEM_DRIVERS is not set'
    source=(args.inventory/'linux-mdt_loader.c').read_text()
    copied='\n\n'.join(function(source,n) for n in ['mdt_header_valid','mdt_phdr_loadable','qcom_mdt_get_size'])
    preamble='''#include <linux/elf.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
typedef uint64_t phys_addr_t;
#define PHYS_ADDR_MAX UINT64_MAX
#define SZ_4K 4096UL
#define ALIGN(x,a) (((x)+(a)-1)&~((a)-1))
#define QCOM_MDT_TYPE_MASK (7 << 24)
#define QCOM_MDT_TYPE_HASH (2 << 24)
struct firmware { size_t size; const unsigned char *data; };
static size_t size_add(size_t a,size_t b) { return a>SIZE_MAX-b?SIZE_MAX:a+b; }
static size_t size_mul(size_t a,size_t b) { return b && a>SIZE_MAX/b?SIZE_MAX:a*b; }
'''
    main='''int main(int argc,char **argv) {
 for(int i=1;i<argc;i++) {
  FILE *f=fopen(argv[i],"rb"); if(!f)return 2;
  if(fseek(f,0,SEEK_END))return 3;
  long bytes=ftell(f); if(bytes<=0 || fseek(f,0,SEEK_SET))return 4;
  unsigned char *b=malloc((size_t)bytes); if(!b)return 5;
  if(fread(b,1,(size_t)bytes,f)!=(size_t)bytes)return 6;
  fclose(f); struct firmware fw={.size=(size_t)bytes,.data=b};
  printf("%zd\\n",qcom_mdt_get_size(&fw)); free(b);
 }
 return 0;
}
'''
    (out/'mdt-native.c').write_text(preamble+copied+'\n'+main)
    # Kernel builds disable sign-compare; preserve the Linux function verbatim
    # instead of altering its unsigned physical-address / -EINVAL expression.
    cmd=['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-sign-compare','-fsanitize=address,undefined',
         '-fno-omit-frame-pointer','-O1',str(out/'mdt-native.c'),'-o',str(out/'mdt-native')]
    compiled=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
    (out/'mdt-compile.stdout').write_text(compiled.stdout);(out/'mdt-compile.stderr').write_text(compiled.stderr)
    assert compiled.returncode==0, compiled.stderr
    names=list(r['firmware'])
    executed=subprocess.run([str(out/'mdt-native')]+[str(args.inventory/n) for n in names],capture_output=True,text=True,timeout=30)
    (out/'mdt-native.stdout').write_text(executed.stdout);(out/'mdt-native.stderr').write_text(executed.stderr)
    assert executed.returncode==0 and [int(v) for v in executed.stdout.splitlines()]==[0x500000]*3
    # Compare the legacy/Iris1 branch's relative Linux offsets with the absolute
    # SM8150 reference macros in separate translation units. No MMIO occurs.
    pairs=[('CPU_BASE','VIDC_CPU_BASE_OFFS'),('CPU_CS_BASE','VIDC_CPU_CS_BASE_OFFS'),
           ('CPU_IC_BASE','VIDC_CPU_IC_BASE_OFFS'),('WRAPPER_BASE','VIDC_WRAPPER_BASE_OFFS'),
           ('VBIF_BASE','VIDC_VBIF_BASE_OFFS'),('CPU_CS_BASE + VIDC_CTRL_INIT','VIDC_CTRL_INIT'),
           ('CPU_CS_BASE + CPU_CS_SCIACMDARG0','VIDC_CTRL_STATUS'),
           ('CPU_CS_BASE + CPU_CS_SCIACMDARG1','VIDC_QTBL_INFO'),
           ('CPU_CS_BASE + CPU_CS_SCIACMDARG2','VIDC_QTBL_ADDR'),
           ('CPU_CS_BASE + CPU_CS_SCIACMDARG3','VIDC_VERSION_INFO'),
           ('CPU_CS_BASE + SFR_ADDR','VIDC_SFR_ADDR'),('CPU_CS_BASE + MMAP_ADDR','VIDC_MMAP_ADDR'),
           ('CPU_CS_BASE + UC_REGION_ADDR','VIDC_UC_REGION_ADDR'),('CPU_CS_BASE + UC_REGION_SIZE','VIDC_UC_REGION_SIZE'),
           ('CPU_IC_BASE + CPU_IC_SOFTINT','VIDC_CPU_IC_SOFTINT'),
           ('CPU_IC_SOFTINT_H2A_MASK','VIDC_CPU_IC_SOFTINT_H2A_BMSK'),
           ('CPU_CS_BASE + CPU_CS_A2HSOFTINTCLR','VIDC_CPU_CS_A2HSOFTINTCLR'),
           ('WRAPPER_BASE + WRAPPER_INTR_STATUS','VIDC_WRAPPER_INTR_STATUS'),
           ('WRAPPER_BASE + WRAPPER_INTR_MASK','VIDC_WRAPPER_INTR_MASK'),
           ('WRAPPER_BASE + WRAPPER_INTR_CLEAR','VIDC_WRAPPER_INTR_CLEAR'),
           ('WRAPPER_BASE + WRAPPER_CPU_CLOCK_CONFIG','VIDC_WRAPPER_CPU_CLOCK_CONFIG'),
           ('WRAPPER_BASE + WRAPPER_CPU_CGC_DIS','VIDC_WRAPPER_CPU_CGC_DIS'),
           ('WRAPPER_BASE + WRAPPER_CPU_STATUS','VIDC_WRAPPER_CPU_STATUS')]
    values=[]
    for index, name in enumerate(['linux-hfi_venus_io.h','reference-vidc_hfi_io.h']):
        header=(args.inventory/name).read_text()
        if index==1:
            assert header.count('#include <linux/io.h>')==1
            header=header.replace('#include <linux/io.h>','/* Native definition evaluation: no I/O include. */')
        expressions=[p[index] for p in pairs]
        c='#include <stdio.h>\n#define BIT(n) (1UL<<(n))\n'+header+'\nint main(void) {\n'
        c+='\n'.join(f'printf("%lu\\n", (unsigned long)({expr}));' for expr in expressions)+'\nreturn 0;\n}\n'
        (out/f'registers-{index}.c').write_text(c)
        command=['cc','-std=c11','-Wall','-Wextra','-Werror',str(out/f'registers-{index}.c'),'-o',str(out/f'registers-{index}')]
        built=subprocess.run(command,capture_output=True,text=True,timeout=60)
        (out/f'registers-{index}.compile.stderr').write_text(built.stderr)
        assert built.returncode==0,built.stderr
        raw=subprocess.check_output([str(out/f'registers-{index}')],text=True,timeout=10)
        (out/f'registers-{index}.stdout').write_text(raw);values.append([int(v) for v in raw.splitlines()])
    assert values[0]==values[1] and len(values[0])==23
    rows=[dict(linux=p[0],reference=p[1],value=val) for p,val in zip(pairs,values[0])]
    (out/'registers.json').write_text(json.dumps(rows,indent=2)+'\n')
    summary=dict(inventory_manifest_sha256=args.inventory_sha256,state_manifest_sha256=args.state_sha256,
                 inventory_files_verified=len(inventory),state_files_verified=len(state_hashes),
                 actual_linux_mdt_functions=3,mdt_images_verified=3,mdt_required_bytes=0x500000,
                 native_mdt_asan_ubsan=True,reference_register_definitions_equal=23,
                 sq2_hfi_protocol_validated=False,hardware_acceptance_closed=False,
                 limits=['Native definitions/MDT layout do not establish hardware behavior or secure firmware authentication.',
                         'The offset comparison covers the SM8150 reference, not executable SQ2 miniport behavior.'])
    (out/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
    hashes={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    verify(out,sha(out/'sha256.json'))
    print(json.dumps(summary|{'files_verified':len(hashes),'manifest_sha256':sha(out/'sha256.json')},indent=2))


if __name__=='__main__':
    main()
