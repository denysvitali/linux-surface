#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check selected SQ2 ISP byte contracts against actual Linux register macros.

Vendor instructions are decoded as data. The generated native C program only
evaluates source macros; it cannot access registers, buses or camera devices.
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
CAMSS = REPO / 'drivers/media/platform/qcom/camss'
VENDOR = Path('/home/dvitali/Documents/drivers/FileRepository/'
              'qccamisp8180.inf_arm64_aeaf635adedd0c46/qccamisp8180.sys')
VENDOR_SHA = '39d8d130d03e703138be4f05dbd19d90a709eb961cc6c65cccdfac1dfd37471f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def defines(source):
    result, continuing = [], False
    for line in source.splitlines():
        if line.startswith('#define') or continuing:
            result.append(line)
            continuing = line.endswith('\\')
    assert not continuing
    return '\n'.join(result)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--csid-source', type=Path, default=CAMSS / 'camss-csid-gen2.c')
    parser.add_argument('--vfe-source', type=Path, default=CAMSS / 'camss-vfe-17x.c')
    parser.add_argument('--profile-source', type=Path, default=CAMSS / 'camss.c')
    args = parser.parse_args()
    out = args.output
    out.mkdir(mode=0o700)
    paths = {'qccamisp8180.sys': VENDOR, 'csid.c': args.csid_source,
             'vfe.c': args.vfe_source, 'profile.c': args.profile_source,
             'audit_isp_contract.py': Path(__file__).resolve()}
    inputs = {}
    for name, path in paths.items():
        inputs[name] = dict(path=str(path), sha256=sha(path))
        shutil.copyfile(path, out / name)
        assert sha(out / name) == inputs[name]['sha256']
    assert inputs['qccamisp8180.sys']['sha256'] == VENDOR_SHA
    data = (out / 'qccamisp8180.sys').read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[:2] == b'MZ' and data[pe:pe+4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
    count = struct.unpack_from('<H', data, pe+6)[0]
    optional = struct.unpack_from('<H', data, pe+20)[0]
    base = struct.unpack_from('<Q', data, pe+48)[0]
    assert base == 0x140000000
    sections = []
    for i in range(count):
        at = pe+24+optional+40*i
        vsize, rva, size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append(dict(name=data[at:at+8].split(b'\0')[0].decode(),
                             vsize=vsize, rva=rva, size=size, raw=raw))

    def read(rva, size):
        found = [s for s in sections if s['rva'] <= rva and
                 rva+size <= s['rva']+s['size']]
        assert len(found) == 1
        at = found[0]['raw']+rva-found[0]['rva']
        return data[at:at+size]

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoded, listing, ranges = {}, [], []
    # Exception-covered code ranges. The ISR excludes its final padding/literal.
    for start, end in [(0x1988, 0x1ebc), (0x11518, 0x11c34),
                       (0x15358, 0x1557c), (0x16020, 0x16374),
                       (0x18f78, 0x192a8), (0x1ad48, 0x1aef8),
                       (0x1aef8, 0x1b0a4), (0x1b0a8, 0x1b254)]:
        raw = read(start, end-start)
        instructions = list(md.disasm(raw, base+start))
        assert sum(i.size for i in instructions) == end-start
        ranges.append(dict(start_rva=start, end_rva=end,
                           bytes_sha256=hashlib.sha256(raw).hexdigest()))
        listing.append(f'\nRange {base+start:#x}..{base+end:#x}')
        for instruction in instructions:
            decoded[instruction.address-base] = (instruction.mnemonic,
                                                  instruction.op_str)
            listing.append(f'{instruction.address:#x}: {instruction.mnemonic} '
                           f'{instruction.op_str}')
    expected = {
        0x1162c: ('ldr', 'x3, [x19, #0x138]'),
        0x11648: ('add', 'x8, x3, #4, lsl #12'),
        0x11650: ('add', 'x9, x3, #2, lsl #12'),
        0x11654: ('stp', 'x8, x9, [x19, #0x140]'),
        0x19c0: ('ldr', 'w19, [x8]'),
        0x19d4: ('ubfx', 'w4, w19, #0x10, #0xc'),
        0x19ec: ('lsr', 'w4, w19, #0x1c'),
        0x153d4: ('ldr', 'x9, [x20, #0x140]'),
        0x153e8: ('str', 'w11, [x9, #0x100]'),
        0x15440: ('ldr', 'x8, [x20, #0x140]'),
        0x15444: ('str', 'w10, [x8, #0x104]'),
        0x1549c: ('bl', '#0x14001ad48'),
        0x154c4: ('bl', '#0x14001aef8'),
        0x154e8: ('bl', '#0x14001b0a8'),
        0x1ae28: ('cmp', 'w8, #4'),
        0x1ae2c: ('b.lt', '#0x14001ae8c'),
        0x16060: ('ldr', 'x8, [x19, #0x138]'),
        0x16074: ('ldr', 'w22, [x8, #0x6c]'),
        0x16080: ('ldr', 'w21, [x9, #0x70]'),
        0x16084: ('ldr', 'x8, [x19, #0x148]'),
        0x16088: ('ldr', 'w9, [x8, #0x5c]'),
        0x16098: ('ldr', 'w9, [x8, #0x60]'),
        0x160a8: ('ldr', 'w9, [x8, #0x64]'),
        0x160b8: ('str', 'w22, [x8, #0x64]'),
        0x160cc: ('str', 'w21, [x11, #0x68]'),
        0x160e4: ('str', 'w20, [x11, #0x58]'),
        0x160fc: ('str', 'w11, [x12, #0x50]'),
        0x16108: ('str', 'w8, [x9, #0x54]'),
        0x16114: ('str', 'w9, [x10, #0x58]'),
        0x16128: ('str', 'w20, [x8, #0x68]'),
        0x18f90: ('mov', 'w8, #3'),
        0x18f94: ('cmp', 'w21, #1'),
        0x18fa0: ('csel', 'w20, w8, wzr, eq'),
        0x19010: ('sub', 'w10, w23, #3, lsl #12'),
        0x19014: ('cmp', 'w10, #0x12'),
        0x19018: ('b.hi', '#0x14001927c'),
        0x1901c: ('adr', 'x9, #0x1400192a8'),
        0x19020: ('ldrsw', 'x8, [x9, w10, uxtw #2]'),
        0x19024: ('adr', 'x9, #0x140019198'),
        0x19028: ('add', 'x8, x9, x8, lsl #2'),
        0x1902c: ('br', 'x8'),
        0x19168: ('ldr', 'x8, [x19, #0x148]'),
        0x19170: ('str', 'w20, [x8, #0x208]'),
        0x19178: ('ldr', 'x8, [x19, #0x148]'),
        0x19180: ('str', 'w20, [x8, #0x308]'),
        0x19188: ('ldr', 'x8, [x19, #0x148]'),
        0x19190: ('str', 'w20, [x8, #0x408]'),
    }
    for at, instruction in expected.items():
        assert decoded[at] == instruction, (hex(at), decoded[at], instruction)
    jump_bytes = read(0x192a8, 19*4)
    jump_targets = [0x19198+entry*4 for entry in struct.unpack('<19i', jump_bytes)]
    assert jump_targets[6:9] == [0x19168, 0x19178, 0x19188]
    assert len(ranges) == 8
    # Decode both branches of each RDI writer rather than assuming one layout.
    relative = [0xc, 0x10, 0x14, 0x18, 0x24, 0x28, 0x2c, 0x30, 0x1c, 0x20, 0]
    csid_offsets = {}
    for rdi, branch_ranges in enumerate([((0x1ae30, 0x1ae88), (0x1ae8c, 0x1aee4)),
                                  ((0x1afe4, 0x1b038), (0x1b03c, 0x1b090)),
                                  ((0x1b194, 0x1b1e8), (0x1b1ec, 0x1b240))]):
        for lite, (start, end) in zip((True, False), branch_ranges):
            stores = [int(re.search(r'#(0x[0-9a-f]+)\]', operands)[1], 16)
                      for at, (mnemonic, operands) in decoded.items()
                      if start <= at < end and mnemonic == 'str']
            offsets = [((0x200 if lite else 0x300)+rdi*0x100)+x for x in relative]
            assert stores == offsets, (rdi, lite, stores)
            csid_offsets[f'{int(lite)},{rdi}'] = offsets
    csid = args.csid_source.read_text()
    vfe = args.vfe_source.read_text()
    profile = args.profile_source.read_text()
    sc8180 = re.search(r'sc8180x_resources = \{(.*?)\n\};', profile, re.S)[1]
    assert '.csid_res = csid_res_sc8280xp,' in sc8180
    assert '.vfe_res = vfe_res_sc8280xp,' in sc8180
    shared = re.search(r'vfe_res_sc8280xp\[\] = \{(.*?)\n\};', profile, re.S)[1]
    assert shared.count('.hw_ops = &vfe_ops_170,') == 8
    csid_names = ['CSID_RDI_FRM_DROP_PATTERN', 'CSID_RDI_FRM_DROP_PERIOD',
                  'CSID_RDI_IRQ_SUBSAMPLE_PATTERN', 'CSID_RDI_IRQ_SUBSAMPLE_PERIOD',
                  'CSID_RDI_RPP_PIX_DROP_PATTERN', 'CSID_RDI_RPP_PIX_DROP_PERIOD',
                  'CSID_RDI_RPP_LINE_DROP_PATTERN', 'CSID_RDI_RPP_LINE_DROP_PERIOD',
                  'CSID_RDI_CFG0']
    vfe_names = ['VFE_IRQ_STATUS_0', 'VFE_IRQ_STATUS_1', 'VFE_IRQ_CLEAR_0',
                 'VFE_IRQ_CLEAR_1', 'VFE_IRQ_CMD', 'VFE_BUS_IRQ_STATUS(0)',
                 'VFE_BUS_IRQ_STATUS(1)', 'VFE_BUS_IRQ_STATUS(2)',
                 'VFE_BUS_IRQ_CLEAR(0)', 'VFE_BUS_IRQ_CLEAR(1)',
                 'VFE_BUS_IRQ_CLEAR(2)', 'VFE_BUS_IRQ_CLEAR_GLOBAL',
                 'VFE_BUS_WM_CFG(0)', 'VFE_BUS_WM_CFG(1)', 'VFE_BUS_WM_CFG(2)']
    vendor_vfe = [0x6c, 0x70, 0x64, 0x68, 0x58, 0x205c, 0x2060, 0x2064,
                  0x2050, 0x2054, 0x2058, 0x2068, 0x2208, 0x2308, 0x2408]
    c = ('#include <stdio.h>\n#define BIT(n) (1u << (n))\n'
         'static int lite; static void *csid;\n'
         '#define csid_is_lite(p) ((void)(p), lite)\n'+defines(csid)+defines(vfe)+
         'int main(void) {\nfor(lite=0;lite<2;lite++) for(int rdi=0;rdi<3;rdi++) {\n')
    for name in csid_names:
        c += f'printf("CSID %d %d {name} %u\\n",lite,rdi,(unsigned){name}(rdi));\n'
    c += '}\n'
    for name in vfe_names:
        c += f'printf("VFE {name} %u\\n",(unsigned){name});\n'
    c += 'return 0; }\n'
    (out / 'linux-register-macros.c').write_text(c)
    command = ['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
               str(out / 'linux-register-macros.c'), '-o', str(out / 'linux-register-macros')]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (out / 'compile.json').write_text(json.dumps(dict(command=command,
        returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2)+'\n')
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(out / 'linux-register-macros')], capture_output=True,
                            text=True, timeout=5)
    (out / 'macro-output.json').write_text(json.dumps(dict(returncode=result.returncode,
        stdout=result.stdout, stderr=result.stderr), indent=2)+'\n')
    assert result.returncode == 0 and not result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 69
    for line in lines[:54]:
        _, lite, rdi, name, actual = line.split()
        index = csid_names.index(name)
        vendor_index = index if index < 8 else 10
        assert int(actual) == csid_offsets[f'{lite},{rdi}'][vendor_index], line
    for line, name, value in zip(lines[54:], vfe_names, vendor_vfe):
        assert line == f'VFE {name} {value}', (line, value)
    report = dict(inputs=inputs, selected_ranges=ranges,
                  selected_instruction_contracts=len(expected),
                  csid_branch_register_stores_verified=66,
                  linux_macro_values_verified=69,
                  base_contract={'csid_from_vfe': 0x4000, 'bus_from_vfe': 0x2000},
                  csid_branch_offsets=csid_offsets,
                  vfe_bus_client_jump_table={'rva': 0x192a8,
                      'bytes_sha256': hashlib.sha256(jump_bytes).hexdigest(),
                      'target_rvas': jump_targets,
                      'rdi_port_ids': [0x3006, 0x3007, 0x3008]},
                  vfe_offsets=dict(zip(vfe_names, vendor_vfe)),
                  actual_hardware_revision_measured=False,
                  analog_supply_mapping_established=False, hardware_operations=0,
                  limits=['The register subset supports reuse, not whole-program equality.',
                          'Static VFE revision decode is not an expected or measured revision.',
                          'Vendor RDI0 sets CGC bit8; Linux leaves dynamic gating selected.',
                          'Crop, decode/packing modes, clock votes, IRQ timing and DMA frames are unvalidated.',
                          'No rail requirement changes, register reads or capture are authorized by this evidence.'])
    (out / 'selected-functions.txt').write_text('\n'.join(listing)+'\n')
    (out / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    manifest = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(manifest, indent=2)+'\n')
    assert all(sha(out / name) == digest for name, digest in manifest.items())
    print(json.dumps(dict(output=str(out), files_verified=len(manifest),
                         linux_macro_values_verified=69,
                         manifest_sha256=sha(out / 'sha256.json'))))


if __name__ == '__main__':
    main()
