#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Correlate BC's observed PIL reply with retained TrEE SMC/response translation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
VENDOR = Path('/home/dvitali/Documents/drivers/FileRepository')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bc')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(operand):
    operand = operand.split('//', 1)[0]
    value = re.sub(r'-?0x[0-9a-f]+|-?\b[0-9]+\b',
                   lambda m: str(int(m[0], 16 if '0x' in m[0] else 10)), operand)
    return re.sub(r'[\s#]', '', value)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    out = p.parse_args().out
    out.mkdir(mode=0o700)
    reader = ROOT / 'tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_loader.py'
    assert sha(reader) == '68eb3cfe6105ac1e1cd1bae17ca6dc7f4274e497e9d9e85b8fc92847bdfbd41b'
    shutil.copy2(reader, out / 'pe_reader.py')
    spec = importlib.util.spec_from_file_location('response_pe', out / 'pe_reader.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vendor = VENDOR / 'surfaceprox_tree.inf_arm64_aa897ec6bd060d05/QcTrEE8180.sys'
    assert sha(vendor) == '2d8805c2b9b7363753d733c5770c8560f2cea594f48483f32bf477fc4eb135ab'
    shutil.copy2(vendor, out / vendor.name)
    image = module.Image(vendor.read_bytes())
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    # The assembly SMC thunks precede the .pdata-covered C functions. Their
    # ranges are instruction/return bounded, not claimed to come from .pdata.
    ranges = [(0x1028, 0x1080, False), (0x1080, 0x10d8, False),
              (0x16cc0, 0x17000, True), (0x17300, 0x1781c, True),
              (0x17820, 0x1797c, True), (0x17980, 0x17ca4, True),
              (0x17cb0, 0x182dc, True)]
    decoded, listing, gnu = {}, [], {}
    for start, end, pdata in ranges:
        if pdata:
            assert image.functions[start] == end
        raw = image.read(start, end-start)
        binary = out / f'tree-{start:x}-{end:x}.bin'
        binary.write_bytes(raw)
        listing.append(f'function {start:x}..{end:x}; pdata={pdata}')
        for i in md.disasm(raw, image.base+start):
            decoded[i.address-image.base] = (i.mnemonic, i.op_str)
            listing.append(f'{i.address-image.base:x}: {i.mnemonic} {i.op_str}')
        dump = subprocess.check_output(['objdump', '-D', '-b', 'binary', '-m', 'aarch64',
            '--adjust-vma=' + hex(image.base+start), str(binary)], text=True)
        (out / (binary.name + '.objdump')).write_text(dump)
        for line in dump.splitlines():
            match = re.match(r'\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(\S+)\s*(.*)', line)
            if match:
                gnu[int(match[1], 16)-image.base] = (match[2], match[3])
    pins = {
        0x1098: ('mov', 'x19, x2'), 0x109c: ('mov', 'x20, x3'),
        0x10a0: ('ldp', 'x2, x3, [x19], #0x10'),
        0x10a4: ('ldp', 'x4, x5, [x19], #8'), 0x10a8: ('smc', '#0'),
        0x10ac: ('cmp', 'w0, #0'), 0x10b0: ('b.gt', '#0x1400010a8'),
        0x10b4: ('str', 'x3, [x19, #-8]!'),
        0x10b8: ('stp', 'x1, x2, [x19, #-0x10]!'),
        0x10bc: ('str', 'x6, [x20]'), 0x10c8: ('ret', ''),
        0x1734c: ('mov', 'w26, w1'), 0x17354: ('mov', 'x25, x3'),
        0x17358: ('mov', 'x23, x4'),
        0x175c4: ('ldr', 'w1, [sp, #0x20]'),
        0x175c8: ('orr', 'w0, w26, #0x40000000'),
        0x175cc: ('add', 'x3, sp, #0x28'),
        0x175d4: ('add', 'x2, sp, #0x30'), 0x175d8: ('bl', '#0x140001080'),
        0x175e8: ('mov', 'w25, w0'), 0x176b8: ('cbz', 'w25, #0x1400176f8'),
        0x176f8: ('mov', 'x8, #1'), 0x176fc: ('add', 'x10, sp, #0x30'),
        0x17700: ('str', 'x8, [x23]'), 0x17704: ('ldp', 'x8, x9, [x10]'),
        0x17708: ('stp', 'x8, x9, [x23, #8]'),
        0x1770c: ('ldr', 'x8, [x10, #0x10]'),
        0x17710: ('str', 'x8, [x23, #0x18]'),
        0x178c8: ('bl', '#0x140016cc0'),
        0x178d8: ('cmp', 'x19, x8'), 0x178dc: ('b.lo', '#0x14001791c'),
        0x17910: ('adrp', 'x8, #0x140017000'),
        0x17914: ('add', 'x8, x8, #0x300'),
        0x1794c: ('adrp', 'x8, #0x140016000'),
        0x17950: ('add', 'x8, x8, #0xcc0'),
        0x17954: ('adrp', 'x9, #0x14002c000'),
        0x17958: ('str', 'x8, [x9, #0x1b0]'),
        0x17e48: ('adrp', 'x9, #0x14002c000'),
        0x17e4c: ('ldr', 'x19, [x9, #0x1b0]'),
        0x17e60: ('add', 'x5, sp, #8'), 0x17e64: ('add', 'x4, sp, #0x18'),
        0x17e68: ('add', 'x3, sp, #0x38'), 0x17e6c: ('mov', 'w2, w25'),
        0x17e70: ('mov', 'w1, w21'), 0x17e78: ('blr', 'x19'),
        0x16ed0: ('bl', '#0x140001028'), 0x16ed4: ('mov', 'w21, w0'),
        0x16ed8: ('cbz', 'w21, #0x140016f1c'),
        0x16f1c: ('mov', 'x8, #1'), 0x16f20: ('str', 'x8, [x23]'),
        0x16f30: ('ldr', 'w8, [x10], #4'),
        0x16f38: ('str', 'x8, [x11], #8'),
    }
    for at, expected in pins.items():
        assert decoded[at] == expected, (hex(at), decoded[at], expected)
    gnu_pins = [0x1098, 0x10a0, 0x10a8, 0x10b4, 0x10b8,
                0x176f8, 0x17700, 0x17708, 0x17710, 0x16f20, 0x16f38]
    for at in gnu_pins:
        actual, expected = gnu[at], pins[at]
        assert actual[0] == expected[0] and normalized(actual[1]) == normalized(expected[1]), (hex(at), actual, expected)
    (out / 'tree-functions.txt').write_text('\n'.join(listing) + '\n')
    # Pin the previously verified query wrapper/header and actual BC reply.
    for name in ('offline-pas-memarea-20261004',):
        root = X.parent / '20261004bb' / name
        expected = json.loads((root / 'sha256.json').read_text())
        actual = {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}
        assert actual == expected | {'sha256.json': sha(root / 'sha256.json')}
    header = HERE / 'upstream/scm_sip_interface.h'
    assert sha(header) == 'ace9bf9b6f2adbe8657d380a87f0504a72705060ce0b3e90044b43e1d30f6ca8'
    shutil.copy2(header, out / header.name)
    return_root = X / 'return-review'
    assert sha(return_root / 'sha256.json') == 'bed2fcf066280d5eb7dbe8aa13084c6b75521b30a081d88d944c783322262a4f'
    return_hashes = json.loads((return_root / 'sha256.json').read_text())
    for name, target in (('report.json', 'bc-return-report.json'),
                         ('decoded-pas.json', 'decoded-pas.json'),
                         ('qcom_scm-smc.c', 'qcom_scm-smc.c')):
        assert sha(return_root / name) == return_hashes[name]
        shutil.copy2(return_root / name, out / target)
    decoded_query = json.loads((out / 'decoded-pas.json').read_text())['area_queries'][0]
    assert decoded_query['transport_return'] == 0 and decoded_query['result_valid']
    assert decoded_query['smc_done']['raw_registers'] == [0, 0x8b700000, 0x9ab00000, 0]
    scm = (out / 'qcom_scm-smc.c').read_text()
    assert all(f'res->result[{i}] = smc_res.a{i+1};' in scm for i in range(3))
    report = dict(vendor_sha256=sha(vendor), pinned_instructions=len(pins),
        gnu_operand_checks=len(gnu_pins), pdata_functions=5, assembly_thunks=2,
        smc_registers_stored_in_result_order=['x1', 'x2', 'x3'],
        abstract_completion_one_generated_by_wrapper=True,
        response_field_offsets=dict(completed=0, start=8, end=16),
        linux_result_fields=dict(start=0, end=1),
        observed_bc_start='0x8b700000', observed_bc_end_exclusive='0x9ab00000',
        reported_window_bytes=0x9ab00000-0x8b700000,
        observed_fe500000_reservation_outside_reported_window=True,
        layout_correlated_with_retained_vendor_and_primary_interface=True,
        actual_windows_execution_observed=False, allocation_policy_changed=False,
        pas_memory_acceptance_established=False, encoded_error_meaning_identified=False,
        hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    shutil.copy2(__file__, out / Path(__file__).name)
    expected = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
    assert all(sha(out / name) == digest for name, digest in expected.items())
    print(json.dumps(report | {'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
