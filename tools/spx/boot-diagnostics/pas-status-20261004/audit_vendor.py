#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Retain PIL request construction as offline bytes; never execute vendor code."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DRIVERS = Path('/home/dvitali/Documents/drivers/FileRepository')
INPUTS = {
    'qcpil8180.sys': ('qcpil8180.inf_arm64_33f5ea4e4b666c6f',
                     '0821cba482219b0aac2c0c47c4149d06a385013a4ebfa30211ed653f5b8ea242'),
    'qcscm8180.sys': ('qcscm8180.inf_arm64_3a013e5b30a369ac',
                     'e17a061b18273f3f87d2781a4d5a31ba57663f7616bfc9d64a9bb74153a01e0a'),
    'QcTrEE8180.sys': ('surfaceprox_tree.inf_arm64_aa897ec6bd060d05',
                      '2d8805c2b9b7363753d733c5770c8560f2cea594f48483f32bf477fc4eb135ab'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    out = ap.parse_args().out
    out.mkdir(mode=0o700)
    helper = ROOT / 'tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_loader.py'
    shutil.copy2(helper, out / 'pe_reader.py')
    spec = importlib.util.spec_from_file_location('pil_pe_reader', out / 'pe_reader.py')
    pe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe)
    inputs = {}
    literal_hits = {}
    for name, (directory, expected) in INPUTS.items():
        source = DRIVERS / directory / name
        assert sha(source) == expected, source
        shutil.copy2(source, out / name)
        inputs[name] = dict(path=str(source), sha256=expected, bytes=source.stat().st_size)
        data = source.read_bytes()
        # A missing literal does not exclude arithmetic construction or hidden firmware.
        literal_hits[name] = {hex(value): [hex(i) for i in range(len(data)-3)
                              if data[i:i+4] == struct.pack('<I', value)]
                             for value in (0xffcfffba, 0x300046)}
    image = pe.Image((out / 'qcpil8180.sys').read_bytes())
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    listing, decoded = [], {}
    ranges = [(0x7e20, 0x85c8), (0x85c8, 0x8830),
              (0x9370, 0x9afc), (0xbd60, 0xc568)]
    for start, end in ranges:
        assert image.functions[start] == end
        raw = image.read(start, end-start)
        (out / f'pil-{start:x}-{end:x}.bin').write_bytes(raw)
        listing.append(f'\n.pdata function {start:#x}..{end:#x}')
        for ins in md.disasm(raw, image.base+start):
            at = ins.address-image.base
            decoded[at] = (ins.mnemonic, ins.op_str)
            listing.append(f'{at:#x}: {ins.mnemonic} {ins.op_str}')
    pins = {
        0x854c: ('ldr', 'w8, [x20, #0x28]'),
        0x8550: ('str', 'w8, [x11, #0xf0]'),
        0x855c: ('ldr', 'x8, [x20, #0x40]'),
        0x8560: ('str', 'x8, [x11, #0xe8]'),
        0x86c4: ('str', 'xzr, [x21, #0xe0]'),
        0x86c8: ('str', 'xzr, [x21, #0xe8]'),
        0xc0b4: ('mov', 'w1, #0x202'),
        0xc0b8: ('movk', 'w1, #0x200, lsl #16'),
        0xc0c0: ('bl', '#0x140009370'),
        0x995c: ('mov', 'w8, #0x202'),
        0x9960: ('movk', 'w8, #0x200, lsl #16'),
        0x9964: ('str', 'w8, [x2]'),
        0x9968: ('mov', 'x8, #3'),
        0x996c: ('str', 'w8, [x2, #4]'),
        0x9970: ('ldrsw', 'x8, [x0, #0x28]'),
        0x9974: ('str', 'x8, [x2, #8]'),
        0x9978: ('ldr', 'x8, [x0, #0xe8]'),
        0x997c: ('str', 'x8, [x2, #0x10]'),
        0x9980: ('ldr', 'w9, [x0, #0xf0]'),
        0x9988: ('add', 'w8, w9, #0xfff'),
        0x998c: ('and', 'w9, w8, #0xfffff000'),
        0x9994: ('str', 'x8, [x2, #0x18]'),
        0x99a8: ('mov', 'w9, #0x1000'),
    }
    for at, expected in pins.items():
        assert decoded[at] == expected, (hex(at), decoded[at], expected)
    table = struct.unpack('<11i', image.read(0x9ac4, 44))
    assert 0x9750 + table[1]*4 == 0x986c  # 0x02000202 branch
    report = dict(inputs=inputs, reader_sha256=sha(helper),
                  request_function_rva='0x9370', request_function_end='0x9afc',
                  memory_wrapper_rva='0xbd60', memory_wrapper_end='0xc568',
                  memory_command='0x02000202', parameter_descriptor=3,
                  processor_context_offset='0x28', physical_context_offset='0xe8',
                  length_context_offset='0xf0', length_rounding_bytes=4096,
                  physical_source_descriptor_offset='0x40',
                  length_source_descriptor_offset='0x28',
                  zero_length_substitution_bytes=4096,
                  decoded_instruction_pins=len(pins), literal_hits=literal_hits,
                  encoded_status_meaning_identified=False,
                  actual_windows_execution_observed=False,
                  acceptable_physical_memory_established=False)
    (out / 'pil-functions.txt').write_text('\n'.join(listing)+'\n')
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    shutil.copy2(__file__, out / Path(__file__).name)
    hashes = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2)+'\n')
    assert all(sha(out/name) == digest for name, digest in hashes.items())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
