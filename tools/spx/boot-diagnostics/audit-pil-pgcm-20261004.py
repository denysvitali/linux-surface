#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pin retained PIL registry, free-list and physical-memory-add paths offline."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g


def normalize(value):
    value = value.split('//', 1)[0]
    value = re.sub(r'-?0x[0-9a-f]+|-?\b[0-9]+\b',
                   lambda m: str(int(m[0], 16 if '0x' in m[0] else 10)), value)
    return re.sub(r'[\s#]', '', value)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    a = g.load()
    assert a['state'].startswith('BD terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['returned_boot_id']
    assert os.uname().release == '6.18.3-1-surface+'
    assert not g.recovery(a).get('next_entry', '')
    out = g.X / 'offline-pil-pgcm'
    out.mkdir(mode=0o700)
    vendor = Path('/home/dvitali/Documents/drivers/FileRepository/qcpil8180.inf_arm64_33f5ea4e4b666c6f')
    refs = Path('/var/tmp/spx-pep-primary-20261003')
    inputs = {
        'qcpil8180.sys': (vendor / 'qcpil8180.sys', '0821cba482219b0aac2c0c47c4149d06a385013a4ebfa30211ed653f5b8ea242'),
        'qcpil8180.inf': (vendor / 'qcpil8180.inf', 'c9ad974f5be305019583495d1232c9a6dbb1a1862f4197127fde6858119b9dea'),
        'pe_reader.py': (HERE / 'camera-capture-audit-20261003/audit_pep_loader.py', '68eb3cfe6105ac1e1cd1bae17ca6dc7f4274e497e9d9e85b8fc92847bdfbd41b'),
        'wdffuncenum.h': (refs / 'wdffuncenum.h', '9492200adbf23b3356b0771e76872590c3e35968e5d395aa62c198faa59de166'),
        'wdffuncenum-1.15.h': (refs / 'wdffuncenum-1.15.h', '2042f92c5a6114d9a2d5443a2509e23e1ef0caebc52f5eacad37e25e1a0d4be7'),
    }
    for name, (path, expected) in inputs.items():
        assert g.sha(path) == expected, name
        shutil.copy2(path, out / name)
        assert g.sha(out / name) == expected
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(refs / 'reference.json', out / 'wdf-reference.json')
    ref = json.loads((out / 'wdf-reference.json').read_text())
    assert ref['commit'] == 'b6191d9543441329154da32f7ab9bdd97228dd3c'
    owners = g.X / 'offline-pil-pool-owners'
    assert g.sha(owners / 'sha256.json') == '0502ec49050cdfa9aa3e170f34d1a2f8152aaacb70848a3b72243eb2efb97776'
    assert g.files(owners) == json.loads((owners / 'sha256.json').read_text()) | {'sha256.json': g.sha(owners / 'sha256.json')}
    shutil.copy2(owners / 'report.json', out / 'owner-report.json')
    spec = importlib.util.spec_from_file_location('pgcm_pe', out / 'pe_reader.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    image = reader.Image((out / 'qcpil8180.sys').read_bytes())
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    starts = (0x6a18, 0x6ad0, 0x6c00, 0x6df0, 0x7090, 0x7600,
              0x125a0, 0x12908, 0x12bf8, 0x115f0, 0x117b8)
    decoded, reached, gnu, functions, listing = {}, set(), {}, [], []
    for start in starts:
        end = image.functions[start]
        raw = image.read(start, end-start)
        binary = out / f'pil-{start:x}-{end:x}.bin'
        binary.write_bytes(raw)
        insns = list(md.disasm(raw, image.base+start))
        assert sum(x.size for x in insns) == len(raw)
        by_address = {x.address-image.base: x for x in insns}
        pending, visited = [start], set()
        while pending:
            at = pending.pop()
            if at in visited or at not in by_address:
                continue
            visited.add(at)
            insn = by_address[at]
            assert insn.id, (hex(at), 'undecoded reachable instruction')
            if insn.mnemonic in ('ret', 'br', 'brk'):
                continue
            if insn.mnemonic == 'b':
                pending.append(insn.operands[0].imm-image.base)
            else:
                pending.append(at+4)
                if insn.mnemonic.startswith('b.') or insn.mnemonic in ('cbz', 'cbnz', 'tbz', 'tbnz'):
                    pending.append(insn.operands[-1].imm-image.base)
        reached.update(visited)
        functions.append(dict(start=hex(start), end=hex(end), bytes_sha256=hashlib.sha256(raw).hexdigest(), reachable=len(visited)))
        listing.append(f'.pdata {start:x}..{end:x}')
        for x in insns:
            at = x.address-image.base
            decoded[at] = (x.mnemonic, x.op_str)
            listing.append(f'{at:x}: {x.mnemonic} {x.op_str}' + ('' if at in visited else ' ; outside bounded CFG'))
        dump = subprocess.check_output(['objdump', '-D', '-b', 'binary', '-m', 'aarch64',
            '--adjust-vma=' + hex(image.base+start), str(binary)], text=True)
        (out / (binary.name + '.objdump')).write_text(dump)
        for line in dump.splitlines():
            match = re.match(r'\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(\S+)\s*(.*)', line)
            if match:
                gnu[int(match[1], 16)-image.base] = (match[2], match[3])
    (out / 'disassembly.txt').write_text('\n'.join(listing) + '\n')
    pins = {
        # PGCM and BaseAddress/Size comparisons, zero-extended registry DWORDs.
        0x12678: ('add', 'x19, x8, #0x4f0'), 0x1267c: ('add', 'x1, x19, #0x50'),
        0x12688: ('ldr', 'x8, [x8, #0xe8]'), 0x1268c: ('blr', 'x8'),
        0x1269c: ('cbnz', 'w0, #0x140012734'), 0x126a0: ('add', 'x1, x19, #0x200'),
        0x126b0: ('ldr', 'w0, [x21]'), 0x126b8: ('add', 'x19, x8, #0x560'),
        0x126bc: ('str', 'x0, [x19]'), 0x126c8: ('mov', 'x1, x19'),
        0x126e8: ('ldr', 'w1, [x21]'), 0x126ec: ('str', 'x1, [x19, #8]'),
        0x12700: ('cbz', 'x0, #0x14001271c'), 0x12704: ('cbz', 'x1, #0x14001271c'),
        0x12708: ('add', 'x2, x20, #0x4c0'), 0x1270c: ('bl', '#0x140007600'),
        0x12710: ('ldr', 'x1, [x19, #8]'), 0x12714: ('ldr', 'x0, [x19]'),
        0x12718: ('bl', '#0x140006a18'),
        # Registry descriptor rows: PGCM/BaseAddress then PGCM/Size.
        0x129c0: ('add', 'x11, x8, #0x490'), 0x12a8c: ('add', 'x10, x29, #0x108'),
        0x12a90: ('ldp', 'x8, x9, [x11, #0xb0]'), 0x12a9c: ('add', 'x8, x11, #0x260'),
        0x12aa8: ('str', 'w14, [x29, #0x128]'), 0x12aac: ('str', 'xzr, [x29, #0x130]'),
        0x12ab4: ('ldp', 'x8, x9, [x11, #0xb0]'), 0x12ac0: ('ldp', 'x8, x9, [x11, #0x60]'),
        0x12acc: ('str', 'xzr, [x29, #0x160]'),
        0x12d3c: ('ldr', 'x19, [x8, #0x728]'), 0x12e60: ('ldr', 'x19, [x8, #0x780]'),
        0x12e74: ('add', 'x3, x26, #4'), 0x12ef4: ('ldr', 'x9, [x20, #0x28]'),
        0x12ef8: ('cbz', 'x9, #0x140012f08'), 0x12f08: ('add', 'x5, x26, #4'),
        0x12f14: ('ldr', 'x2, [x20, #8]'), 0x12f18: ('ldr', 'x1, [x20]'),
        0x12f20: ('bl', '#0x1400125a0'),
        # Free-list nodes hold next/base/length. Same PGCM values seed both lists.
        0x6a30: ('stp', 'x0, x1, [sp]'), 0x6a5c: ('mov', 'x1, #0x18'),
        0x6a90: ('ldr', 'x8, [x8, #0x98]'), 0x6a94: ('add', 'x2, sp, #0x10'),
        0x6a98: ('mov', 'x1, #0x10'), 0x6a9c: ('add', 'x0, x19, #8'),
        0x6aa0: ('blr', 'x8'), 0x6aac: ('ldr', 'x8, [x9, #0x510]'),
        0x6ab0: ('str', 'x8, [x19]'), 0x6ab4: ('str', 'x19, [x9, #0x510]'),
        0x7688: ('add', 'x0, x19, #8'), 0x7694: ('ldr', 'x8, [x20]'),
        0x769c: ('str', 'x19, [x20]'),
        # Allocate a requested firmware span, enqueue prefix/suffix leftovers.
        0x6b08: ('ldr', 'w9, [x20, #0x10]'), 0x6b0c: ('ldr', 'w14, [x0, #0x10]'),
        0x6b18: ('ldr', 'w13, [x20, #8]'), 0x6b20: ('ldr', 'w9, [x0, #0x18]'),
        0x6b2c: ('ldr', 'w12, [x0, #0x14]'), 0x6b3c: ('and', 'w11, w10, w9'),
        0x6b68: ('str', 'w9, [x0, #0x18]'), 0x6b74: ('sub', 'w1, w9, w13'),
        0x6b7c: ('bl', '#0x140006a18'), 0x6b8c: ('add', 'x0, x9, #1'),
        0x6b90: ('sub', 'w1, w22, w21'), 0x6b94: ('bl', '#0x140006a18'),
        # Consume configured firmware requests before physical-memory addition.
        0x6e7c: ('ldr', 'x7, [x22, #0x500]'), 0x6e80: ('ldr', 'w8, [x23, #0x508]'),
        0x6e98: ('ldr', 'w14, [x10, #0x10]'), 0x6ea0: ('ldr', 'w13, [x10, #0x18]'),
        0x6f48: ('bl', '#0x140006ad0'), 0x6f7c: ('ldr', 'w8, [x19, #0x510]'),
        0x6f80: ('cbz', 'w8, #0x140006fe4'), 0x6fe4: ('bl', '#0x140006c00'),
        0x6c44: ('ldr', 'x20, [x23, #0x510]'), 0x6cb8: ('add', 'x0, x20, #8'),
        0x6cbc: ('add', 'x1, x20, #0x10'), 0x6cc4: ('ldr', 'x8, [x8, #0x60]'),
        0x6cc8: ('blr', 'x8'), 0x6cd0: ('tbz', 'w0, #0x1f, #0x140006d6c'),
        0x6d78: ('ldr', 'x9, [x20, #0x10]'), 0x6d98: ('b', '#0x140006c44'),
        0x12a78: ('ldp', 'x8, x9, [x11]'), 0x12a84: ('add', 'x8, x0, #0x510'),
        # The area query precedes free-list partitioning; later dynamic allocator.
        0x70b8: ('bl', '#0x14000c568'), 0x7168: ('bl', '#0x140004ce8'),
        0x716c: ('bl', '#0x140004a78'), 0x71cc: ('bl', '#0x140006df0'),
        0x11610: ('ldr', 'x8, [x8, #0xf0]'), 0x1163c: ('mov', 'w5, #0x25'),
        0x11804: ('ldr', 'x8, [x11, #0x140]'),
    }
    for at, expected in pins.items():
        assert at in reached and decoded[at] == expected, (hex(at), decoded.get(at))
        actual = gnu[at]
        assert actual[0] == expected[0] and normalize(actual[1]) == normalize(expected[1]), (hex(at), actual, expected)
    descriptors = {}
    for rva, expected in ((0x1d490, 'DoNotReturnMemoryToHLOS'), (0x1d4f0, 'Size'),
                          (0x1d540, 'PGCM'), (0x1d6f0, 'BaseAddress')):
        length, maximum, pointer = struct.unpack('<HH4xQ', image.read(rva, 16))
        assert length <= maximum
        name = image.read(pointer-image.base, length).decode('utf-16le')
        assert name == expected
        descriptors[hex(rva)] = dict(name=name, pointer_rva=hex(pointer-image.base), bytes=image.read(rva, 16).hex())
    pe = struct.unpack_from('<I', image.data, 0x3c)[0]
    imp = struct.unpack_from('<I', image.data, pe+24+120)[0]
    imports = {}
    for at in range(imp, imp+1000, 20):
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
            imports[iat+8*j] = name.decode()
    for at, expected in ((0x1d060, 'MmAddPhysicalMemory'), (0x1d098, 'memmove_s'),
                          (0x1d0e8, 'RtlCompareUnicodeString'), (0x1d0f0, 'MmAllocatePagesForMdlEx'),
                          (0x1d140, 'MmGetPhysicalMemoryRanges')):
        assert imports[at] == expected
    wdf = {}
    for filename in ('wdffuncenum.h', 'wdffuncenum-1.15.h'):
        values = dict((name, int(value)) for name, value in re.findall(
            r'(Wdf\w+TableIndex)\s*=\s*(\d+)', (out / filename).read_text()))
        for name, offset in (('WdfRegistryOpenKey', 0x728), ('WdfRegistryQueryULong', 0x780)):
            assert values[name + 'TableIndex']*8 == offset
            wdf[name] = dict(index=offset//8, offset=hex(offset))
    inf = (out / 'qcpil8180.inf').read_bytes().decode('utf-16')
    assert re.search(r'HKR,PGCM,BaseAddress,%REG_DWORD%,0x8BD80000', inf)
    assert re.search(r'HKR,PGCM,Size,%REG_DWORD%,0xE780000', inf)
    assert 'HKR,PilConfig,DoNotReturnMemoryToHLOS' not in inf
    # Every dataflow claim remains static: no retained vendor code is executed.
    report = dict(utc=datetime.now(timezone.utc).isoformat(), inputs={name: digest for name, (_, digest) in inputs.items()},
        functions=functions, pins=len(pins), gnu_operand_comparisons=len(pins),
        descriptors=descriptors, imports={hex(k): v for k, v in imports.items()}, wdf=wdf,
        pgcm=dict(base='0x8bd80000', size='0xe780000', end_exclusive='0x9a500000'),
        registry_dwords_seed_global_23560_and_23568=True,
        pgcm_seed_copied_into_global_23510_free_list=True,
        free_list_node_offsets=dict(next=0, base=8, length=16),
        firmware_requests_partition_pool_before_memory_add=True,
        do_not_return_memory_to_hlos_nonzero_skips_memory_add=True,
        unused_nodes_pass_by_address_to_mm_add_physical_memory=True,
        windows_runtime_execution_observed=False, complete_pgcm_owner_map_proven=False,
        linux_allocation_from_nomap_validated=False, compiled_candidate_changed=False,
        next_step='Correlate firmware request table and fixed DT regions, then review a bounded NOMAP reservation policy.',
        api_reference='https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddk/nf-ntddk-wdm-mmaddphysicalmemory')
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'pins.json').write_text(json.dumps({hex(k): v for k, v in pins.items()}, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    assert g.files(out) == json.loads((out / 'sha256.json').read_text()) | {'sha256.json': g.sha(out / 'sha256.json')}
    os.sync()
    print(json.dumps(dict(pins=len(pins), functions=len(functions), manifest_sha256=g.sha(out / 'sha256.json'))))


if __name__ == '__main__':
    main()
