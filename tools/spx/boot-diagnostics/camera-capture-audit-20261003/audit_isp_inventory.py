#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Static SQ2 ISP inventory for receiver-contract review; no hardware access.

Decode PE exception-covered functions. Only track simple address construction
within basic blocks, and preserve unresolved calls and opaque words.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG

REPO = Path(__file__).resolve().parents[4]
VENDOR = Path('/home/dvitali/Documents/drivers/FileRepository/'
              'qccamisp8180.inf_arm64_aeaf635adedd0c46')
EXPECTED = {
    'qccamisp8180.sys': '39d8d130d03e703138be4f05dbd19d90a709eb961cc6c65cccdfac1dfd37471f',
    'qccamisp8180.inf': '5ba8efe39de8812c604298604e5f5fc5f1c8d6b781d187f95705742aa6c56449',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = Path(sys.argv[1])
    out.mkdir(mode=0o700)
    paths = {name: VENDOR / name for name in EXPECTED}
    for name in ('camss.c', 'camss-csid-gen2.c', 'camss-csid.c',
                 'camss-vfe-17x.c', 'camss-vfe.c'):
        paths[name] = REPO / 'drivers/media/platform/qcom/camss' / name
    paths['audit_isp_inventory.py'] = Path(__file__).resolve()
    inputs = {}
    for name, path in paths.items():
        digest = sha(path)
        if name in EXPECTED:
            assert digest == EXPECTED[name], name
        inputs[name] = dict(path=str(path), sha256=digest)
        shutil.copyfile(path, out / name)
        assert sha(out / name) == digest
    data = (out / 'qccamisp8180.sys').read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[:2] == b'MZ' and data[pe:pe+4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
    count = struct.unpack_from('<H', data, pe+6)[0]
    optional = struct.unpack_from('<H', data, pe+20)[0]
    base = struct.unpack_from('<Q', data, pe+48)[0]
    sections = []
    for i in range(count):
        at = pe+24+optional+i*40
        vsize, rva, size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append(dict(name=data[at:at+8].split(b'\0')[0].decode(),
                             rva=rva, vsize=vsize, raw=raw, size=size,
                             flags=struct.unpack_from('<I', data, at+36)[0]))

    def offset(rva, size=1):
        found = [s for s in sections if s['rva'] <= rva and
                 rva+size <= s['rva']+s['size']]
        assert len(found) == 1, (hex(rva), size)
        return found[0]['raw']+rva-found[0]['rva']

    imports = json.loads(subprocess.check_output(
        ['rabin2', '-ij', str(out / 'qccamisp8180.sys')], text=True, timeout=30))
    iat = {i['plt']: i['name'] for i in imports['imports']}
    strings = {}
    for match in re.finditer(rb'[\x09\x0a\x0d\x20-\x7e]{5,}\x00', data):
        section = next((s for s in sections if s['raw'] <= match.start() <
                        s['raw']+s['size']), None)
        if section:
            strings[base+section['rva']+match.start()-section['raw']] = (
                match.group()[:-1].decode())
    pdata = next(s for s in sections if s['name'] == '.pdata')
    assert pdata['vsize'] % 8 == 0
    functions = []
    for i in range(pdata['vsize']//8):
        start, unwind = struct.unpack_from('<II', data, pdata['raw']+i*8)
        flag = unwind & 3
        assert flag in (0, 1, 2)
        header = unwind if flag else struct.unpack_from(
            '<I', data, offset(unwind, 4))[0]
        length = (((header >> 2) & 0x7ff) if flag else
                  (header & 0x3ffff))*4
        assert start % 4 == 0 and length > 0
        offset(start, length)
        assert any(s['flags'] & 0x20000000 and s['rva'] <= start and
                   start+length <= s['rva']+s['vsize'] for s in sections)
        functions.append(dict(start=base+start, end=base+start+length,
                              unwind_flag=flag, calls=[], references=[]))
    starts = {f['start'] for f in functions}
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail, md.skipdata = True, True
    listing, opaque = [], []
    for function in functions:
        start, end = function['start'], function['end']
        raw = offset(start-base, end-start)
        instructions = list(md.disasm(data[raw:raw+end-start], start))
        assert sum(i.size for i in instructions) == end-start
        assert all(i.size == 4 for i in instructions)
        by_address = {i.address: i for i in instructions}
        reachable, pending = set(), [start]
        while pending:
            address = pending.pop()
            if address in reachable or address not in by_address:
                continue
            reachable.add(address)
            instruction = by_address[address]
            if not instruction.id or instruction.mnemonic in ('ret', 'br'):
                continue
            if instruction.mnemonic == 'b':
                pending.append(instruction.operands[0].imm)
            else:
                pending.append(address+4)
                if (instruction.mnemonic.startswith('b.') or
                        instruction.mnemonic in ('cbz', 'cbnz', 'tbz', 'tbnz')):
                    pending.append(instruction.operands[-1].imm)
        function['cfg_reachable_instruction_count'] = len(reachable)
        known = {}
        listing.append(f'\nFunction {start:#x}..{end:#x}')
        for instruction in instructions:
            suffix = []
            if not instruction.id:
                opaque.append(dict(function=start, at=instruction.address,
                                   bytes=instruction.bytes.hex(),
                                   cfg_reachable=instruction.address in reachable))
                known.clear()
                suffix.append('opaque word')
            elif instruction.address not in reachable:
                known.clear()
                suffix.append('not reached by bounded CFG')
            else:
                ops, before = instruction.operands, dict(known)
                _, writes = instruction.regs_access()
                for reg in writes:
                    known.pop(reg, None)
                mnemonic = instruction.mnemonic
                if mnemonic in ('adrp', 'adr'):
                    known[ops[0].reg] = ops[1].imm
                elif (mnemonic == 'add' and len(ops) == 3 and
                      ops[1].type == ARM64_OP_REG and
                      ops[2].type == ARM64_OP_IMM and
                      isinstance(before.get(ops[1].reg), int)):
                    known[ops[0].reg] = (before[ops[1].reg]+
                                       (ops[2].imm << ops[2].shift.value))
                elif (mnemonic == 'ldr' and len(ops) == 2 and
                      ops[1].type == ARM64_OP_MEM and not ops[1].mem.index and
                      isinstance(before.get(ops[1].mem.base), int)):
                    address = before[ops[1].mem.base]+ops[1].mem.disp
                    if address in iat:
                        known[ops[0].reg] = ('import', iat[address], address)
                if mnemonic in ('add', 'adr'):
                    value = known.get(ops[0].reg)
                    if isinstance(value, int) and (value in strings or value in starts):
                        reference = dict(at=instruction.address, target=value,
                                         string=strings.get(value),
                                         function=value in starts)
                        function['references'].append(reference)
                        suffix.append((strings.get(value) or f'function {value:#x}')
                                      .replace('\n', r'\n').replace('\r', r'\r'))
                if mnemonic == 'bl' and ops[0].type == ARM64_OP_IMM:
                    function['calls'].append(dict(at=instruction.address,
                        kind='direct', target=ops[0].imm,
                        within_pdata=ops[0].imm in starts))
                elif mnemonic == 'blr':
                    call = dict(at=instruction.address, kind='indirect',
                                operand=instruction.op_str)
                    value = before.get(ops[0].reg)
                    if isinstance(value, tuple):
                        call.update(import_name=value[1], iat=value[2])
                        suffix.append(value[1])
                    function['calls'].append(call)
                if mnemonic in ('bl', 'blr'):
                    known = {k: v for k, v in known.items() if md.reg_name(k) in
                             ('x19', 'x20', 'x21', 'x22', 'x23', 'x24',
                              'x25', 'x26', 'x27', 'x28')}
                elif (mnemonic in ('b', 'cbz', 'cbnz', 'tbz', 'tbnz', 'br', 'ret')
                      or mnemonic.startswith('b.')):
                    known.clear()
            listing.append(f'{instruction.address:#x}: {instruction.mnemonic} '
                           f'{instruction.op_str}'+
                           (' ; '+' | '.join(suffix) if suffix else ''))
    result = dict(inputs=inputs, image_base=base, sections=sections,
                  exception_record_count=len(functions), functions=functions,
                  opaque_words=opaque, strings={hex(k): v for k, v in strings.items()},
                  hardware_operations=0,
                  limits=['Leaf functions may lack exception records.',
                          'Only simple within-block addresses are tracked.',
                          'Unresolved indirect branches stop bounded CFG paths.',
                          'Strings and calls do not prove runtime revisions or rail ownership.'])
    (out / 'imports.json').write_text(json.dumps(imports, indent=2)+'\n')
    (out / 'isp-functions.txt').write_text('\n'.join(listing)+'\n')
    (out / 'isp-inventory.json').write_text(json.dumps(result, indent=2)+'\n')
    manifest = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(manifest, indent=2)+'\n')
    assert all(sha(out / name) == digest for name, digest in manifest.items())
    print(json.dumps(dict(output=str(out), functions=len(functions),
                         opaque_words=len(opaque),
                         manifest_sha256=sha(out / 'sha256.json'))))


if __name__ == '__main__':
    main()
