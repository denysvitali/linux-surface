#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual Linux boot/ISR bodies against synthetic register traces, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(source, marker):
    start = source.index(marker)
    at = source.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    if source[end:end + 1] == ';':
        end += 1
    return source[start:end]


PREAMBLE = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
typedef uint32_t u32;
typedef int irqreturn_t;
#define __iomem
#define IRQ_NONE 0
#define IRQ_WAKE_THREAD 2
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define IS_ENABLED(x) (x)
#include "linux-hfi_venus_io.h"
'''

SCAFFOLD = r'''
struct device { unsigned dummy; };
struct venus_resources { enum vpu_version vpu_version; enum hfi_version hfi_version; };
struct venus_core { struct device *dev; const struct venus_resources *res;
    void *cpu_cs_base, *wrapper_base; void *priv; };
struct venus_hfi_device { struct venus_core *core; u32 irq_status; };
static struct venus_hfi_device *to_hfi_priv(struct venus_core *core) { return core->priv; }
struct event { u32 op, offset, value; };
struct capture { struct event trace[400]; unsigned len, sleeps, errors; u32 irq_status; int result; };
static u32 cpu[0x300/4], wrapper[0x4000/4];
static struct capture got;
static unsigned polls, ready_after;
static u32 ctrl_result;
static void event(u32 op,u32 offset,u32 value) {
    assert(got.len<400); got.trace[got.len++]=(struct event){op,offset,value};
}
static u32 offset(const void *addr) {
    uintptr_t a=(uintptr_t)addr, c=(uintptr_t)cpu, w=(uintptr_t)wrapper;
    assert(!(a&3));
    if(a>=c && a<c+sizeof(cpu)) return 0xd2000+(u32)(a-c);
    assert(a>=w && a<w+sizeof(wrapper)); return 0xe0000+(u32)(a-w);
}
static u32 readl(const void *addr) {
    u32 off=offset(addr), value;
    memcpy(&value,addr,4);
    if(off==0xd204c) value=(++polls>=ready_after)?ctrl_result:0;
    event(0,off,value);return value;
}
static void writel(u32 value,void *addr) {
    event(1,offset(addr),value);memcpy(addr,&value,4);
}
static void usleep_range(unsigned low,unsigned high) {
    assert(low==500 && high==1000);got.sleeps++;
}
static void dev_err(struct device *dev,const char *format,...) {
    (void)dev;(void)format;got.errors++;
}
'''

CHECKS = r'''
static struct venus_resources resources(unsigned kind) {
    switch(kind) {
    case 0:return (struct venus_resources){VPU_VERSION_AR50,HFI_VERSION_1XX};
    case 1:return (struct venus_resources){VPU_VERSION_AR50,HFI_VERSION_3XX};
    case 2:return (struct venus_resources){VPU_VERSION_AR50,HFI_VERSION_4XX};
    case 3:return (struct venus_resources){VPU_VERSION_IRIS1,HFI_VERSION_4XX};
#if !CONFIG_VIDEO_QCOM_IRIS
    case 4:return (struct venus_resources){VPU_VERSION_IRIS2,HFI_VERSION_6XX};
    case 5:return (struct venus_resources){VPU_VERSION_IRIS2_1,HFI_VERSION_6XX};
#endif
    case 6:return (struct venus_resources){VPU_VERSION_AR50_LITE,HFI_VERSION_4XX};
    default:assert(0);return (struct venus_resources){0};
    }
}
static struct capture run(unsigned kind,u32 input,bool boot,bool before,unsigned outcome,bool absent) {
    struct venus_resources res=resources(kind);struct device dev={0};
    struct venus_core core={&dev,&res,cpu,wrapper,NULL};
    struct venus_hfi_device hdev={&core,0x12345678};core.priv=absent?NULL:&hdev;
    memset(cpu,0,sizeof(cpu));memset(wrapper,0,sizeof(wrapper));memset(&got,0,sizeof(got));
    polls=0;ready_after=outcome==2?101:3;ctrl_result=outcome==1?4:1;
    wrapper[(boot?0x10:0xc)/4]=input;
    if(boot) got.result=before?baseline_venus_boot_core(&hdev):venus_boot_core(&hdev);
    else got.result=before?baseline_venus_isr(&core):venus_isr(&core);
    got.irq_status=hdev.irq_status;return got;
}
static void same(struct capture a,struct capture b) {
    assert(a.len==b.len && a.sleeps==b.sleeps && a.errors==b.errors);
    assert(a.result==b.result && a.irq_status==b.irq_status);
    assert(!memcmp(a.trace,b.trace,a.len*sizeof(struct event)));
}
static unsigned writes(struct capture c,struct event *out) {
    unsigned n=0;for(unsigned i=0;i<c.len;i++) if(c.trace[i].op==1) out[n++]=c.trace[i];return n;
}
int main(void) {
    const u32 masks[]={0,0x1f6,0xffffffff,0xa5a5a5a5,0x8,0x10};
    unsigned irq_cases=0,boot_cases=0,legacy_cases=0,absent_cases=0;
    for(unsigned kind=0;kind<7;kind++) {
#if CONFIG_VIDEO_QCOM_IRIS
        if(kind==4 || kind==5) continue;
#endif
        for(unsigned n=0;n<64;n++) {
            u32 status=(n&31)|((n&32)?0x40000000U:0);
            struct capture c=run(kind,status,false,false,0,false);assert(c.result==2);
            if(kind!=3) { same(c,run(kind,status,false,true,0,false));legacy_cases++; }
            else {
                struct event expect[2], actual[4];unsigned e=0;
                if(status&2) expect[e++]=(struct event){1,0xd2104,7};
                if(status&4) expect[e++]=(struct event){1,0xd201c,1};
                assert(writes(c,actual)==e);assert(!memcmp(expect,actual,e*sizeof(struct event)));
                assert(c.irq_status==((status&0x40000016U)?status:0x12345678U));
                assert(c.len==e+1 && c.trace[0].op==0 && c.trace[0].offset==0xe000c);
            }
            irq_cases++;
        }
        struct capture absent=run(kind,0x16,false,false,0,true);
        assert(absent.result==0 && !absent.len);absent_cases++;
        for(unsigned m=0;m<6;m++) for(unsigned outcome=0;outcome<3;outcome++) {
            struct capture c=run(kind,masks[m],true,false,outcome,false);
            assert(c.result==(outcome==2?-ETIMEDOUT:outcome==1?-EINVAL:0));
            assert(c.sleeps==(outcome==2?100:outcome==1?2:3));
            assert(c.errors==(outcome==1?1U:0U));
            if(kind!=3) { same(c,run(kind,masks[m],true,true,outcome,false));legacy_cases++; }
            else {
                struct event actual[4];assert(writes(c,actual)==2);
                assert(actual[0].offset==0xe0010 && actual[0].value==(masks[m]&~0x14U));
                assert(actual[1].offset==0xd2048 && actual[1].value==1);
                assert(c.trace[0].op==0 && c.trace[0].offset==0xe0010 && c.trace[0].value==masks[m]);
            }
            boot_cases++;
        }
    }
    printf("{\"config_iris\":%u,\"irq_cases\":%u,\"boot_cases\":%u,\"legacy_comparisons\":%u,\"absent_cases\":%u}\n",
        CONFIG_VIDEO_QCOM_IRIS,irq_cases,boot_cases,legacy_cases,absent_cases);
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('inventory', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--inventory-sha256', required=True)
    args = p.parse_args()
    root, out = args.inventory, args.output
    assert sha(root / 'sha256.json') == args.inventory_sha256
    hashes = json.loads((root / 'sha256.json').read_text())
    assert set(hashes) == {p.name for p in root.iterdir()} - {'sha256.json'}
    assert all(sha(root / name) == digest for name, digest in hashes.items())
    import importlib.util
    spec = importlib.util.spec_from_file_location('iris1_audit', root / 'audit_contracts.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    image = audit.load(root / 'audit_pep_loader.py', 'review_image').Image((root / 'oem-00040.sys').read_bytes())
    ranges, tables, listing = audit.contracts(image)
    report = json.loads((root / 'contracts.json').read_text())
    assert ranges == report['ranges'] and tables == report['retained_tables']
    out.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__), out / 'verify_interrupts.py')
    shutil.copyfile(root / 'linux-hfi_venus_io.h', out / 'linux-hfi_venus_io.h')
    core = (root / 'linux-core.h').read_text()
    helper = (root / 'linux-hfi_helper.h').read_text()
    definitions = block(core, 'enum vpu_version {') + '\n' + block(helper, 'enum hfi_version {')
    definitions += '\n' + core[core.index('#define IS_V1(core)'):core.index('static inline bool is_lite(')]
    before, after = ((root / name).read_text() for name in ('before-hfi_venus.c', 'linux-hfi_venus.c'))
    bodies = '\n'.join(block(after, marker) for marker in
                       ('static int venus_boot_core(', 'static irqreturn_t venus_isr('))
    baseline = '\n'.join(block(before, marker).replace('venus_boot_core(', 'baseline_venus_boot_core(')
                         .replace('venus_isr(', 'baseline_venus_isr(') for marker in
                         ('static int venus_boot_core(', 'static irqreturn_t venus_isr('))
    source = PREAMBLE + definitions + SCAFFOLD + baseline + '\n' + bodies + CHECKS
    (out / 'native.c').write_text(source)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    results = []

    def run(name, body, config, expected=0):
        cfile = out / (name + '.c')
        cfile.write_text(body)
        command = ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                   '-DCONFIG_VIDEO_QCOM_IRIS=' + str(config), str(cfile), '-o', str(out / name)]
        result = subprocess.run(command, capture_output=True, text=True)
        (out / (name + '.compile.stdout')).write_text(result.stdout)
        (out / (name + '.compile.stderr')).write_text(result.stderr)
        assert result.returncode == 0, (name, result.stderr)
        actual = subprocess.run([str(out / name)], capture_output=True, text=True)
        (out / (name + '.stdout')).write_text(actual.stdout)
        (out / (name + '.stderr')).write_text(actual.stderr)
        if expected == 0:
            assert actual.returncode == 0 and not actual.stderr, (name, actual.stderr)
        else:
            assert actual.returncode != 0 and 'Assertion' in actual.stderr, (name, actual.returncode)
        results.append(dict(name=name, compile=command, exit_code=actual.returncode,
                            checks=json.loads(actual.stdout) if expected == 0 else None))

    run('iris-disabled', source, 0)
    run('iris-enabled', source, 1)
    # Mutate only the actual candidate body, preserving baseline and external oracle.
    wrong_ack = bodies.replace('writel(CPU_CS_D2HSOFTINTCLR_MASK_IRIS1,', 'writel(1,')
    assert wrong_ack != bodies
    run('negative-dsp-ack', source.replace(bodies, wrong_ack), 0, 1)
    wrong_mask = bodies.replace('WRAPPER_INTR_MASK_A2HWD_BASK |', 'WRAPPER_INTR_MASK_A2HWD_BASK_V6 |', 1)
    assert wrong_mask != bodies
    run('negative-watchdog-bit', source.replace(bodies, wrong_mask), 0, 1)
    wrong_addr = bodies.replace('cpu_cs_base + CPU_CS_D2HSOFTINTCLR_IRIS1', 'cpu_cs_base + CPU_CS_A2HSOFTINTCLR')
    assert wrong_addr != bodies
    run('negative-dsp-register', source.replace(bodies, wrong_addr), 0, 1)
    output = dict(inventory_sha256=args.inventory_sha256, checked_pins=len(audit.PINS),
                  cases=results, original_instructions_executed=False, hardware_operations=0,
                  limits=['Actual C bodies use mock readl/writel/sleep; no firmware or MMIO operation.',
                          'Synthetic startup success/error/timeout is not hardware startup acceptance.',
                          'No SC8180X resource currently selects the Iris1 path.'])
    (out / 'review.json').write_text(json.dumps(output, indent=2) + '\n')
    manifest = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files': len(manifest), 'manifest_sha256': sha(out / 'sha256.json'),
                      'checks': [r['checks'] for r in results if r['checks']], 'negative_cases': 3}))


if __name__ == '__main__':
    main()
