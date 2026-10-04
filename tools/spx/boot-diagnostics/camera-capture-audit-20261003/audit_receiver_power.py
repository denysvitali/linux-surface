#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract SQ2 receiver firmware packages and check retained PoFx callback bytes.

Offline only: parses original files and disassembles selected ARM64 ranges as
data. Does not load vendor code, evaluate ACPI or access a device.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

REPO = Path(__file__).resolve().parents[4]
FILES = Path('/home/dvitali/Documents/drivers/FileRepository')
MIPI = FILES / 'qccammipicsi8180.inf_arm64_b579e0018fd8f1d6'
PEP = FILES / 'surfaceprox_pep.inf_arm64_6f779ee9c199c1af'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_packages(extract, source):
    packages, methods = {}, []
    # CPXC-only inventories do not cover the independent CPC0/CPC1/CPC2 tables.
    for name, count, method in [('CPXC', 986, 'CPMX'), ('CPC0', 102, 'C0MD'),
                                ('CPC1', 158, 'C1MD'), ('CPC2', 1229, 'C2MD')]:
        package = extract(source, name)
        assert package['literal_packages_verified'] == count
        package['package_start_line'] = package.pop('cpxc_start_line')
        packages[name] = package
        pattern = (rf'Method \({method}, 0, NotSerialized\)\s*'
                   rf'\{{\s*Return \({name}\)')
        match = re.search(pattern, source)
        assert match is not None, (method, name)
        methods.append(dict(method=method, returns=name,
                            line=source.count('\n', 0, match.start())+1))
    assert r'\\_SB.MPCS' not in packages['CPXC']['devices']
    assert r'\\_SB.VFE0' not in packages['CPXC']['devices']
    expected = [('CPC0', r'\\_SB.JPGE', 2), ('CPC1', r'\\_SB.MPCS', 4),
                ('CPC2', r'\\_SB.VFE0', 13)]
    summary = []
    for name, device, components in expected:
        assert list(packages[name]['devices']) == [device]
        states = packages[name]['devices'][device]
        assert [(s['kind'], s['component'], s['state']) for s in states] == [
            ('FSTATE', component, state) for component in range(components)
            for state in range(2)]
        operations = Counter(a['operation'] for s in states for a in s['actions'])
        # This absence applies only to the literal actions in these tables.
        assert operations['PMICVREGVOTE'] == 0
        summary.append(dict(package=name, device=device, components=components,
                            states=len(states), action_counts=dict(operations)))

    mpcs = packages['CPC1']['devices'][r'\\_SB.MPCS']
    for component in range(4):
        common = [('CLOCK', ['gcc_camera_xo_clk', 1]),
                  ('CLOCK', ['gcc_camera_ahb_clk', 1]),
                  ('CLOCK', ['cam_cc_gdsc_clk', 1]),
                  ('FOOTSWITCH', ['titan_top_gdsc', 1]),
                  ('CLOCK', ['cam_cc_camnoc_axi_clk', 1]),
                  ('CLOCK', ['cam_cc_cpas_ahb_clk', 1])]
        active = [('NPARESOURCE', [1, '/arc/client/rail_mmcx', 48]), *common,
                  ('CLOCK', [f'cam_cc_csi{component}phytimer_clk', 8, 300000000, 3]),
                  ('CLOCK', [f'cam_cc_csiphy{component}_clk', 8, 300000000, 3])]
        idle = [(op, [args[0], 2]) for op, args in reversed(active[1:])]
        idle.append(('NPARESOURCE', [1, '/arc/client/rail_mmcx', 0]))
        for state, expected_actions in zip(mpcs[component*2:component*2+2],
                                           (active, idle)):
            assert [(a['operation'], a['arguments']) for a in state['actions']] == expected_actions

    vfe = packages['CPC2']['devices'][r'\\_SB.VFE0']
    rates = []
    for component in range(8):
        prefix = f'ife_{component}' if component < 4 else f'ife_lite_{component-4}'
        found = [a for a in vfe[component*2]['actions'] if a['operation'] == 'CLOCK'
                 and a['arguments'][0] == f'cam_cc_{prefix}_cphy_rx_clk']
        assert len(found) == 1
        assert found[0]['arguments'] == [f'cam_cc_{prefix}_cphy_rx_clk', 8, 400000000, 3]
        rates.append(dict(component=component, **found[0]))
    return dict(packages=packages, return_methods=methods, separate_tables=summary,
                vfe_receiver_rate_fields=rates,
                total_literal_packages_verified=sum(
                    p['literal_packages_verified'] for p in packages.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = args.output
    out.mkdir(mode=0o700)
    paths = {
        'dsdt.dsl': Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl'),
        'qccammipicsi8180.sys': MIPI / 'qccammipicsi8180.sys',
        'qccammipicsi8180.inf': MIPI / 'qccammipicsi8180.inf',
        'qcpep8180.sys': PEP / 'qcpep8180.sys',
        'surfaceprox_pep.inf': PEP / 'surfaceprox_pep.inf',
        'audit_firmware.py': REPO / 'tools/spx/boot-diagnostics/camera-power-20261003/audit_firmware.py',
        'camcc-sc8180x.c': REPO / 'drivers/clk/qcom/camcc-sc8180x.c',
        'sc8180x.dtsi': REPO / 'arch/arm64/boot/dts/qcom/sc8180x.dtsi',
        'audit_receiver_power.py': Path(__file__).resolve(),
    }
    expected_hashes = {
        'dsdt.dsl': 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8',
        'qccammipicsi8180.sys': '39e299af8ada6d80778f510c363085f49c5a06d94d418ce98ea87065c806a306',
        'qccammipicsi8180.inf': '821f1172fe7ab910e45bea489d059744bb17f4689f55612d520881fbd8a8e40e',
        'qcpep8180.sys': '751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde',
        'surfaceprox_pep.inf': '291a4b2ebcd4ee677e6604a3a98d9300fa29f13f8e3d843683054fef1f0a44ef',
        'audit_firmware.py': 'd3c9dce5ff967c5b5df764900df444bd1d47c56630ebc5148f130c74dda846a6',
    }
    inputs = {}
    for name, path in paths.items():
        digest = sha(path)
        if name in expected_hashes:
            assert digest == expected_hashes[name], name
        inputs[name] = dict(path=str(path), sha256=digest)
        shutil.copyfile(path, out / name)
        assert sha(out / name) == digest
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('pep_literals', out / 'audit_firmware.py')
    firmware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(firmware)
    result = check_packages(firmware.extract, (out / 'dsdt.dsl').read_text())

    data = (out / 'qccammipicsi8180.sys').read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[:2] == b'MZ' and data[pe:pe+4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
    base = struct.unpack_from('<Q', data, pe+48)[0]
    assert base == 0x140000000
    section_count = struct.unpack_from('<H', data, pe+6)[0]
    optional = struct.unpack_from('<H', data, pe+20)[0]
    sections = []
    for i in range(section_count):
        at = pe+24+optional+i*40
        vsize, rva, size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append(dict(name=data[at:at+8].split(b'\0')[0].decode(),
                             vsize=vsize, rva=rva, size=size, raw=raw))

    def read(rva, size):
        found = [s for s in sections if s['rva'] <= rva and
                 rva+size <= s['rva']+s['size']]
        assert len(found) == 1
        at = found[0]['raw']+rva-found[0]['rva']
        return data[at:at+size]

    pdata = next(s for s in sections if s['name'] == '.pdata')
    exception_ranges = {}
    for at in range(pdata['raw'], pdata['raw']+pdata['vsize'], 8):
        start, unwind = struct.unpack_from('<II', data, at)
        if unwind & 3:
            length = ((unwind >> 2) & 0x7ff)*4
        else:
            length = (struct.unpack('<I', read(unwind, 4))[0] & 0x3ffff)*4
        exception_ranges[start] = start+length
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoded, ranges, listing = {}, [], []
    selected = [(0x2620, 0x2a00), (0x2aa0, 0x2af8), (0x2b00, 0x2b50),
                (0x2b50, 0x2b70), (0x2b70, 0x2bb0), (0x2bb0, 0x2bf0),
                (0x2bf0, 0x2cd8), (0x29780, 0x299f0)]
    for start, end in selected:
        leaf = start == 0x2b50
        if leaf:
            assert start not in exception_ranges
            assert exception_ranges[0x2b00] == start and 0x2b70 in exception_ranges
        else:
            assert exception_ranges[start] == end
        raw = read(start, end-start)
        insns = list(md.disasm(raw, base+start))
        assert sum(i.size for i in insns) == len(raw)
        ranges.append(dict(start_rva=start, end_rva=end,
                           exception_covered=not leaf,
                           bytes_sha256=hashlib.sha256(raw).hexdigest()))
        listing.append(f'\nRange {base+start:#x}..{base+end:#x}')
        for insn in insns:
            decoded[insn.address-base] = (insn.mnemonic, insn.op_str)
            listing.append(f'{insn.address:#x}: {insn.mnemonic} {insn.op_str}')
    expected = {
        0x263c: ('mov', 'x27, x0'), 0x2640: ('mov', 'w19, w1'),
        0x264c: ('mov', 'x24, x3'), 0x2664: ('add', 'w8, w19, #2'),
        0x2668: ('lsl', 'w20, w8, #5'), 0x26a8: ('mov', 'w8, #1'),
        0x26ac: ('stp', 'w8, w19, [x22]'),
        0x26b0: ('adrp', 'x8, #0x140002000'),
        0x26b4: ('add', 'x8, x8, #0xaa0'),
        0x26b8: ('str', 'xzr, [x22, #0x38]'), 0x26bc: ('str', 'x8, [x22, #0x18]'),
        0x26c0: ('adrp', 'x9, #0x140002000'), 0x26c4: ('add', 'x9, x9, #0xb00'),
        0x26c8: ('adrp', 'x8, #0x140002000'), 0x26cc: ('add', 'x8, x8, #0xb50'),
        0x26d0: ('stp', 'x8, x9, [x22, #8]'),
        0x26d4: ('adrp', 'x9, #0x140002000'), 0x26d8: ('add', 'x9, x9, #0xb70'),
        0x26dc: ('adrp', 'x8, #0x140002000'), 0x26e0: ('add', 'x8, x8, #0xbb0'),
        0x26e4: ('stp', 'x9, x8, [x22, #0x20]'),
        0x26e8: ('adrp', 'x9, #0x140002000'), 0x26ec: ('add', 'x9, x9, #0xbf0'),
        0x26f8: ('str', 'x9, [x22, #0x30]'),
        0x2738: ('adrp', 'x8, #0x14000b000'), 0x273c: ('add', 'x26, x8, #0x1d0'),
        0x2748: ('add', 'x8, x25, #2'), 0x274c: ('add', 'x23, x22, x8, lsl #5'),
        0x2758: ('mov', 'x1, #0x30'), 0x2764: ('str', 'x0, [x23, #0x18]'),
        0x276c: ('stp', 'xzr, xzr, [x0]'), 0x2770: ('mov', 'w8, #2'),
        0x2774: ('stp', 'xzr, xzr, [x0, #0x10]'),
        0x277c: ('stp', 'xzr, xzr, [x0, #0x20]'),
        0x2788: ('str', 'w8, [x23, #0x10]'),
        0x278c: ('add', 'x8, x26, x25, lsl #4'),
        0x2790: ('ldp', 'x9, x10, [x8]'), 0x2794: ('stp', 'x9, x10, [x23]'),
        0x27d4: ('mov', 'w8, #1'), 0x27e4: ('str', 'w8, [x23, #0x14]'),
        0x2818: ('mov', 'x1, x22'), 0x281c: ('mov', 'x0, x27'),
        0x2b50: ('adrp', 'x8, #0x140007000'), 0x2b54: ('add', 'x3, x8, #0x180'),
        0x2b58: ('mov', 'w4, w1'), 0x2b5c: ('adrp', 'x9, #0x140006000'),
        0x2b60: ('add', 'x1, x9, #0xf88'), 0x2b64: ('mov', 'w2, #9'),
        0x2b68: ('mov', 'w0, #3'), 0x2b6c: ('b', '#0x140002170'),
        0x2c04: ('mov', 'x22, x1'), 0x2c10: ('mov', 'x19, x2'),
        0x2c14: ('mov', 'x21, x3'), 0x2c28: ('mov', 'x20, x6'),
        0x2c34: ('str', 'xzr, [x20]'), 0x2c48: ('ccmp', 'x21, #0x18, #0, ne'),
        0x2c50: ('ldr', 'w8, [x19, #8]'), 0x2c54: ('cbnz', 'w8, #0x140002cc0'),
        0x2c58: ('ldr', 'w8, [x19, #0xc]'), 0x2c5c: ('cmp', 'w8, #2'),
        0x2c7c: ('ldr', 'x4, [x19, #0x10]'), 0x2cb0: ('str', 'xzr, [x19, #0x10]'),
        0x2cb4: ('mov', 'w8, #2'), 0x2cb8: ('adrp', 'x9, #0x14000b000'),
        0x2cbc: ('str', 'w8, [x9, #0x550]'),
        0x29820: ('ldrh', 'w1, [x20, #0x20]'),
        0x298b4: ('str', 'x0, [x8, w21, uxtw #3]'),
        0x298c0: ('bl', '#0x140004258'), 0x2992c: ('mov', 'x9, #2'),
        0x29930: ('stp', 'xzr, xzr, [x19]'), 0x29934: ('mov', 'w8, #0x1f4'),
        0x29938: ('str', 'x9, [x19, #0x18]'), 0x2993c: ('str', 'w8, [x19, #0x10]'),
        0x29940: ('mov', 'w9, #0x32'), 0x29944: ('mov', 'x8, #5'),
        0x29948: ('str', 'w9, [x19, #0x28]'), 0x2994c: ('str', 'x8, [x19, #0x20]'),
        0x29950: ('ldrh', 'w1, [x20, #0x20]'), 0x29954: ('mov', 'x3, x19'),
        0x29958: ('ldr', 'x0, [x20]'), 0x2995c: ('bl', '#0x140002620'),
    }
    for at, instruction in expected.items():
        assert decoded[at] == instruction, (hex(at), decoded[at], instruction)
    imports = json.loads(subprocess.check_output(
        ['rabin2', '-ij', str(out / 'qccammipicsi8180.sys')], text=True, timeout=30))
    iat = {i['plt']-base: i['name'] for i in imports['imports']}
    selected_imports = []
    for at, adrp_at, reg, slot, name in [
        (0x2820, 0x280c, 'x8', 0xa0, 'PoFxRegisterDevice'),
        (0x2838, 0x2830, 'x8', 0xc8, 'PoFxStartDevicePowerManagement'),
        (0x2ae8, 0x2ae0, 'x9', 0xd0, 'PoFxCompleteIdleState'),
        (0x2b20, 0x2b14, 'x9', 0xe8, 'PoFxCompleteIdleCondition'),
        (0x2b88, 0x2b80, 'x9', 0xb8, 'PoFxReportDevicePoweredOn'),
        (0x2be4, 0x2bdc, 'x9', 0xe0, 'PoFxCompleteDevicePowerNotRequired'),
        (0x2cac, 0x2ca0, 'x8', 0x198, 'ExFreePoolWithTag'),
        (0x298ac, 0x298a4, 'x8', 0x1a8, 'MmMapIoSpaceEx'),
    ]:
        page = 0x9000
        assert decoded[adrp_at] == ('adrp', f'{reg}, #{base+page:#x}'), hex(at)
        assert decoded[adrp_at+4] == ('ldr', f'x8, [{reg}, #{slot:#x}]'), hex(at)
        assert decoded[at] == ('blr', 'x8') and iat[page+slot] == name
        selected_imports.append(dict(call_rva=at, adrp_rva=adrp_at,
                                     iat_rva=page+slot, name=name))

    guid_bytes = [read(0xb1d0+i*16, 16) for i in range(4)]
    pep_bytes = (out / 'qcpep8180.sys').read_bytes()
    guid_report = [dict(component=i, guid=str(uuid.UUID(bytes_le=raw)),
                        rva=0xb1d0+i*16, exact_bytes_occurrences_in_pep=pep_bytes.count(raw))
                   for i, raw in enumerate(guid_bytes)]
    camcc = (out / 'camcc-sc8180x.c').read_text()
    clock_fields = []
    for table, rate in [('ftbl_cam_cc_csi0phytimer_clk_src', 300000000),
                        ('ftbl_cam_cc_cphy_rx_clk_src', 400000000)]:
        match = re.search(rf'static const struct freq_tbl {table}\[\] = \{{(.*?)\n\}};',
                          camcc, re.S)
        assert match and re.search(rf'F\({rate},', match.group(1))
        clock_fields.append(dict(table=table, rate_hz=rate,
                                 line=camcc.count('\n', 0, match.start())+1))
    result.update(inputs=inputs, selected_ranges=ranges,
                  instruction_contract_checks=len(expected), selected_imports=selected_imports,
                  component_guids=guid_report, matching_linux_rate_tables=clock_fields,
                  pofx_version=1, idle_state_count=2, deepest_wakeable_idle_state=1,
                  idle_state_attributes=[dict(state=0, transition_latency_100ns=0,
                                               residency_requirement_100ns=0, nominal_power_uw=500),
                                         dict(state=1, transition_latency_100ns=2,
                                               residency_requirement_100ns=5, nominal_power_uw=50)],
                  callback_rvas=dict(active_condition=0x2b50, idle_condition=0x2b00,
                                     idle_state=0x2aa0, power_required=0x2b70,
                                     power_not_required=0x2bb0, power_control=0x2bf0),
                  analog_supply_mapping_established=False,
                  pep_consumption_of_return_methods_established=False,
                  hardware_operations=0,
                  limits=['Literal table actions do not cover the complete PEP resource graph.',
                          'PoFx metadata attributes are not measured physical timings or power.',
                          'Component count comes from device context; no hardcoded four-count claim.',
                          'Leaf range inferred from published pointer, adjacent ranges and tail branch.',
                          'GUID occurrence search cannot exclude generated identifiers.',
                          'PEP method loading, action-code semantics and analog provider mapping unproven.',
                          'Clock numeric fields match Linux Hz tables; runtime PEP rate semantics untraced.',
                          'Logging and OS import bodies are external; not a whole-program power proof.'])
    (out / 'receiver-power.json').write_text(json.dumps(result, indent=2)+'\n')
    (out / 'selected-mipi-code.txt').write_text('\n'.join(listing)+'\n')
    (out / 'imports.json').write_text(json.dumps(imports, indent=2)+'\n')
    manifest = ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(manifest)
    print(json.dumps(dict(literal_packages=result['total_literal_packages_verified'],
                          tables=result['separate_tables'],
                          instruction_checks=len(expected), imports=len(selected_imports),
                          output_files=len(manifest.splitlines()), manifest_sha256=sha(out / 'SHA256SUMS'))))


if __name__ == '__main__':
    main()
