#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check SQ2 PEP clock conversion and retained BSP plans as offline byte data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path, name):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def clock_tables(image):
    """The name lookup's 0x60 stride and the initial BSP pointer are byte checked."""
    base = image.base
    qword = lambda at: struct.unpack('<Q', image.read(at, 8))[0]
    dword = lambda at: struct.unpack('<I', image.read(at, 4))[0]
    string = lambda at: image.read(at, 96).split(b'\0')[0].decode('ascii')
    bsp = 0x189850
    nodes, count = qword(bsp+0x20)-base, dword(bsp+0x28)
    assert nodes == 0x18ae00 and count == 427
    selected, names = [], []
    for index in range(count):
        at = nodes+index*0x60
        name = string(qword(at)-base)
        names.append(name)
        if not (name.startswith('cam_cc_csiphy') or 'cphy_rx_clk' in name or
                re.fullmatch(r'cam_cc_csi[0-3]phytimer_clk', name)):
            continue
        domain = qword(at+8)-base
        table, entries = qword(domain)-base, dword(domain+8)
        assert entries == 2
        plan = []
        for i in range(entries):
            record = table+i*0x38
            eligibility = image.read(record+0x20, 0x18)
            assert eligibility == bytes(0x18), (name, 'conditional eligibility')
            plan.append(dict(record_rva=record, frequency_hz=dword(record),
                             corner=dword(record+0x18), source_rva=qword(record+8)-base,
                             source_name=string(qword(qword(record+8)-base)-base),
                             eligibility_hex=eligibility.hex()))
        rates = [entry['frequency_hz'] for entry in plan]
        timer = 'phytimer' in name
        assert rates == [19200000, 300000000 if timer else 400000000], (name, rates)
        rail = qword(domain+0x10)-base
        assert rail == 0x196230 and string(qword(rail)-base) == '/arc/client/rail_mmcx'
        selected.append(dict(name=name, index=index, node_rva=at, domain_rva=domain,
                             branch_address=qword(at+0x18), domain_rcgr=qword(domain+0x28),
                             rail_rva=rail, rail_name=string(qword(rail)-base), plan=plan))
    assert len(names) == len(set(names)) == 427 and len(selected) == 16
    assert [n['name'] for n in selected[:4]] == [f'cam_cc_csiphy{i}_clk' for i in range(4)]
    assert len({n['domain_rva'] for n in selected[:12]}) == 1
    assert selected[0]['domain_rcgr'] == 0xad0a064
    assert [n['domain_rcgr'] for n in selected[12:]] == [0xad06004+i*0x24 for i in range(4)]
    pd_table, pd_count = qword(bsp+0x60)-base, dword(bsp+0x68)
    assert (pd_table, pd_count) == (0x19c550, 39)
    titan = 0x19c748
    assert string(qword(titan)-base) == 'titan_top_gdsc'
    assert qword(titan+0x10) == 0xad0c1bc and qword(titan+0x38)-base == 0x196230
    return dict(bsp_rva=bsp, clock_node_count=count, clock_node_stride=0x60,
                frequency_record_stride=0x38, selected_nodes=selected,
                titan=dict(node_rva=titan, gdsc_address=0xad0c1bc, rail_rva=0x196230),
                analog_supplier_established=False, live_bsp_observed=False)


def conversion_tables(image):
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    tables = []
    for table, count, kind, anchor, slot in [
            (0x207370, 15, 'b', 0x207370, 0x20),
            (0x207720, 12, 'i', 0x207460, 0x10)]:
        values = struct.unpack('<'+str(count)+kind, image.read(table, count*struct.calcsize(kind)))
        rows = []
        for i, offset in enumerate(values):
            target = anchor+offset*4
            insns = list(md.disasm(image.read(target, 12), image.base+target))
            assert len(insns) == 3 and insns[0].mnemonic == 'mov'
            assert insns[0].op_str.startswith('w8, #')
            assert insns[1].mnemonic == 'str' and insns[1].op_str == f'w8, [sp, #{slot:#x}]'
            value = int(insns[0].op_str.split('#')[1], 0)
            rows.append(dict(firmware_code=i+1, internal_code=value, target_rva=target))
        expected = [1 << i for i in range(15)] if kind == 'b' else [0,1,2,3,16,17,18,19,32,33,34,35]
        assert [r['internal_code'] for r in rows] == expected
        tables.append(dict(table_rva=table, rows=rows))
    return tables


def choose(rates, request, mode):
    if request in rates:
        return request
    below = [r for r in rates if r < request]
    above = [r for r in rates if r > request]
    lower = max(below) if below else None
    upper = min(above) if above else None
    if mode == 0:
        return upper
    if mode == 1:
        return lower
    if mode == 2:
        if upper is None:
            return lower
        if lower is None:
            return upper
        return upper if upper-request < request-lower else lower
    return None


def validate_linux(camcc, camss):
    tables = {}
    for name, expected in [('ftbl_cam_cc_cphy_rx_clk_src', [19200000,400000000]),
                           ('ftbl_cam_cc_csi0phytimer_clk_src', [19200000,300000000])]:
        match = re.search(r'static const struct freq_tbl '+name+r'\[\] = \{(.*?)\n\};', camcc, re.S)
        assert match is not None
        rates = [int(s) for s in re.findall(r'F\((\d+),', match.group(1))]
        assert rates == expected, (name, rates)
        tables[name] = rates
    section = camss.split('static const struct camss_subdev_resources csiphy_res_sc8180x[] = {', 1)[1].split('\n};',1)[0]
    rows = re.findall(r'\.clock_rate = \{ \{ 0 \}, \{ 0 \}, \{ (\d+) \}, \{ (\d+) \} \}', section)
    assert rows == [('400000000','300000000')]*4, rows
    return dict(tables=tables, phy_requests_hz=[400000000]*4, timer_requests_hz=[300000000]*4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[4])
    args = parser.parse_args()
    out, repo = args.output, args.repo
    out.mkdir(mode=0o700)
    previous = Path('/var/tmp/spx-pep-loader-contract-20261003-v1')
    receiver = Path('/var/tmp/spx-receiver-power-20261003-v1')
    paths = {
        'qcpep8180.sys': previous/'qcpep8180.sys', 'dsdt.dsl': previous/'dsdt.dsl',
        'audit_pep_loader.py': previous/'audit_pep_loader.py',
        'prior-loader-SHA256SUMS': previous/'SHA256SUMS',
        'prior-receiver-power.json': receiver/'receiver-power.json',
        'prior-receiver-SHA256SUMS': receiver/'SHA256SUMS',
        'audit_firmware.py': repo/'tools/spx/boot-diagnostics/camera-power-20261003/audit_firmware.py',
        'camcc-sc8180x.c': repo/'drivers/clk/qcom/camcc-sc8180x.c',
        'camss.c': repo/'drivers/media/platform/qcom/camss/camss.c',
        'common.c': repo/'drivers/clk/qcom/common.c', 'clk-rcg2.c': repo/'drivers/clk/qcom/clk-rcg2.c',
        'audit_pep_clock.py': Path(__file__).resolve(),
    }
    pinned = {'qcpep8180.sys':'751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde',
              'dsdt.dsl':'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8',
              'prior-loader-SHA256SUMS':'f2f629de2f2c39edb85cfc01c4430ef695680da88b1db699f5f3447dbabadefa',
              'prior-receiver-SHA256SUMS':'7ca2b4bc51b8f01b2715a0732c139e109b5999a81cc5eff735a56e4b36518943',
              'audit_firmware.py':'d3c9dce5ff967c5b5df764900df444bd1d47c56630ebc5148f130c74dda846a6'}
    inputs = {}
    for name, path in paths.items():
        digest = sha(path)
        if name in pinned:
            assert digest == pinned[name], name
        shutil.copyfile(path, out/name)
        assert sha(out/name) == digest
        inputs[name] = dict(path=str(path), sha256=digest)
    for prefix, files in [('prior-loader', ['audit_pep_loader.py']), ('prior-receiver', ['receiver-power.json'])]:
        manifest = dict(line.split('  ',1)[::-1] for line in (out/(prefix+'-SHA256SUMS')).read_text().splitlines())
        for name in files:
            dest = 'prior-receiver-power.json' if name == 'receiver-power.json' else name
            assert sha(out/dest) == manifest[name]
    loader = module(out/'audit_pep_loader.py','pep_clock_image')
    image = loader.Image((out/'qcpep8180.sys').read_bytes())
    bsp, conversions = clock_tables(image), conversion_tables(image)
    firmware = module(out/'audit_firmware.py','pep_clock_firmware')
    source = (out/'dsdt.dsl').read_text()
    previous_receiver = json.loads((out/'prior-receiver-power.json').read_text())
    packages = {name:firmware.extract(source,name) for name in ('CPC1','CPC2')}
    for data in packages.values():
        data['package_start_line'] = data.pop('cpxc_start_line')
    assert packages['CPC1'] == previous_receiver['packages']['CPC1']
    assert packages['CPC2'] == previous_receiver['packages']['CPC2']
    requests = []
    by_name = {n['name']:n for n in bsp['selected_nodes']}
    for package, data in packages.items():
        for device, states in data['devices'].items():
            for state in states:
                if state['state'] != 0:
                    continue
                for action in state['actions']:
                    argv = action['arguments']
                    if action['operation'] != 'CLOCK' or argv[0] not in by_name or len(argv) != 4:
                        continue
                    name, opcode, requested, mode = argv
                    assert opcode == 8 and mode == 3
                    internal_action = conversions[0]['rows'][opcode-1]['internal_code']
                    internal_mode = conversions[1]['rows'][mode-1]['internal_code']
                    rates = [r['frequency_hz'] for r in by_name[name]['plan']]
                    selected = choose(rates,requested,internal_mode)
                    assert selected == (300000000 if 'phytimer' in name else 400000000)
                    requests.append(dict(package=package, device=device, component=state['component'],
                                         line=action['line'], name=name, firmware_action=opcode,
                                         internal_action=internal_action, firmware_mode=mode,
                                         internal_mode=internal_mode, request_hz=requested,
                                         supported_hz=rates, static_selected_hz=selected))
    assert len(requests) == 16
    linux = validate_linux((out/'camcc-sc8180x.c').read_text(), (out/'camss.c').read_text())
    # These are explicit contracts, not a claim to have resolved the whole PEP CFG.
    contract = {
        0xf1e04:('add','x8, x9, #0x850'), 0xf1e0c:('str','x8, [x21, #0x1a0]'),
        0xf1ff0:('ldr','w20, [x8, #0x28]'), 0xf1ff8:('ldr','x23, [x8, #0x20]'),
        0xf1ffc:('mov','x24, #0x60'), 0xf2010:('bl','#0x140153eac'),
        0x1ec934:('bl','#0x1400f1fc0'), 0x1ec9c0:('bl','#0x140207100'),
        0x1ec9cc:('add','x9, x8, #0x20'), 0x1ec9d4:('str','w8, [x9]'),
        0x1eca38:('bl','#0x140043d70'), 0x1eca5c:('bl','#0x140207388'),
        0x1eca68:('add','x9, x8, #0x28'), 0x1eca70:('str','w8, [x9]'),
        0x1eca88:('bl','#0x1401ec628'),
        0x1ec6bc:('mov','w8, #0x3e8'), 0x1ec6fc:('str','w9, [x8]'),
        0x1ec708:('and','x8, x8, #0xf'),
        0x207160:('sub','w8, w8, #1'), 0x20716c:('cmp','w8, #0xe'),
        0x207178:('adr','x9, #0x140207370'), 0x20717c:('ldrsb','x8, [x9, w10, uxtw]'),
        0x207180:('add','x8, x9, x8, lsl #2'), 0x207184:('br','x8'),
        0x2073ec:('sub','w8, w8, #1'), 0x2073f8:('cmp','w8, #0xb'),
        0x207404:('adr','x9, #0x140207720'), 0x207408:('ldrsw','x8, [x9, w10, uxtw #2]'),
        0x20740c:('adr','x9, #0x140207460'), 0x207410:('add','x8, x9, x8, lsl #2'),
        0x207414:('br','x8'),
        0x1eb09c:('ldr','w3, [x10]'), 0x1eb098:('ldr','w4, [x11]'),
        0x1eb094:('ldr','w5, [x12]'), 0x1eb0ac:('bl','#0x1401f4358'),
        0x1f4be0:('add','x9, x8, #0x6c'), 0x1f4be8:('str','w8, [x9]'),
        0x1f4ea8:('add','x9, x8, #0x70'), 0x1f4eb0:('str','w8, [x9]'),
        0x1f4eb8:('add','x9, x8, #0x74'), 0x1f4ec0:('str','w8, [x9]'),
        0x854e0:('add','x9, x8, #0x18'), 0x854ec:('ldr','w2, [x9]'),
        0x854f0:('ldr','w1, [sp, #0x40]'), 0x854f8:('bl','#0x1400f2200'),
        0xf2248:('mov','w3, w2'), 0xf224c:('mov','w2, w12'),
        0xf2254:('bl','#0x1400f78b8'), 0xf78d8:('mov','w1, w2'),
        0xf78dc:('mov','w2, w3'), 0xf791c:('mov','w25, #0x4240'),
        0xf7920:('movk','w25, #0xf, lsl #16'), 0xf7938:('mov','w8, #0x3e8'),
        0xf7958:('bl','#0x1400f72f8'), 0xf7994:('bl','#0x1400f74b0'),
        0xf734c:('mov','x10, #0x38'), 0xf7354:('madd','x19, x9, x10, x8'),
        0xf7358:('add','x0, x19, #0x20'), 0xf735c:('bl','#0x1400f8fb0'),
        0xf736c:('cmp','w8, w21'), 0xf7370:('b.eq','#0x1400f73e4'),
        0xf7378:('ccmp','w8, w24, #0xe, hi'), 0xf737c:('csel','w24, w8, w24, lo'),
        0xf738c:('ccmp','w8, w25, #4, lo'), 0xf7390:('csel','w25, w8, w25, hi'),
        0xf73ac:('cbz','w9, #0x1400f7400'), 0xf73b0:('cmp','w9, #1'),
        0xf73b8:('cmp','w9, #2'), 0xf73bc:('b.ne','#0x1400f7410'),
        0xf73c8:('sub','w9, w21, w25'), 0xf73cc:('sub','w8, w24, w21'),
        0xf73d0:('cmp','w8, w9'), 0xf73d4:('b.hs','#0x1400f73f4'),
        0xf73d8:('str','x23, [x26]'), 0xf73e4:('str','x19, [x26]'),
        0xf73f4:('str','x22, [x26]'), 0xf7404:('str','x23, [x26]'),
        0xf7410:('str','xzr, [x26]'),
        0xf8fd0:('ldr','w9, [x20, #4]'), 0xf8ff4:('ldr','x19, [x20, #8]'),
        0xf9040:('ldrb','w8, [x20, #1]'), 0xf9044:('ldrb','w9, [x20]'),
        0xf9060:('cbnz','w11, #0x1400f907c'), 0xf9064:('cbnz','w9, #0x1400f9084'),
        0xf9068:('mov','w0, #1'),
    }
    starts = [0xf1de0,0xf1fc0,0x1ec890,0x1ec628,0x207100,0x207388,
              0x1ead90,0x1f4358,0x84b50,0xf2200,0xf78b8,0xf72f8,0xf8fb0]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    decoded, ranges, listing = {}, [], []
    for start in starts:
        end = image.functions[start]
        raw = image.read(start,end-start)
        insns = list(md.disasm(raw,image.base+start))
        assert sum(i.size for i in insns) == len(raw)
        ranges.append(dict(start_rva=start,end_rva=end,bytes_sha256=hashlib.sha256(raw).hexdigest()))
        listing.append(f'Function {start:#x}..{end:#x}')
        for i in insns:
            at = i.address-image.base
            decoded[at] = (i.mnemonic,i.op_str)
            listing.append(f'{at:#x}: {i.mnemonic} {i.op_str}')
    for at, instruction in contract.items():
        assert decoded[at] == instruction, (hex(at),decoded[at],instruction)
    assert struct.unpack('<Q',image.read(0x1c07f8,8))[0]-image.base == 0x84b50
    result = dict(inputs=inputs, bsp=bsp, conversions=conversions, requests=requests,
                  linux=linux, selected_ranges=ranges, exception_records=image.exception_count,
                  instruction_checks=len(contract), hardware_operations=0,
                  limits=['Static retained BSP; live Windows requests, mutations and execution unobserved.',
                          'Selected call sites and conversion branches do not resolve the complete NPA graph.',
                          'All selected plan eligibility tuples are zero; no board fuse query is made.',
                          'MMCX domain pointers are not dedicated PHY/PLL analog supplier evidence.',
                          'Kernel table alignment does not establish capture, rate readback or acceptance.'])
    (out/'pep-clock.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'pep-clock-code.txt').write_text('\n'.join(listing)+'\n')
    (out/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    print(json.dumps(dict(clock_nodes=bsp['clock_node_count'],
                          selected_nodes=16,request_records=16,instruction_checks=len(contract),
                          manifest_sha256=sha(out/'SHA256SUMS'))))


if __name__ == '__main__':
    main()
