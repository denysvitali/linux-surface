#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare pinned MIPI PHY bytes with extracted Linux register programming.

Vendor code is decoded as data only. The Linux harness uses modeled MMIO.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

REPO = Path(__file__).resolve().parents[4]
VENDOR = Path('/home/dvitali/Documents/drivers/FileRepository/'
              'qccammipicsi8180.inf_arm64_b579e0018fd8f1d6/qccammipicsi8180.sys')
PHY = REPO / 'drivers/media/platform/qcom/camss/camss-csiphy-3ph-1-0.c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(source, name):
    match = re.search(r'^static (?:void|bool|u8)\s+'+name+r'\s*\(', source, re.M)
    assert match, name
    start = source.index('{', match.end())
    depth, end = 1, start+1
    while depth:
        depth += (source[end] == '{')-(source[end] == '}')
        end += 1
    return source[match.start():end]


def table(source, name):
    match = re.search(r'csiphy_lane_regs '+name+r'\[\] = \{(.*?)\n\};', source, re.S)
    assert match, name
    entries = re.findall(r'\{(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+),\s*(CSIPHY_[A-Z_]+)\}', match[1])
    assert len(entries) == match[1].count('{')
    return [dict(offset=int(a, 16), value=int(v, 16), delay_us=int(d, 16), parameter=p)
            for a, v, d, p in entries], 'static const struct csiphy_lane_regs '+name+'[] = {'+match[1]+'\n};\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--phy-source', type=Path, default=PHY)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)
    inputs = {}
    for name, path in {'qccammipicsi8180.sys': VENDOR, 'phy-final.c': args.phy_source,
                       'camss-final.c': REPO / 'drivers/media/platform/qcom/camss/camss.c',
                       'ov13858.c': REPO / 'drivers/media/i2c/ov13858.c',
                       'audit_phy_program.py': Path(__file__).resolve()}.items():
        inputs[name] = dict(path=str(path), sha256=sha(path))
        shutil.copyfile(path, args.output / name)
    assert inputs['qccammipicsi8180.sys']['sha256'] == '39e299af8ada6d80778f510c363085f49c5a06d94d418ce98ea87065c806a306'
    (args.output / 'inputs.json').write_text(json.dumps(inputs, indent=2)+'\n')
    data = VENDOR.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe+4] == b'PE\0\0' and struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
    count, optional = struct.unpack_from('<H', data, pe+6)[0], struct.unpack_from('<H', data, pe+20)[0]
    sections = []
    for i in range(count):
        at = pe+24+optional+40*i
        virtual, rva, size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append(dict(name=data[at:at+8].split(b'\0')[0].decode(),
                             virtual=virtual, rva=rva, size=size, raw=raw))

    def read(rva, size):
        found = [s for s in sections if s['rva'] <= rva and rva+size <= s['rva']+s['size']]
        assert len(found) == 1, (hex(rva), size)
        at = found[0]['raw']+rva-found[0]['rva']
        return data[at:at+size]

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoded = {}
    listing = []
    for start, end in [(0x4488, 0x4590), (0x4590, 0x47c4), (0x47e0, 0x48ac)]:
        instructions = list(md.disasm(read(start, end-start), 0x140000000+start))
        assert len(instructions)*4 == end-start
        for ins in instructions:
            decoded[ins.address-0x140000000] = (ins.mnemonic, ins.op_str)
            listing.append(f'{ins.address:#x}: {ins.mnemonic} {ins.op_str}\n')
    # Byte-decoded instruction contracts establish width/stride and selected pointers.
    expected = {
        0x44c0: ('mov', 'x9, #0xc'), 0x44c4: ('madd', 'x10, x8, x9, x23'),
        0x44c8: ('ldp', 'w8, w9, [x10]'), 0x44cc: ('str', 'w9, [x21, w8, uxtw]'),
        0x44d0: ('ldr', 'w22, [x10, #8]'),
        0x4800: ('add', 'x1, x21, #0x4e0'), 0x4804: ('mov', 'x2, #1'),
        0x4824: ('add', 'x11, x21, #0x3a0'),
        0x4828: ('ldr', 'w8, [x11, w9, sxtw #2]'),
        0x482c: ('ldr', 'w10, [x20, w8, uxtw]'),
        0x4850: ('mov', 'w8, #0x10000000'), 0x4854: ('cmp', 'w19, w8'),
        0x4858: ('b.eq', '#0x14000489c'),
        0x4704: ('mov', 'x2, #0x36'), 0x4708: ('add', 'x1, x21, #0x1c0'),
        0x4718: ('mov', 'x2, #5'), 0x471c: ('mov', 'x1, x24'),
        0x472c: ('mov', 'x2, #1'), 0x4730: ('mov', 'x1, x20'),
        0x4754: ('mov', 'x2, #0xc'), 0x4758: ('add', 'x1, x21, #0x470'),
        0x4764: ('mov', 'x2, #0xb'), 0x4768: ('add', 'x1, x21, #0x500'),
        0x45c0: ('adrp', 'x8, #0x140009000'),
        0x45c4: ('add', 'x25, x8, #0x6f0'),
        0x45dc: ('adrp', 'x9, #0x14000b000'),
        0x45e0: ('add', 'x24, x9, #0x210'),
        0x4650: ('adrp', 'x8, #0x14000b000'),
        0x4654: ('add', 'x20, x8, #0x250'),
        0x46c4: ('ldr', 'x9, [x19, #0x18]'),
        0x46c8: ('ldr', 'x8, #0x1400047c8'),
        0x46cc: ('ldr', 'x10, #0x1400047d0'),
        0x46d0: ('adrp', 'x11, #0x140009000'),
        0x46d4: ('add', 'x21, x11, #0x560'),
        0x46dc: ('cmp', 'x8, x10'),
        0x46e0: ('b.hi', '#0x1400046ec'),
        0x46e4: ('add', 'x22, x21, #0xc0'),
        0x46ec: ('ldr', 'x8, #0x1400047d8'),
        0x46f0: ('cmp', 'x9, x8'),
        0x46f4: ('b.ls', '#0x140004700'),
        0x46f8: ('mov', 'x22, x21'),
        0x46fc: ('mov', 'x23, #0xa'),
        0x4740: ('mov', 'x2, x23'), 0x4744: ('mov', 'x1, x22'),
        0x4748: ('bl', '#0x140004488'),
        0x47f8: ('adrp', 'x8, #0x140009000'),
        0x47fc: ('add', 'x21, x8, #0x608'),
    }
    for at, pair in expected.items():
        assert decoded[at] == pair, (hex(at), decoded[at], pair)
    selected_contract_count = len(expected)
    (args.output / 'selected-functions.txt').write_text(''.join(listing))
    tables = {}
    for name, rva, count in [('common', 0x9720, 54), ('settle', 0xb210, 5),
                             ('lane_enable', 0xb250, 1), ('reset', 0x9708, 2),
                             ('revision_request', 0x9ae8, 1),
                             ('irq_clear', 0x99d0, 12), ('irq_masks', 0x9a60, 11),
                             ('rate_1500_to_2000', 0x9620, 10), ('rate_above_2000', 0x9560, 10)]:
        raw = read(rva, count*12)
        tables[name] = dict(rva=rva, count=count, bytes_sha256=hashlib.sha256(raw).hexdigest(),
                            entries=[dict(zip(['offset', 'value', 'delay_us'],
                                              struct.unpack_from('<III', raw, i*12))) for i in range(count)])
    offsets = struct.unpack('<4I', read(0x99a8, 16))
    assert offsets == (0x8e0, 0x8e4, 0x8e8, 0x8ec)
    assert tables['revision_request']['entries'] == [dict(offset=0x818, value=2, delay_us=0)]
    literals = {hex(rva): struct.unpack('<q', read(rva, 8))[0] for rva in [0x47c8, 0x47d0, 0x47d8]}
    assert list(literals.values()) == [-1500000000, 500000000, 2000000000]
    source = args.phy_source.read_text()
    linux, declaration = table(source, 'lane_regs_sdm845')
    other, _ = table(source, 'lane_regs_sc8280xp')
    fixed = {r['offset']: r['value'] for r in linux if r['parameter'] == 'CSIPHY_DEFAULT_PARAMS'}
    dynamic = {r['offset'] for r in linux if r['parameter'] == 'CSIPHY_SETTLE_CNT_LOWER_BYTE'}
    dnp = {r['offset'] for r in linux if r['parameter'] == 'CSIPHY_DNP_PARAMS'}
    vendor = {r['offset']: r['value'] for r in tables['common']['entries']}
    common = {0x818, 0x81c}
    matched = {k: v for k, v in vendor.items() if k not in dynamic|common}
    assert all(fixed[k] == v for k, v in matched.items())
    extra = {k: v for k, v in fixed.items() if k not in vendor}
    assert len(extra) == 10 and len(dynamic) == 5
    assert all(k % 0x100 in [0x60, 0x64] for k in extra)
    differences = [r['offset'] for r in other if r['parameter'] == 'CSIPHY_DEFAULT_PARAMS'
                   and r['offset'] in matched and r['value'] != matched[r['offset']]]
    assert differences == [0, 0x200, 0x400, 0x600]
    selector = re.search(r'if \(of_device_is_compatible\(dev->of_node,\s*"qcom,sc8180x-camss"\)\) \{(.*?)\} else \{(.*?)\}', source, re.S)
    assert selector and 'regs->lane_regs = &lane_regs_sdm845[0];' in selector[1]
    assert 'regs->lane_regs = &lane_regs_sc8280xp[0];' in selector[2]
    defines = '\n'.join(line for line in source.splitlines()
                        if re.match(r'#define CSIPHY_(DEFAULT_PARAMS|SETTLE_CNT_LOWER_BYTE|SKEW_CAL|DNP_PARAMS)\b', line))
    harness = '''#include <stdint.h>
#include <stdio.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef int32_t s32;
typedef int64_t s64;
struct csiphy_lane_regs { s32 reg_addr,reg_data; u32 delay_us,csiphy_param_type; };
struct csiphy_device_regs { const struct csiphy_lane_regs *lane_regs; int lane_array_size; };
struct csiphy_device { struct csiphy_device_regs *regs; unsigned char *base; };
static unsigned char bus[4096];
static void writel_relaxed(u32 value,void *address) {
 printf("%ld %u\\n",(unsigned char *)address-bus,value);
}
static void udelay(u32 delay) { (void)delay; }
static uint64_t div_u64(uint64_t a,uint64_t b) { return a/b; }
'''+defines+'\n'+declaration+function(source, 'csiphy_gen2_config_lanes')+'\n'+function(source, 'csiphy_settle_cnt_calc')+'''
int main(void) {
 struct csiphy_device_regs r={lane_regs_sdm845,sizeof(lane_regs_sdm845)/sizeof(lane_regs_sdm845[0])};
 struct csiphy_device d={&r,bus};
 int64_t rates[]={270000000,540000000};
 for(unsigned int i=0;i<2;i++) {
  u8 settle=csiphy_settle_cnt_calc(rates[i],300000000);
  printf("RATE %ld %u\\n",rates[i],settle);
  csiphy_gen2_config_lanes(&d,settle);
 }
 return 0;
}
'''
    (args.output / 'linux-phy-harness.c').write_text(harness)
    command = ['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               str(args.output / 'linux-phy-harness.c'), '-o', str(args.output / 'linux-phy-harness')]
    compile_result = subprocess.run(command, capture_output=True, text=True)
    (args.output / 'compile.json').write_text(json.dumps(dict(command=command,
        returncode=compile_result.returncode, stdout=compile_result.stdout,
        stderr=compile_result.stderr), indent=2)+'\n')
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([str(args.output / 'linux-phy-harness')], capture_output=True, text=True)
    (args.output / 'harness-result.json').write_text(json.dumps(dict(
        returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2)+'\n')
    assert result.returncode == 0, result.stderr
    traces, rate = {}, None
    for line in result.stdout.splitlines():
        if line.startswith('RATE'):
            _, frequency, settle = line.split()
            rate = int(frequency)
            traces[rate] = dict(settle=int(settle), writes=[])
        else:
            offset, value = map(int, line.split())
            traces[rate]['writes'].append(dict(offset=offset, value=value))
    for rate, trace in traces.items():
        expected_trace = [dict(offset=r['offset'], value=trace['settle'] if r['offset'] in dynamic else r['value'])
                    for r in linux if r['offset'] not in dnp]
        assert trace['writes'] == expected_trace
        assert trace['settle'] == (22 if rate == 270000000 else 21)
        actual = {r['offset']: r['value'] for r in trace['writes']}
        assert all(actual[k] == v for k, v in matched.items())
    report = dict(sections=sections, selected_byte_decoded_contracts=selected_contract_count,
                  expected_phy_revision=0x10000000, revision_offsets=offsets,
                  tables=tables, rate_branch_literals=literals,
                  vendor_common_fixed_matching_linux=len(matched), dynamic_settle_offsets=sorted(dynamic),
                  linux_extra_calibration_writes=extra, sc8280_fixed_mismatch_offsets=differences,
                  linux_trace=traces,
                  limits=['Vendor bytes decoded only; no vendor execution or hardware MMIO',
                          'Expected revision is a vendor check, not a live hardware revision measurement',
                          'Conditional rate input context field units and full caller path not established',
                          'Linux extra calibration/IRQ/order/settle behavior is not exact vendor equivalence',
                          'No analog provider/ownership, CSID/VFE revision or capture acceptance'])
    (args.output / 'phy-program-contract.json').write_text(json.dumps(report, indent=2)+'\n')
    files = sorted(p for p in args.output.iterdir() if p.is_file())
    (args.output / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in files))
    print(json.dumps(dict(output=str(args.output), fixed_matches=len(matched),
                          dynamic_settle=len(dynamic), extra_linux=len(extra),
                          sc8280_mismatches=differences,
                          modeled_trace_writes=sum(len(v['writes']) for v in traces.values()),
                          manifest_sha256=sha(args.output / 'SHA256SUMS'))))


if __name__ == '__main__':
    main()
