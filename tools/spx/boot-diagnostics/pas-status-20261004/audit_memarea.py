#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pin vendor PIL area-query and allocator dataflow without executing it."""
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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    out = p.parse_args().out
    out.mkdir(mode=0o700)
    vendor = Path('/home/dvitali/Documents/drivers/FileRepository/') / (
        'qcpil8180.inf_arm64_33f5ea4e4b666c6f/qcpil8180.sys')
    assert sha(vendor) == '0821cba482219b0aac2c0c47c4149d06a385013a4ebfa30211ed653f5b8ea242'
    helper = ROOT / 'tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_loader.py'
    shutil.copy2(helper, out / 'pe_reader.py')
    spec = importlib.util.spec_from_file_location('area_pe', out / 'pe_reader.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    shutil.copy2(vendor, out / vendor.name)
    image = reader.Image(vendor.read_bytes())
    ranges = [(0x6200, 0x64fc), (0x68f0, 0x6a18), (0x7090, 0x72f8),
              (0x7348, 0x74b8), (0x7e20, 0x85c8), (0x9370, 0x9afc),
              (0xc568, 0xcaec), (0x115f0, 0x117b0), (0x117b8, 0x119f0)]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    listing, instructions = [], {}
    for start, end in ranges:
        assert image.functions[start] == end
        raw = image.read(start, end-start)
        (out / f'pil-{start:x}-{end:x}.bin').write_bytes(raw)
        listing.append(f'\n.pdata function {start:#x}..{end:#x}')
        for i in md.disasm(raw, image.base+start):
            at = i.address-image.base
            instructions[at] = (i.mnemonic, i.op_str)
            listing.append(f'{at:#x}: {i.mnemonic} {i.op_str}')
    pins = {
        0xc750: ('mov', 'w1, #0x209'),
        0xc754: ('movk', 'w1, #0x200, lsl #16'),
        0xc758: ('mov', 'x0, #0'),
        0xc75c: ('bl', '#0x140009370'),
        0x99c4: ('mov', 'w8, #0x209'),
        0x99c8: ('movk', 'w8, #0x200, lsl #16'),
        0x99cc: ('str', 'w8, [x2]'),
        0x99d0: ('mov', 'x8, #1'),
        0x99d4: ('str', 'w8, [x2, #4]'),
        0x99dc: ('str', 'xzr, [x2, #8]'),
        0xc878: ('ldr', 'x8, [sp, #0x88]'),
        0xc87c: ('cmp', 'x8, #1'),
        0xc880: ('b.ne', '#0x14000c8e8'),
        0xc8d4: ('ldr', 'w8, [sp, #0x90]'),
        0xc8d8: ('ldr', 'w9, [sp, #0x98]'),
        0xc8dc: ('str', 'w8, [x21]'),
        0xc8e0: ('str', 'w9, [x22]'),
        0x70b8: ('bl', '#0x14000c568'),
        0x70d0: ('ldr', 'w8, [x29, #0x14]'),
        0x70d8: ('str', 'x8, [x11, #0x5a0]'),
        0x70dc: ('ldr', 'w9, [x29, #0x18]'),
        0x70e4: ('str', 'x9, [x12, #0x598]'),
        0x62a4: ('cbnz', 'w9, #0x14000634c'),
        0x62ac: ('ldr', 'x2, [x8, #0x598]'),
        0x62b0: ('ldr', 'w6, [x19, #0x14]'),
        0x62b8: ('ldr', 'x1, [x9, #0x5a0]'),
        0x62cc: ('bl', '#0x1400117b8'),
        0x117f0: ('tst', 'w25, #0xffffefff'),
        0x117fc: ('b.eq', '#0x1400119b8'),
        0x119b8: ('mov', 'x2, x20'),
        0x119bc: ('mov', 'x1, x21'),
        0x119c4: ('bl', '#0x1400115f0'),
        0x1163c: ('mov', 'w5, #0x25'),
        0x116a0: ('ldr', 'w13, [sp, #0x50]'),
        0x116a4: ('str', 'x13, [x20]'),
    }
    for at, expected in pins.items():
        assert instructions[at] == expected, (hex(at), instructions[at])
    table = struct.unpack('<11i', image.read(0x9ac4, 44))
    assert 0x9750 + table[8]*4 == 0x99c4
    # Read named imports, rather than assigning names from disassembly alone.
    pe = struct.unpack_from('<I', image.data, 0x3c)[0]
    imports = struct.unpack_from('<I', image.data, pe+24+120)[0]
    names = {}
    for at in range(imports, imports+1000, 20):
        original, _, _, _, iat = struct.unpack('<5I', image.read(at, 20))
        if not iat:
            break
        for j in range(1000):
            entry = struct.unpack('<Q', image.read(original+8*j, 8))[0]
            if not entry:
                break
            if entry >> 63:
                continue
            name = bytearray()
            while (byte := image.read(entry+2+len(name), 1)) != b'\0':
                name += byte
            names[iat+8*j] = name.decode()
    assert names[0x1d0f0] == 'MmAllocatePagesForMdlEx'
    assert names[0x1d138] == 'MmMapLockedPagesSpecifyCache'
    assert names[0x1d140] == 'MmGetPhysicalMemoryRanges'
    primary = HERE / 'upstream/scm_sip_interface.h'
    assert sha(primary) == 'ace9bf9b6f2adbe8657d380a87f0504a72705060ce0b3e90044b43e1d30f6ca8'
    shutil.copy2(primary, out / primary.name)
    report = dict(vendor_sha256=sha(vendor), reader_sha256=sha(helper),
                  pinned_instructions=len(pins), function_ranges=len(ranges),
                  query_command='0x02000209', query_arginfo=1, query_spare=0,
                  vendor_response_completed_status=1,
                  vendor_response_start_offset=8, vendor_response_end_offset=16,
                  dynamic_allocator_uses_queried_bounds=True,
                  queried_bounds_truncated_to_32_bits_by_vendor=True,
                  physical_allocator='MmAllocatePagesForMdlEx', allocation_flags='0x25',
                  alignment_zero_or_4096_uses_direct_bounded_allocator=True,
                  actual_device_bounds_observed=False,
                  actual_windows_execution_observed=False,
                  linux_raw_result_register_layout_verified=False,
                  encoded_status_meaning_identified=False,
                  acceptable_physical_memory_established=False)
    (out / 'functions.txt').write_text('\n'.join(listing)+'\n')
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    shutil.copy2(__file__, out / Path(__file__).name)
    hashes = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2)+'\n')
    assert all(sha(out/name) == digest for name, digest in hashes.items())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
