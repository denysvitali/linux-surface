#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the retained SQ2 PEP's STND camera loader as offline ARM64 byte data.

No vendor execution, ACPI evaluation, device open or hardware access. The static
loader contract does not establish actual Windows execution or analog wiring.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method_list(source):
    root = re.search(r'Name \(STNX, Package \((0x[0-9A-F]+)\)\s*\{(.*?)\}\)',
                     source, re.S)
    assert root is not None
    fields = re.findall(r'"([A-Z0-9]{4})"', root.group(2))
    assert len(fields) == int(root.group(1), 16) == 31
    returned = re.search(r'Method \(STND, 0, NotSerialized\)\s*\{\s*Return \(STNX\)', source)
    assert returned is not None
    camera = {'C0MD': (5, 'CPC0'), 'C1MD': (6, 'CPC1'),
              'C2MD': (7, 'CPC2'), 'CPMX': (27, 'CPXC')}
    records = []
    for index, entry in enumerate(fields):
        # Matches the four LDRB/shift/OR operations and little-endian STR W10.
        word = int.from_bytes(entry.encode('ascii'), 'big')
        request_name = word.to_bytes(4, 'little').decode('ascii')
        declaration = re.search(r'Method \('+request_name+
                                r', 0, NotSerialized\)\s*\{\s*Return \(([^)]+)\)', source)
        record = dict(index=index, entry=entry, assembled_u32=word,
                      request_name=request_name,
                      simple_return=declaration.group(1) if declaration else None,
                      method_line=source.count('\n', 0, declaration.start())+1 if declaration else None)
        records.append(record)
    for name, (index, package) in camera.items():
        assert records[index]['request_name'] == name
        assert records[index]['simple_return'] == package
    return dict(count=len(fields), stnx_line=source.count('\n', 0, root.start())+1,
                stnd_line=source.count('\n', 0, returned.start())+1,
                entries=records, camera_exports=[records[index] for index, _ in camera.values()])


class Image:
    def __init__(self, data):
        self.data = data
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        assert data[:2] == b'MZ' and data[pe:pe+4] == b'PE\0\0'
        assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
        self.base = struct.unpack_from('<Q', data, pe+48)[0]
        assert self.base == 0x140000000
        count = struct.unpack_from('<H', data, pe+6)[0]
        optional = struct.unpack_from('<H', data, pe+20)[0]
        self.sections = []
        for i in range(count):
            at = pe+24+optional+40*i
            vsize, rva, size, raw = struct.unpack_from('<IIII', data, at+8)
            self.sections.append(dict(name=data[at:at+8].split(b'\0')[0].decode(),
                                      vsize=vsize, rva=rva, size=size, raw=raw))
        pdata = next(s for s in self.sections if s['name'] == '.pdata')
        assert pdata['vsize'] % 8 == 0
        self.functions = {}
        self.exception_count = pdata['vsize'] // 8
        for at in range(pdata['raw'], pdata['raw']+pdata['vsize'], 8):
            start, unwind = struct.unpack_from('<II', data, at)
            assert (unwind & 3) in (0, 1, 2)
            length = (((unwind >> 2) & 0x7ff)*4 if unwind & 3 else
                      (struct.unpack('<I', self.read(unwind, 4))[0] & 0x3ffff)*4)
            assert length > 0 and start not in self.functions
            self.functions[start] = start+length

    def read(self, rva, size):
        found = [s for s in self.sections if s['rva'] <= rva and
                 rva+size <= s['rva']+s['size']]
        assert len(found) == 1, (hex(rva), size)
        at = found[0]['raw']+rva-found[0]['rva']
        return self.data[at:at+size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--references', type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(mode=0o700)
    vendor = Path('/home/dvitali/Documents/drivers/FileRepository/'
                  'surfaceprox_pep.inf_arm64_6f779ee9c199c1af')
    paths = {
        'qcpep8180.sys': vendor / 'qcpep8180.sys',
        'surfaceprox_pep.inf': vendor / 'surfaceprox_pep.inf',
        'dsdt.dsl': Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl'),
        'wdffuncenum-1.15.h': args.references / 'wdffuncenum-1.15.h',
        'wdffuncenum-1.33.h': args.references / 'wdffuncenum.h',
        'reference.json': args.references / 'reference.json',
        'reference-commit.json': args.references / 'commit.json',
        'prior-receiver-power.json': Path('/var/tmp/spx-receiver-power-20261003-v1/receiver-power.json'),
        'prior-receiver-SHA256SUMS': Path('/var/tmp/spx-receiver-power-20261003-v1/SHA256SUMS'),
        'audit_pep_loader.py': Path(__file__).resolve(),
    }
    expected = {
        'qcpep8180.sys': '751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde',
        'surfaceprox_pep.inf': '291a4b2ebcd4ee677e6604a3a98d9300fa29f13f8e3d843683054fef1f0a44ef',
        'dsdt.dsl': 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8',
        'wdffuncenum-1.15.h': '2042f92c5a6114d9a2d5443a2509e23e1ef0caebc52f5eacad37e25e1a0d4be7',
        'wdffuncenum-1.33.h': '9492200adbf23b3356b0771e76872590c3e35968e5d395aa62c198faa59de166',
        'prior-receiver-SHA256SUMS': '7ca2b4bc51b8f01b2715a0732c139e109b5999a81cc5eff735a56e4b36518943',
    }
    inputs = {}
    for name, path in paths.items():
        digest = sha(path)
        if name in expected:
            assert digest == expected[name], name
        inputs[name] = dict(path=str(path), sha256=digest)
        shutil.copyfile(path, out / name)
        assert sha(out / name) == digest
    previous_manifest = dict(line.split('  ', 1)[::-1] for line in
                             (out / 'prior-receiver-SHA256SUMS').read_text().splitlines())
    assert sha(out / 'prior-receiver-power.json') == previous_manifest['receiver-power.json']
    previous = json.loads((out / 'prior-receiver-power.json').read_text())
    assert previous['inputs']['dsdt.dsl']['sha256'] == inputs['dsdt.dsl']['sha256']
    exports = method_list((out / 'dsdt.dsl').read_text())
    reference = json.loads((out / 'reference.json').read_text())
    assert reference['commit'] == 'b6191d9543441329154da32f7ab9bdd97228dd3c'
    assert reference['sha256'] == inputs['wdffuncenum-1.33.h']['sha256']
    image = Image((out / 'qcpep8180.sys').read_bytes())
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    decoded, reached, listing, selected, opaque = {}, set(), [], [], []
    ranges = [(0x44d8, 0x455c), (0x390f8, 0x3914c), (0x391b0, 0x39204),
              (0x3fa38, 0x3fd18), (0x56190, 0x56428),
              (0x1e9250, 0x1e962c), (0x1e9f30, 0x1ea364),
              (0x1ead90, 0x1eb8c8), (0x1eb8d0, 0x1ebb6c),
              (0x1fa4d0, 0x1fac40), (0x209a90, 0x209ba0), (0x20c2e0, 0x20ccec)]
    for start, end in ranges:
        assert image.functions[start] == end
        raw = image.read(start, end-start)
        insns = list(md.disasm(raw, image.base+start))
        assert sum(i.size for i in insns) == len(raw) and all(i.size == 4 for i in insns)
        by_address = {i.address-image.base: i for i in insns}
        pending, visited = [start], set()
        while pending:
            at = pending.pop()
            if at in visited or at not in by_address:
                continue
            visited.add(at)
            insn = by_address[at]
            assert insn.id, (hex(at), 'opaque reached by CFG')
            if insn.mnemonic in ('ret', 'br', 'brk'):
                continue
            if insn.mnemonic == 'b':
                pending.append(insn.operands[0].imm-image.base)
            else:
                pending.append(at+4)
                if insn.mnemonic.startswith('b.') or insn.mnemonic in ('cbz','cbnz','tbz','tbnz'):
                    pending.append(insn.operands[-1].imm-image.base)
        reached.update(visited)
        selected.append(dict(start_rva=start, end_rva=end, reachable=len(visited),
                             bytes_sha256=hashlib.sha256(raw).hexdigest()))
        listing.append(f'\nFunction {image.base+start:#x}..{image.base+end:#x}')
        for insn in insns:
            at = insn.address-image.base
            decoded[at] = (insn.mnemonic, insn.op_str)
            if not insn.id:
                opaque.append(dict(rva=at, bytes=insn.bytes.hex(), reachable=at in visited))
            suffix = '' if at in visited else ' ; outside bounded CFG'
            listing.append(f'{insn.address:#x}: {insn.mnemonic} {insn.op_str}{suffix}')
    contract = {
        0x390f8: ('sub', 'sp, sp, #0x20'), 0x39118: ('mov', 'w9, #0'),
        0x39120: ('strb', 'w9, [x8]'), 0x39128: ('add', 'x8, x8, #1'),
        0x39134: ('sub', 'x8, x8, #1'), 0x3913c: ('b', '#0x14003910c'),
        0x391c0: ('ldr', 'x8, [x8, #0xe18]'),
        0x391c4: ('add', 'x8, x8, #0x150'), 0x391f0: ('blr', 'x8'),
        0x4500: ('ldr', 'x8, [x8, #0xe18]'),
        0x4504: ('add', 'x8, x8, #0x5d0'), 0x4548: ('blr', 'x8'),
        0x562bc: ('bl', '#0x14020c2e0'),
        0x20c6b8: ('ldr', 'w8, #0x14020cd00'),
        0x20c6c4: ('ldr', 'w3, [sp, #0x44]'),
        0x20c6c8: ('mov', 'w2, #0x20000'), 0x20c6d4: ('bl', '#0x140209a90'),
        0x20c708: ('bl', '#0x1401fa4d0'),
        0x20c808: ('ldr', 'w8, [sp, #0x1c]'),
        0x20c854: ('mul', 'x9, x9, x8'), 0x20c858: ('ldr', 'x8, [sp, #0x50]'),
        0x20c85c: ('add', 'x8, x8, x9'), 0x20c864: ('ldr', 'w3, [x8]'),
        0x20c874: ('bl', '#0x140209a90'),
        0x20c944: ('ldr', 'w8, [x11]'), 0x20c948: ('str', 'w8, [x9]'),
        0x20cb5c: ('ldr', 'x0, [x8]'), 0x20cb68: ('blr', 'x8'),
        0x20cbbc: ('bl', '#0x14003fa38'), 0x3fbb8: ('bl', '#0x1401eb8d0'),
        0x1eb9a4: ('mov', 'x2, #7'), 0x1eb9a8: ('adrp', 'x8, #0x140233000'),
        0x1eb9ac: ('add', 'x1, x8, #0x7c8'),
        0x1eb9b4: ('bl', '#0x140012028'), 0x1eba38: ('bl', '#0x140011ad8'),
        0x1eba94: ('bl', '#0x1401e9250'),
        0x1e94b8: ('bl', '#0x1401e9630'), 0x1e9518: ('bl', '#0x1401e9f30'),
        0x1ea344: ('bl', '#0x1401ead90'),
        0x1eadf4: ('add', 'x8, x8, #0x10'), 0x1eadf8: ('ldr', 'w8, [x8]'),
        0x1eadfc: ('str', 'w8, [sp, #0x40]'),
        0x1eb004: ('cmp', 'w8, #2'), 0x1eb0ac: ('bl', '#0x1401f4358'),
        0x1eb124: ('cmp', 'w8, #5'), 0x1eb160: ('bl', '#0x1401f59f0'),
        0x1eb28c: ('cmp', 'w8, #0xa'), 0x1eb35c: ('bl', '#0x1401f2518'),
        0x1eb36c: ('cmp', 'w8, #0xf'), 0x1eb39c: ('bl', '#0x1401f2d80'),
        0x1fa8e0: ('add', 'x8, x8, #4'), 0x1fa8e4: ('ldrb', 'w8, [x8]'),
        0x1fa8ec: ('lsl', 'w9, w8, #0x18'),
        0x1fa8f4: ('add', 'x8, x8, #5'), 0x1fa8f8: ('ldrb', 'w8, [x8]'),
        0x1fa900: ('lsl', 'w8, w8, #0x10'), 0x1fa904: ('orr', 'w9, w9, w8'),
        0x1fa90c: ('add', 'x8, x8, #6'), 0x1fa910: ('ldrb', 'w8, [x8]'),
        0x1fa918: ('lsl', 'w8, w8, #8'), 0x1fa91c: ('orr', 'w9, w9, w8'),
        0x1fa924: ('add', 'x8, x8, #7'), 0x1fa928: ('ldrb', 'w8, [x8]'),
        0x1fa930: ('orr', 'w10, w9, w8'), 0x1fa950: ('str', 'w10, [x8]'),
        0x209aac: ('str', 'w3, [sp, #0xc]'),
        0x209af0: ('mov', 'x1, #0x104'), 0x209af4: ('add', 'x0, sp, #0x68'),
        0x209af8: ('bl', '#0x1400390f8'), 0x209afc: ('ldr', 'w8, [sp, #0xc]'),
        0x209b00: ('str', 'w8, [sp, #0x6c]'),
        0x209b04: ('ldr', 'w8, #0x140209b98'), 0x209b08: ('str', 'w8, [sp, #0x68]'),
        0x209b0c: ('mov', 'w2, #0x104'), 0x209b68: ('ldr', 'w2, #0x140209b9c'),
        0x209b74: ('bl', '#0x1400044d8'),
    }
    for at, expected_instruction in contract.items():
        assert at in reached and decoded[at] == expected_instruction, (hex(at), decoded[at])
    assert image.read(0x20cd00, 4) == b'STND'
    assert image.read(0x209b98, 4) == b'AeiA'
    assert struct.unpack('<I', image.read(0x209b9c, 4))[0] == 0x32c018
    assert image.read(0x2337c8, 7) == b'DEVICE\0'
    wdf = {}
    for version in ('1.15', '1.33'):
        header = (out / f'wdffuncenum-{version}.h').read_text()
        values = {name: int(value) for name, value in re.findall(r'(Wdf\w+TableIndex)\s*=\s*(\d+)', header)}
        assert values['WdfDeviceGetIoTargetTableIndex']*8 == 0x150
        assert values['WdfIoTargetSendIoctlSynchronouslyTableIndex']*8 == 0x5d0
        wdf[version] = {name: values[name] for name in
                        ('WdfDeviceGetIoTargetTableIndex', 'WdfIoTargetSendIoctlSynchronouslyTableIndex')}
    tags = []
    for table in (0x1bd820, 0x1c0500, 0x1c0920):
        strings = []
        for index in range(16):
            pointer = struct.unpack('<Q', image.read(table+8*index, 8))[0]
            strings.append(image.read(pointer-image.base, 64).split(b'\0')[0].decode())
        assert [strings[i] for i in (2, 5, 10, 15)] == ['CLOCK', 'PMICVREGVOTE', 'NPARESOURCE', 'FOOTSWITCH']
        tags.append(dict(table_rva=table, strings=strings))
    assert tags[0]['strings'] == tags[1]['strings'] == tags[2]['strings']
    result = dict(inputs=inputs, method_list=exports, selected_ranges=selected,
                  exception_records=image.exception_count, instruction_checks=len(contract),
                  opaque_words=opaque, wdf_reference_indices=wdf, resource_tag_tables=tags,
                  request_shape=dict(size=260, signature_ascii='AeiA', control_code=0x32c018,
                                     method_field_offset=4, path_bytes=256),
                  static_camera_loader_path_established=True, actual_windows_execution_observed=False,
                  hardware_operations=0, analog_supply_mapping_established=False,
                  prior_literal_packages_verified=previous['total_literal_packages_verified'],
                  limits=['Bounded CFG does not resolve imported/WDF bodies or all indirect calls.',
                          'WDF indices agree in pinned 1.15/1.33 headers; live Windows binding unobserved.',
                          'EX request identification uses documented buffer shape; historical acpiioct.h unavailable.',
                          'Selected parser/action branches are not a complete PEP or power graph.',
                          'Tag-table indices and builder dispatch agree; builder internals remain untraced.',
                          'Static loader path does not prove requests succeeded in Windows.',
                          'No dedicated analog wiring, provider or Linux capture acceptance follows.'])
    (out / 'pep-loader.json').write_text(json.dumps(result, indent=2)+'\n')
    (out / 'pep-selected-code.txt').write_text('\n'.join(listing)+'\n')
    manifest = ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(manifest)
    print(json.dumps(dict(methods=exports['count'], camera_exports=len(exports['camera_exports']),
                          instruction_checks=len(contract), ranges=len(selected),
                          opaque_words=len(opaque), manifest_sha256=sha(out / 'SHA256SUMS'))))


if __name__ == '__main__':
    main()
