#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare bounded original ARM64 header builders with actual Linux HFI C bodies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
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
    if source[end:end+1] == ';':
        end += 1
    return source[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('inventory', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--inventory-sha256', required=True)
    args = p.parse_args()
    assert os.uname().machine == 'aarch64', 'Original fragments require an ARM64 host.'
    root, out = args.inventory, args.output
    out.mkdir(mode=0o700)
    import importlib.util
    spec = importlib.util.spec_from_file_location('audit_video_startup', root / 'audit_startup.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.verify(root, args.inventory_sha256)
    report = json.loads((root / 'startup.json').read_text())
    image = audit.module(root / 'audit_pep_loader.py').Image((root / 'oem-00040.sys').read_bytes())
    ranges, listing, pins = audit.instructions(image)
    assert ranges == report['selected_ranges'] and pins == report['instruction_pins']
    assert image.exception_count == 2707
    inf = (root / 'qcsmmu8180.inf').read_text(encoding='utf-16')
    groups = audit.streams(inf)
    for name, rows in groups.items():
        for row, recorded in zip(rows, report['smmu_registry_groups'][name], strict=True):
            assert all(recorded[k] == v for k, v in row.items())
    for name, start, end in [('queue-builder.bin', 0x3611ac, 0x3612dc),
                             ('sys-init-builder.bin', 0x355a3c, 0x355a58)]:
        assert (root / name).read_bytes() == image.read(start, end - start)
        shutil.copyfile(root / name, out / name)
    shutil.copyfile(Path(__file__), out / 'verify_startup.py')
    source = (root / 'linux-hfi_venus.c').read_text()
    commands = (root / 'linux-hfi_cmds.c').read_text()
    cmd_header = (root / 'linux-hfi_cmds.h').read_text()
    helper = (root / 'linux-hfi_helper.h').read_text()
    definitions = source[source.index('#define HFI_MASK_QHDR_TX_TYPE'):source.index('#define QDSS_SIZE')]
    structures = '\n'.join(block(source, 'struct ' + name + ' {') for name in ('mem_desc', 'iface_queue'))
    structures += '\n' + block(helper, 'struct hfi_pkt_hdr {')
    structures += '\n' + block(cmd_header, 'struct hfi_sys_init_pkt {')
    structures += '\n' + block(cmd_header, 'struct hfi_sfr {')
    constants = '\n'.join(re.search(r'^#define ' + name + r'\s+.*$', text, re.M).group()
                           for text, name in [(cmd_header, 'HFI_CMD_SYS_INIT'), (helper, 'HFI_VIDEO_ARCH_OX')])
    bodies = '\n'.join(block(source, name) for name in [
        'static void venus_set_qhdr_defaults(', 'static int venus_interface_queues_init('])
    bodies += '\n' + block(commands, 'void pkt_sys_init(')
    # The surrounding allocation/barrier scaffolding accesses only ordinary RAM.
    # The copied Linux functions, definitions and structures remain verbatim.
    preamble = '''#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
typedef uint32_t u32;
typedef uint8_t u8;
typedef uint64_t dma_addr_t;
#define __counted_by(x)
#define SZ_4K 4096U
'''
    scaffolding = '''
#define ALIGN(x,a) (((x)+(a)-1U)&~((a)-1U))
#define ALIGNED_QUEUE_SIZE ALIGN(IFACEQ_TABLE_SIZE+IFACEQ_NUM*IFACEQ_QUEUE_SIZE,SZ_4K)
#define ALIGNED_SFR_SIZE SZ_4K
struct venus_hfi_device { struct mem_desc ifaceq_table,sfr; struct iface_queue queues[IFACEQ_NUM]; };
static unsigned poison, allocations;
static int venus_alloc(struct venus_hfi_device *hdev, struct mem_desc *desc, u32 size) {
    (void)hdev;
    desc->kva=malloc(size);assert(desc->kva);
    memset(desc->kva,poison,size);desc->da=0x100000U+allocations++*0x400000U;desc->size=size;
    return 0;
}
static void wmb(void) { __asm__ __volatile__("":::"memory"); }
extern void windows_queue_build(void *context);
extern void windows_sys_init_build(void *outer,void *packet);
'''
    main = '''
int main(void) {
    _Static_assert(sizeof(struct hfi_queue_table_header)==24,"table ABI");
    _Static_assert(sizeof(struct hfi_queue_header)==56,"queue ABI");
    _Static_assert(IFACEQ_TABLE_SIZE==192,"total ABI");
    _Static_assert(IFACEQ_QUEUE_SIZE==50*16384,"queue allocation");
    _Static_assert(sizeof(struct hfi_sys_init_pkt)==12,"packet ABI");
    unsigned queue_cases=0, matching_layouts=0;
    const u32 factors[]={1,32,50};
    for(unsigned pattern=0;pattern<2;pattern++) {
      poison=pattern?0xa5U:0;
      for(unsigned f=0;f<3;f++) {
        uint64_t context[0x8000/8]={0};
        u8 storage[192+64];memset(storage,0xc7,sizeof(storage));
        u8 *table=storage+32;memset(table,poison,192);
        u32 factor=factors[f],da=0x100000;
        memcpy((u8 *)context+0xd4,&factor,4);memcpy((u8 *)context+0x12c,&da,4);
        memcpy((u8 *)context+0x130,&table,8);
        windows_queue_build(context);
        const u32 th[]={0,192,24,56,3,3};assert(!memcmp(table,th,sizeof(th)));
        for(unsigned i=0;i<3;i++) {
          u32 expected[]={1,da+i*(factor<<14)+192,0x01010000U|i,factor*4096,
                          0,pattern?0xa5a5a5a5U:0,1,1,1,0,0,0,0,0};
          assert(!memcmp(table+24+56*i,expected,56));
          uint64_t hdr,kva;u32 start;
          memcpy(&hdr,(u8 *)context+0xd8+24*i,8);
          memcpy(&start,(u8 *)context+0xe0+24*i,4);
          memcpy(&kva,(u8 *)context+0xe8+24*i,8);
          assert(hdr==(uintptr_t)(table+24+56*i));assert(start==expected[1]);
          assert(kva==(uintptr_t)table+i*(factor<<14)+192);
        }
        for(unsigned i=0;i<32;i++)assert(storage[i]==0xc7 && storage[224+i]==0xc7);
        struct venus_hfi_device hdev={0};allocations=0;
        assert(!venus_interface_queues_init(&hdev));
        assert(!memcmp(hdev.ifaceq_table.kva,th,sizeof(th)));
        if(factor==50) {
          const u32 *a=(void *)table,*b=hdev.ifaceq_table.kva;
          for(unsigned w=0;w<192/4;w++) {
            if(w==42)assert(a[w]==1 && b[w]==0);else assert(a[w]==b[w]);
          }
          matching_layouts++;
        }
        free(hdev.ifaceq_table.kva);free(hdev.sfr.kva);queue_cases++;
      }
    }
    uint64_t outer[2]={0};u8 storage[32];memset(storage,0xc7,sizeof(storage));
    windows_sys_init_build(outer,storage+8);
    const u32 expected[]={12,0x10001,2};assert(!memcmp(storage+8,expected,12));
    for(unsigned i=0;i<8;i++)assert(storage[i]==0xc7);
    for(unsigned i=20;i<32;i++)assert(storage[i]==0xc7);
    struct hfi_sys_init_pkt pkt;pkt_sys_init(&pkt,HFI_VIDEO_ARCH_OX);
    assert(pkt.hdr.size==12 && pkt.hdr.pkt_type==0x10001 && pkt.arch_type==1);
    struct hfi_sys_init_pkt candidate;pkt_sys_init(&candidate,2);
    assert(!memcmp(&candidate,storage+8,sizeof(candidate)));
    printf("{\\"queue_cases\\":%u,\\"matching_layouts\\":%u,\\"debug_rx_req_difference\\":true,"
           "\\"windows_sys_init\\":[12,65537,2],\\"linux_sys_init\\":[12,65537,1],"
           "\\"linux_arch2_packet_matches\\":true}\\n",
           queue_cases,matching_layouts);
    return 0;
}
'''
    (out / 'hfi-native.c').write_text(preamble + definitions + structures + '\n' + constants +
                                    scaffolding + bodies + '\n' + main)
    for path in (out / 'queue-builder.bin', out / 'sys-init-builder.bin'):
        assert not any(c in str(path.resolve()) for c in '"\n\\')
    assembly = f'''/* AAPCS wrappers around the original, call-free ARM64 instruction fragments. */
.text
.align 2
.global windows_queue_build
.type windows_queue_build,%function
windows_queue_build:
    stp x19,x22,[sp,#-48]!
    stp x25,x26,[sp,#16]
    str x27,[sp,#32]
    mov x19,x0
    .incbin "{(out / 'queue-builder.bin').resolve()}"
    ldr x27,[sp,#32]
    ldp x25,x26,[sp,#16]
    ldp x19,x22,[sp],#48
    ret
.size windows_queue_build,.-windows_queue_build
.align 2
.global windows_sys_init_build
.type windows_sys_init_build,%function
windows_sys_init_build:
    stp x19,x30,[sp,#-16]!
    sub sp,sp,#48
    .incbin "{(out / 'sys-init-builder.bin').resolve()}"
    ldr x8,[sp,#24]
    ldr w9,[sp,#32]
    str x8,[x1]
    str w9,[x1,#8]
    add sp,sp,#48
    ldp x19,x30,[sp],#16
    ret
.size windows_sys_init_build,.-windows_sys_init_build
.section .note.GNU-stack,"",%progbits
'''
    (out / 'builders.S').write_text(assembly)
    command = ['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-g', '-O1',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               str(out / 'hfi-native.c'), str(out / 'builders.S'), '-o', str(out / 'hfi-native')]
    (out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (out / 'compile.stdout').write_text(compiled.stdout)
    (out / 'compile.stderr').write_text(compiled.stderr)
    assert compiled.returncode == 0 and not compiled.stderr
    native = subprocess.run([str(out / 'hfi-native')], capture_output=True, text=True, timeout=30)
    (out / 'native.stdout').write_text(native.stdout)
    (out / 'native.stderr').write_text(native.stderr)
    assert native.returncode == 0 and not native.stderr
    checks = json.loads(native.stdout)
    assert checks['queue_cases'] == 6 and checks['matching_layouts'] == 2
    rejected = []
    # Pin changes fail before native execution; original files remain untouched.
    for name, rva, replacement in [
        ('queue-header-size', 0x3611c8, image.read(0x3611b0, 4)),
        ('sys-init-arch', 0x355a50, struct.pack('<I', struct.unpack('<I', image.read(0x355a50, 4))[0] - 32)),
    ]:
        section = next(s for s in image.sections if s['rva'] <= rva < s['rva'] + s['size'])
        offset = section['raw'] + rva - section['rva']
        data = bytearray(image.data);data[offset:offset+4] = replacement
        path = out / (name + '.sys');path.write_bytes(data)
        try:
            audit.instructions(audit.module(root / 'audit_pep_loader.py').Image(bytes(data)))
        except AssertionError as error:
            rejected.append(dict(name=name, sha256=sha(path), reason=str(error)))
        else:
            raise AssertionError('accepted ' + name)
    changed = inf.replace('"MAP",%REG_BINARY%, 0xFF, 0x23, 0x00, 0x00, 0x60',
                          '"MAP",%REG_BINARY%, 0xFF, 0x13, 0x00, 0x00, 0x60', 1)
    assert changed != inf
    path = out / 'wrong-soc-sid.inf.txt';path.write_text(changed)
    try:
        audit.streams(changed)
    except AssertionError:
        rejected.append(dict(name='wrong-soc-sid', sha256=sha(path)))
    else:
        raise AssertionError('accepted wrong-soc-sid')
    result = dict(inventory_manifest_sha256=args.inventory_sha256,
                  selected_ranges_verified=len(ranges), instruction_pins_verified=len(pins),
                  native_checks=checks, actual_linux_c_functions_compiled=3,
                  original_arm64_fragments_executed=2, native_asan_ubsan_clean=True,
                  rejected_fixtures=rejected, hardware_operations=0,
                  limits=['Only original queue/packet construction fragments ran in synthetic RAM; no Windows services or driver startup executed.',
                          'ASan/UBSan instrument the C scaffolding and Linux bodies; assembly uses explicit table/packet sentinels.',
                          'SYS_INIT architecture 2 differs from Linux architecture 1; firmware acceptance of either is unobserved.',
                          'The debug queue rx_req policy differs (Windows1/Linux0); Linux deliberately suppresses debug interrupts.',
                          'No PAS9 authentication, MMIO operation, codec node or real-media test.'])
    (out / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
    hashes = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    audit.verify(out, sha(out / 'sha256.json'))
    print(json.dumps(result | dict(files=len(hashes), manifest_sha256=sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
