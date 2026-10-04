#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Inventory retained ARM64 MIPI-CSI functions and static power call sites.

Uses PE exception records for function boundaries. Address tracking is bounded
to simple ADRP/ADD/LDR sequences, not a general symbolic executor. Never loads
the vendor code or accesses hardware.
"""
import hashlib
import importlib.util
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
              'qccammipicsi8180.inf_arm64_b579e0018fd8f1d6')
DSDT = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = Path(sys.argv[1])
    out.mkdir(mode=0o700)
    paths = {'qccammipicsi8180.sys': VENDOR / 'qccammipicsi8180.sys',
             'qccammipicsi8180.inf': VENDOR / 'qccammipicsi8180.inf',
             'dsdt.dsl': DSDT,
             'audit_mipi_power.py': Path(__file__).resolve(),
             'audit_firmware.py': REPO / 'tools/spx/boot-diagnostics/camera-power-20261003/audit_firmware.py'}
    expected = {'qccammipicsi8180.sys': '39e299af8ada6d80778f510c363085f49c5a06d94d418ce98ea87065c806a306',
                'qccammipicsi8180.inf': '821f1172fe7ab910e45bea489d059744bb17f4689f55612d520881fbd8a8e40e',
                'dsdt.dsl': 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'}
    inputs = {}
    for name, path in paths.items():
        if name in expected:
            assert sha(path) == expected[name], name
        inputs[name] = dict(path=str(path), sha256=sha(path))
        shutil.copyfile(path, out / name)
        assert sha(out / name) == inputs[name]['sha256']
    data = (out / 'qccammipicsi8180.sys').read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[:2] == b'MZ' and data[pe:pe+4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
    count, optional = struct.unpack_from('<H', data, pe+6)[0], struct.unpack_from('<H', data, pe+20)[0]
    base = struct.unpack_from('<Q', data, pe+48)[0]
    sections = []
    for i in range(count):
        at = pe+24+optional+i*40
        name = data[at:at+8].split(b'\0')[0].decode()
        vsize, rva, size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append(dict(name=name, rva=rva, vsize=vsize, raw=raw, size=size,
                             flags=struct.unpack_from('<I', data, at+36)[0]))

    def offset(rva, size=1):
        found = [s for s in sections if s['rva'] <= rva and rva+size <= s['rva']+s['size']]
        assert len(found) == 1, (rva, size)
        return found[0]['raw']+rva-found[0]['rva']

    imports = json.loads(subprocess.check_output(['rabin2', '-ij', str(out / 'qccammipicsi8180.sys')],
                                                text=True, timeout=30))
    iat = {i['plt']: i['name'] for i in imports['imports']}
    strings = {}
    for m in re.finditer(rb'[\x09\x0a\x0d\x20-\x7e]{5,}\x00', data):
        s = next((s for s in sections if s['raw'] <= m.start() < s['raw']+s['size']), None)
        if s:
            strings[base+s['rva']+m.start()-s['raw']] = m.group()[:-1].decode()
    pdata = next(s for s in sections if s['name'] == '.pdata')
    assert pdata['vsize'] % 8 == 0
    functions = []
    for i in range(pdata['vsize'] // 8):
        start, unwind = struct.unpack_from('<II', data, pdata['raw']+i*8)
        flag = unwind & 3
        assert flag in (0, 1, 2)
        if flag:
            length = ((unwind >> 2) & 0x7ff)*4
        else:
            header = struct.unpack_from('<I', data, offset(unwind, 4))[0]
            length = (header & 0x3ffff)*4
        assert start % 4 == 0 and length > 0
        offset(start, length)
        assert any(s['flags'] & 0x20000000 and s['rva'] <= start and
                   start+length <= s['rva']+s['vsize'] for s in sections)
        functions.append(dict(start=base+start, end=base+start+length,
                              unwind_flag=flag, unwind_data=unwind, calls=[], references=[]))
    starts = {f['start'] for f in functions}
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    listing, indirect_calls, undecoded = [], [], []
    for f in functions:
        raw = offset(f['start']-base, f['end']-f['start'])
        insns = list(md.disasm(data[raw:raw+f['end']-f['start']], f['start']))
        assert sum(i.size for i in insns) == f['end']-f['start']
        assert all(i.size == 4 for i in insns)
        by_address = {i.address: i for i in insns}
        reachable, pending = set(), [f['start']]
        while pending:
            address = pending.pop()
            if address in reachable or address not in by_address:
                continue
            reachable.add(address)
            i = by_address[address]
            if not i.id or i.mnemonic in ('ret', 'br'):
                continue
            if i.mnemonic == 'b':
                pending.append(i.operands[0].imm)
            else:
                pending.append(address+4)
                if i.mnemonic.startswith('b.') or i.mnemonic in ('cbz','cbnz','tbz','tbnz'):
                    pending.append(i.operands[-1].imm)
        f['cfg_reachable_instruction_count'] = len(reachable)
        f['cfg_unreached_instruction_count'] = len(insns)-len(reachable)
        known = {}
        listing.append(f"\nFunction {f['start']:#x}..{f['end']:#x}")
        for ins in insns:
            if not ins.id:
                undecoded.append(dict(function=f['start'], at=ins.address,
                                      bytes=ins.bytes.hex(), cfg_reachable=ins.address in reachable))
                listing.append(f'{ins.address:#x}: {ins.mnemonic} {ins.op_str} ; opaque word')
                known.clear()
                continue
            if ins.address not in reachable:
                listing.append(f'{ins.address:#x}: {ins.mnemonic} {ins.op_str} ; not reached by bounded CFG')
                known.clear()
                continue
            ops = ins.operands
            refs, call = [], None
            before = dict(known)
            _, writes = ins.regs_access()
            for reg in writes:
                known.pop(reg, None)
            if ins.mnemonic in ('adrp', 'adr') and len(ops) == 2 and ops[1].type == ARM64_OP_IMM:
                known[ops[0].reg] = ops[1].imm
            elif ins.mnemonic == 'add' and len(ops) == 3 and ops[1].type == ARM64_OP_REG and ops[2].type == ARM64_OP_IMM:
                if ops[1].reg in before:
                    known[ops[0].reg] = before[ops[1].reg]+(ops[2].imm << ops[2].shift.value)
            elif ins.mnemonic == 'ldr' and len(ops) == 2 and ops[1].type == ARM64_OP_MEM:
                memory = ops[1].mem
                if not memory.index and memory.base in before:
                    address = before[memory.base]+memory.disp
                    if address in iat:
                        known[ops[0].reg] = ('import', iat[address], address)
            # ADRP alone names a page, not the string accidentally at that page.
            produced = [known.get(ops[0].reg)] if ins.mnemonic in ('add', 'adr') else []
            for value in produced:
                if isinstance(value, int) and value not in before.values() and (value in strings or value in starts):
                    ref = dict(at=ins.address, target=value,
                               string=strings.get(value), function=value in starts)
                    f['references'].append(ref)
                    refs.append(ref)
            if ins.mnemonic == 'bl' and ops[0].type == ARM64_OP_IMM:
                call = dict(at=ins.address, target=ops[0].imm, kind='direct', within_pdata=ops[0].imm in starts)
                f['calls'].append(call)
            elif ins.mnemonic == 'blr':
                value = before.get(ops[0].reg)
                call = dict(at=ins.address, kind='indirect', operand=ins.op_str)
                if isinstance(value, tuple):
                    call.update(import_name=value[1], iat=value[2])
                f['calls'].append(call)
                indirect_calls.append(dict(function=f['start'], **call))
            annotations = [(r.get('string') or f"function {r['target']:#x}").replace('\n', r'\n').replace('\r', r'\r') for r in refs]
            if call and call.get('import_name'):
                annotations.append(call['import_name'])
            listing.append(f'{ins.address:#x}: {ins.mnemonic} {ins.op_str}' +
                           (' ; ' + ' | '.join(annotations) if annotations else ''))
            # Reset across calls/branches: no inferred values across basic blocks.
            if ins.mnemonic in ('bl', 'blr'):
                known = {k:v for k,v in known.items() if md.reg_name(k) in ('x19','x20','x21','x22','x23','x24','x25','x26','x27','x28')}
            elif ins.mnemonic == 'b' or ins.mnemonic.startswith('b.') or ins.mnemonic in ('cbz','cbnz','tbz','tbnz','br','ret'):
                known.clear()
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('firmware_audit', out / 'audit_firmware.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    firmware = parser.extract((out / 'dsdt.dsl').read_text())
    devices = {name: states for name, states in firmware['devices'].items()
               if name in (r'\\_SB.CAMP', r'\\_SB.MPCS', r'\\_SB.VFE0')}
    functions_by_start = {f['start']:f for f in functions}
    selected = [
        (0x140029780, 0x14002995c, 'direct', 0x140002620),
        (0x140002620, 0x140002820, 'import_name', 'PoFxRegisterDevice'),
        (0x140002620, 0x140002838, 'import_name', 'PoFxStartDevicePowerManagement'),
        (0x140001850, 0x140001984, 'direct', 0x1400023f8),
        (0x140001850, 0x140001968, 'direct', 0x1400024f8),
        (0x1400023f8, 0x1400024b0, 'import_name', 'PoFxActivateComponent'),
        (0x1400024f8, 0x1400025b0, 'import_name', 'PoFxIdleComponent'),
        (0x140029780, 0x1400299c8, 'direct', 0x1400038d8),
        (0x140029780, 0x1400299cc, 'direct', 0x14002a278),
        (0x14002a278, 0x14002a4e0, 'import_name', 'PoFxRegisterComponentPerfStates'),
    ]
    proofs = []
    for start, at, kind, target in selected:
        calls = [c for c in functions_by_start[start]['calls'] if c['at'] == at]
        assert len(calls) == 1
        assert calls[0].get('target' if kind == 'direct' else kind) == target
        proofs.append(dict(function=start, **calls[0]))
    assert not any(w['cfg_reachable'] for w in undecoded)
    assert data[offset(0x3cf0, 4):offset(0x3cf0, 4)+4] == b'PERF'
    result = dict(scope='Offline bounded MIPI power-call inventory; analog ownership not established',
                  inputs=inputs, image_base=base, sections=sections, functions=functions,
                  exception_record_count=len(functions), opaque_words=undecoded,
                  indirect_calls=indirect_calls, strings={hex(k):v for k,v in strings.items()},
                  firmware_camera_states=devices,
                  literal_firmware_packages_verified=firmware['literal_packages_verified'],
                  selected_power_call_sites=proofs, perf_method_literal_rva=0x3cf0,
                  analog_supply_mapping_established=False, hardware_operations=0,
                  limits=['Only PE exception-covered functions decoded; leaf functions may lack records',
                          'References/calls require bounded CFG reachability; unresolved indirect branches stop that path',
                          'Simple address tracking resets at branches; indirect/interface/WDF calls remain unresolved',
                          'Function/string associations and imports do not establish an entire power call graph',
                          'No absence proof for external regulator operations or physical rails'])
    (out / 'imports.json').write_text(json.dumps(imports, indent=2)+'\n')
    (out / 'mipi-functions.txt').write_text('\n'.join(listing)+'\n')
    (out / 'mipi-power-inventory.json').write_text(json.dumps(result, indent=2)+'\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    print(json.dumps(dict(output=str(out), functions=len(functions), opaque_words=len(undecoded),
                         resolved_import_calls=sum('import_name' in c for c in indirect_calls),
                         unresolved_indirect_calls=sum('import_name' not in c for c in indirect_calls),
                         manifest_sha256=sha(out / 'SHA256SUMS'))))


if __name__ == '__main__':
    main()
