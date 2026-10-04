#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify retained SQ2 UC reservation and Iris1 interrupt contracts offline."""
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
REPO = next((p for p in Path(__file__).resolve().parents if (p / 'PORT-CHECKLIST.md').is_file()),
            Path('/home/dvitali/Documents/git/linux-surface-next'))
PRIOR = Path('/var/tmp/spx-video-startup-20261003-v4')
PRIOR_SHA = '9196bea5634ff8df0491ba656e525f15cedc03f64acdea4f6f9ea81a3d0d023a'
PREIMAGE = Path('/var/tmp/spx-video-iris1-preimage-20261003')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RANGES = [(0x34a788, 0x34b834), (0x357a10, 0x359ac8),
          (0x356978, 0x35748c), (0x3648f0, 0x364df4),
          (0x365400, 0x365a4c), (0x366340, 0x366aac),
          (0x3f1c0, 0x403c8), (0x403c8, 0x415f4)]
PINS = {
    0x34b3b8: ('add', 'x8, x7, #0x310'),
    0x34b454: ('add', 'x24, x8, #0x8c0'),
    0x34b474: ('add', 'x22, x12, #0x6b0'),
    0x34b6d4: ('mov', 'x10, #0x7060'),
    0x34b780: ('mov', 'x10, #0x7268'),
    0x35843c: ('ldp', 'w8, w9, [x8, #0x24]'),
    0x358444: ('add', 'w10, w9, w8'),
    0x358450: ('sub', 'w19, w10, w12'),
    0x358460: ('mov', 'w4, w19'),
    0x358464: ('mov', 'w3, #4'),
    0x358468: ('mov', 'w2, w21'),
    0x35846c: ('add', 'x1, x22, #0x120'),
    0x358474: ('blr', 'x20'),
    0x364954: ('ldp', 'w20, w19, [x23, #0x14]'),
    0x364964: ('mov', 'x1, x19'),
    0x364968: ('mov', 'x0, x20'),
    0x365444: ('mov', 'w19, w3'),
    0x365448: ('mov', 'w23, w4'),
    0x36544c: ('mov', 'w24, w5'),
    0x3654a8: ('add', 'x3, x8, #0xf88'),
    0x365530: ('mov', 'w6, w24'),
    0x365534: ('mov', 'w5, w23'),
    0x36554c: ('blr', 'x19'),
    0x3656bc: ('blr', 'x8'),
    0x3656c4: ('str', 'x0, [x8, #0x28]'),
    0x366640: ('cmp', 'w9, #1'),
    0x366648: ('ldr', 'x19, [x8, #0x78]'),
    0x366664: ('ldr', 'w2, [sp, #0x48]'),
    0x366674: ('blr', 'x19'),
    0x366878: ('ldr', 'x19, [x8, #0xc8]'),
    0x366894: ('ands', 'x22, x24, #-0x100000000'),
    0x356df8: ('ldp', 'w8, w9, [x8, #0x24]'),
    0x356e0c: ('str', 'w11, [x9, #0x64]'),
    0x3f804: ('tst', 'w9, #0xfffffff7'),
    0x3f808: ('b.eq', '#0x14003fa7c'),
    0x3fa7c: ('tbz', 'w23, #1, #0x14003fbbc'),
    0x3fa9c: ('mov', 'w10, #7'),
    0x3faa4: ('str', 'w10, [x9, #0x104]'),
    0x3fbbc: ('tbz', 'w23, #2, #0x14003fcf4'),
    0x3fbdc: ('mov', 'w10, #1'),
    0x3fbe4: ('str', 'w10, [x9, #0x1c]'),
}


def contracts(image):
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    decoded, records, listing = {}, [], []
    for start, end in RANGES:
        assert image.functions[start] == end
        raw = image.read(start, end - start)
        insns = list(md.disasm(raw, image.base + start))
        assert sum(i.size for i in insns) == len(raw)
        records.append(dict(start=start, end=end, sha256=hashlib.sha256(raw).hexdigest()))
        listing.append(f'FUNCTION {start:#x}..{end:#x}')
        for i in insns:
            at = i.address - image.base
            decoded[at] = (i.mnemonic, i.op_str)
            listing.append(f'{at:#x}: {i.mnemonic} {i.op_str}')
    for at, expected in PINS.items():
        assert decoded[at] == expected, (hex(at), decoded[at], expected)
    tables = {}
    for base in (0x1b56b0, 0x1b58c0):
        count = struct.unpack('<I', image.read(base, 4))[0]
        assert count == 4
        rows = [list(struct.unpack('<18I', image.read(base + 16 + n * 72, 72)))
                for n in range(count)]
        assert rows[0][5:7] == [0x25800000, 0xba800000]
        assert [r[1] for r in rows] == [0, 1, 3, 4]
        tables[hex(base)] = rows
    assert [r[4] for r in tables['0x1b58c0']] == [0x4030000, 0x4090000, 0x40a0000, 0x40b0000]
    allocator = struct.unpack('<Q', image.read(0x1ac050 + 0x38, 8))[0] - image.base
    reservation = struct.unpack('<Q', image.read(0x1ac050 + 0x50, 8))[0] - image.base
    assert allocator == 0x365400 and reservation == 0x366340
    return records, tables, listing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    prior = load(PRIOR / 'audit_startup.py', 'prior_video_audit')
    prior.verify(PRIOR, PRIOR_SHA)
    out = args.output
    out.mkdir(mode=0o700)
    inputs = {}
    paths = {n: PRIOR / n for n in ('oem-00040.sys', 'audit_pep_loader.py', 'dsdt.dsl')}
    paths.update({'audit_contracts.py': Path(__file__).resolve()})
    for name in ('hfi_venus.c', 'hfi_venus_io.h', 'core.h', 'hfi_helper.h'):
        paths['linux-' + name] = REPO / 'drivers/media/platform/qcom/venus' / name
    for name in ('hfi_venus.c', 'hfi_venus_io.h'):
        paths['before-' + name] = PREIMAGE / name
    for name in ('venus_hfi.c', 'vidc_hfi_io.h', 'fetch.json'):
        paths['android-' + name] = Path('/var/tmp/spx-video-integration-fetch-20261003') / name
    expected = {'android-venus_hfi.c': '940f3b0cb9fe8967d9e375b1ba82873cf1eb0180e85b0dff618de6569bd15d2e',
                'before-hfi_venus.c': '8a3e0f50b0894063e91c4f7040f22f2bd443be45525521eed6e5877cab1df486',
                'before-hfi_venus_io.h': 'eddecf2411a8fad132ecec02323ba8037a09360b1bc43b10746e4d3bfde68b38'}
    for name, source in paths.items():
        digest = sha(source)
        if name in expected:
            assert digest == expected[name], name
        shutil.copyfile(source, out / name)
        assert sha(out / name) == digest
        inputs[name] = dict(path=str(source), sha256=digest)
    image = load(out / 'audit_pep_loader.py', 'video_image').Image((out / 'oem-00040.sys').read_bytes())
    ranges, tables, listing = contracts(image)
    (out / 'disassembly.txt').write_text('\n'.join(listing) + '\n')
    report = dict(inputs=inputs, ranges=ranges, pins=[dict(rva=at, mnemonic=m, operands=o)
                  for at, (m, o) in PINS.items()], retained_tables=tables,
                  table_nonsecure_iova_start=0x25800000, table_nonsecure_iova_length=0xba800000,
                  table_uc_iova=0xdf000000, uc_window_size=0x1000000,
                  physical_firmware_reservation=None, live_iova_observed=False,
                  hardware_operations=0,
                  limits=['Static original instructions and tables are not a Windows startup run.',
                          'ASL VideoNonSecurePT pool differs from retained miniport defaults.',
                          'A VCM IOVA reservation is not a physical RAM firmware reservation.',
                          'No SC8180X resource/DT enables this Iris1 code yet.'])
    (out / 'contracts.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps({'files': len(hashes), 'pins': len(PINS), 'manifest_sha256': sha(out / 'sha256.json')}))


if __name__ == '__main__':
    main()
