#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual MDT relocation path on retained Venus images, without SCM."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
INVENTORY = Path('/var/tmp/spx-video-integration-20261003-v1')
PIN = 'f7049b043c472599086e33d5c477b90a06606b68cd05d88c3e4bf50a23892c5f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


PREAMBLE = r'''
#include <linux/elf.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#include <sys/types.h>
typedef uint64_t phys_addr_t;
#define PHYS_ADDR_MAX UINT64_MAX
#define SZ_4K 4096UL
#define ALIGN(x,a) (((x)+(a)-1)&~((a)-1))
#define QCOM_MDT_TYPE_MASK (7 << 24)
#define QCOM_MDT_TYPE_HASH (2 << 24)
#define QCOM_MDT_RELOCATABLE (1 << 27)
#define GFP_KERNEL 0
#define kmalloc(n,f) malloc(n)
#define kfree(p) free(p)
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define dev_err(...) ((void)0)
struct device { unsigned dummy; };
struct firmware { size_t size; const unsigned char *data; };
struct qcom_pas_context { unsigned dummy; };
static size_t size_add(size_t a,size_t b) { return a>SIZE_MAX-b?SIZE_MAX:a+b; }
static size_t size_mul(size_t a,size_t b) { return b && a>SIZE_MAX/b?SIZE_MAX:a*b; }
static unsigned init_calls,setup_calls,split_calls;
static int fail;
static phys_addr_t expect_phys;
static unsigned char *metadata;
static size_t metadata_size;
static int qcom_pas_init_image(int id,const void *bytes,size_t n,struct qcom_pas_context *ctx) {
    assert(id==9 && !ctx && n==metadata_size && !memcmp(bytes,metadata,n));
    init_calls++;return fail==1?-EIO:0;
}
static int qcom_pas_mem_setup(int id,phys_addr_t phys,size_t n) {
    assert(id==9 && phys==expect_phys && n==0x500000);setup_calls++;return fail==2?-EIO:0;
}
static ssize_t mdt_load_split_segment(void *ptr,const struct elf32_phdr *phdrs,
    unsigned int segment,const char *name,struct device *dev) {
    (void)ptr;(void)phdrs;(void)segment;(void)name;(void)dev;split_calls++;return -ENOENT;
}
'''

CHECKS = r'''
static unsigned char *read_file(const char *name,size_t *size) {
    FILE *f=fopen(name,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);
    assert(n>0 && !fseek(f,0,SEEK_SET));unsigned char *p=malloc(n);assert(p);
    assert(fread(p,1,n,f)==(size_t)n && !fclose(f));*size=n;return p;
}
static void reset(unsigned char *memory) {
    memset(memory,0xa5,0x500020);init_calls=setup_calls=split_calls=0;fail=0;
}
static void guards(unsigned char *memory) {
    for(unsigned i=0;i<16;i++)assert(memory[i]==0xa5 && memory[0x500010+i]==0xa5);
    assert(!split_calls);
}
int main(int argc,char **argv) {
    assert(argc==4);size_t n,want_size;
    unsigned char *data=read_file(argv[1],&n),*want=read_file(argv[2],&want_size);
    metadata=read_file(argv[3],&metadata_size);assert(want_size==0x500000);
    struct firmware fw={.size=n,.data=data};struct device dev={0};
    unsigned char *memory=malloc(0x500020);assert(memory);
    const phys_addr_t addresses[]={0x9ab00000,0xa0000000,0xbf000000};
    unsigned checks=0;phys_addr_t reloc;
    assert(qcom_mdt_get_size(&fw)==0x500000 && metadata_size==7020);
    for(unsigned i=0;i<3;i++) {
        reset(memory);expect_phys=addresses[i];reloc=0;
        assert(!qcom_mdt_load(&dev,&fw,argv[1],9,memory+16,expect_phys,0x500000,&reloc));
        assert(reloc==0xf500000 && init_calls==1 && setup_calls==1);
        assert(!memcmp(memory+16,want,want_size));guards(memory);checks++;
    }
    for(unsigned error=1;error<=2;error++) {
        reset(memory);expect_phys=addresses[1];fail=error;
        assert(qcom_mdt_load(&dev,&fw,argv[1],9,memory+16,expect_phys,0x500000,NULL)==-EIO);
        assert(init_calls==1 && setup_calls==(error==2));
        for(unsigned i=0;i<0x500020;i++)assert(memory[i]==0xa5);checks++;
    }
    reset(memory);expect_phys=addresses[1];
    assert(qcom_mdt_load(&dev,&fw,argv[1],9,memory+16,expect_phys,0x4ff000,NULL)==-EINVAL);
    assert(init_calls==1 && setup_calls==1);guards(memory);
    for(unsigned i=0x4ff010;i<0x500020;i++)assert(memory[i]==0xa5);checks++;
    reset(memory);assert(!qcom_mdt_load_no_init(&dev,&fw,argv[1],memory+16,addresses[2],0x500000,&reloc));
    assert(!init_calls && !setup_calls && reloc==0xf500000 && !memcmp(memory+16,want,want_size));guards(memory);checks++;
    reset(memory);assert(qcom_mdt_load_no_init(&dev,&fw,argv[1],NULL,addresses[1],0x500000,NULL)==-EINVAL);checks++;
    assert(qcom_mdt_load_no_init(&dev,&fw,argv[1],memory+16,0,0x500000,NULL)==-EINVAL);checks++;
    assert(qcom_mdt_load_no_init(&dev,&fw,argv[1],memory+16,addresses[1],0,NULL)==-EINVAL);checks++;
    unsigned char magic=data[0];data[0]=0;expect_phys=addresses[1];
    assert(qcom_mdt_load(&dev,&fw,argv[1],9,memory+16,expect_phys,0x500000,NULL)==-EINVAL);
    assert(!init_calls && !setup_calls);data[0]=magic;checks++;
    printf("{\"checks\":%u,\"relocated_addresses\":3,\"loadable_bytes\":5242880,\"metadata_bytes\":7020}\n",checks);
    free(memory);free(data);free(want);free(metadata);return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    assert sha(INVENTORY / 'sha256.json') == PIN
    pins = json.loads((INVENTORY / 'sha256.json').read_text())
    records = json.loads((INVENTORY / 'inventory.json').read_text())
    for name in ['inventory.json', 'linux-mdt_loader.c'] + list(records['firmware']):
        assert sha(INVENTORY / name) == pins[name]
    source_path = REPO / 'drivers/soc/qcom/mdt_loader.c'
    assert sha(source_path) == pins['linux-mdt_loader.c']
    out = args.output
    out.mkdir(mode=0o700)
    shutil.copyfile(source_path, out / 'mdt_loader.c')
    shutil.copyfile(INVENTORY / 'inventory.json', out / 'inventory.json')
    shutil.copyfile(INVENTORY / 'sha256.json', out / 'inventory-sha256.json')
    helper = REPO / 'tools/spx/boot-diagnostics/video-power-20261003/verify_power.py'
    spec = importlib.util.spec_from_file_location('power_extract', helper)
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    source = source_path.read_text()
    markers = ('static bool mdt_header_valid(', 'static bool mdt_phdr_loadable(',
               'ssize_t qcom_mdt_get_size(', 'void *qcom_mdt_read_metadata(',
               'static int __qcom_mdt_pas_init(', 'static bool qcom_mdt_bins_are_split(',
               'int qcom_mdt_load_no_init(', 'int qcom_mdt_load(')
    bodies = [extract.block(source, marker) for marker in markers]
    cfile = out / 'native.c'
    cfile.write_text(PREAMBLE + '\n\n'.join(bodies) + CHECKS)
    cmd = ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
           '-Wno-sign-compare', '-Wno-misleading-indentation',
           '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
           str(cfile), '-o', str(out / 'native')]
    compiled = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    (out / 'compile.stdout').write_text(compiled.stdout)
    (out / 'compile.stderr').write_text(compiled.stderr)
    assert compiled.returncode == 0, compiled.stderr
    results = []
    for name, row in records['firmware'].items():
        data = (INVENTORY / name).read_bytes()
        # Independent expected output from the previously sealed ELF inventory.
        memory = bytearray([0xa5]) * 0x500000
        for header in row['headers']:
            if not header['linux_mdt_loadable']:
                continue
            offset = header['paddr'] - row['lowest_paddr']
            count = header['filesz']
            memory[offset:offset + count] = data[header['offset']:header['offset'] + count]
            memory[offset + count:offset + header['memsz']] = bytes(header['memsz'] - count)
        assert len(memory) == 0x500000
        metadata = data[:row['headers'][0]['filesz']]
        hashed = next(h for h in row['headers'] if h['flags'] & (7 << 24) == (2 << 24))
        metadata += data[hashed['offset']:hashed['offset'] + hashed['filesz']]
        shutil.copyfile(INVENTORY / name, out / name)
        (out / (name + '.expected')).write_bytes(memory)
        (out / (name + '.metadata')).write_bytes(metadata)
        command = [str(out / 'native'), str(out / name), str(out / (name + '.expected')),
                   str(out / (name + '.metadata'))]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        (out / (name + '.stdout')).write_text(result.stdout)
        (out / (name + '.stderr')).write_text(result.stderr)
        assert result.returncode == 0 and not result.stderr, (name, result.stderr)
        results.append(dict(image=name, sha256=sha(out / name), checks=json.loads(result.stdout)))
    shutil.copyfile(Path(__file__), out / 'verify_relocation.py')
    shutil.copyfile(helper, out / 'verify_power.py')
    report = dict(compile=cmd, inventory_manifest_sha256=PIN, source_sha256=sha(source_path),
                  extracted_functions=[dict(marker=m, sha256=hashlib.sha256(b.encode()).hexdigest())
                                       for m, b in zip(markers, bodies)], results=results,
                  asan_ubsan=True, mmio_operations=0, scm_calls=0,
                  limits=['PAS init_image and mem_setup are mock leaf functions, not secure monitor calls.',
                          'Authentication/reset and the live allocator were not exercised.',
                          'Synthetic physical addresses do not reserve or write host RAM.'])
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(manifest)
    print(json.dumps(dict(files=len(manifest.splitlines()), manifest_sha256=sha(out / 'SHA256SUMS'),
                         results=results), indent=2))


if __name__ == '__main__':
    main()
