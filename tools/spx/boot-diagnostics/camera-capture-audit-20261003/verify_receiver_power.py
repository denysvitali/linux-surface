#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash a receiver power audit and reject incomplete/wrong firmware fixtures."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    inventory, out = args.inventory, args.output
    out.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__), out / Path(__file__).name)
    entries = {}
    for line in (inventory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert Path(name).name == name and name not in entries
        assert sha(inventory / name) == digest, name
        entries[name] = digest
    assert set(entries) == {p.name for p in inventory.iterdir()}-{'SHA256SUMS'}
    report = json.loads((inventory / 'receiver-power.json').read_text())
    assert report['hardware_operations'] == 0
    assert not report['analog_supply_mapping_established']
    assert not report['pep_consumption_of_return_methods_established']
    assert report['total_literal_packages_verified'] == 2475
    assert report['instruction_contract_checks'] == 81
    assert [t['states'] for t in report['separate_tables']] == [4, 8, 26]
    assert len(report['selected_imports']) == 8 and len(report['selected_ranges']) == 8
    for name, metadata in report['inputs'].items():
        assert entries[name] == metadata['sha256']

    # Independent file-offset walk rechecks the selected byte ranges, including
    # the leaf which the original exception-only inventory did not list.
    data = (inventory / 'qccammipicsi8180.sys').read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    section_count = int.from_bytes(data[pe+6:pe+8], 'little')
    optional = int.from_bytes(data[pe+20:pe+22], 'little')
    for selected in report['selected_ranges']:
        start, end = selected['start_rva'], selected['end_rva']
        blobs = []
        for i in range(section_count):
            header = pe+24+optional+40*i
            rva = int.from_bytes(data[header+12:header+16], 'little')
            size = int.from_bytes(data[header+16:header+20], 'little')
            offset = int.from_bytes(data[header+20:header+24], 'little')
            if rva <= start and end <= rva+size:
                blobs.append(data[offset+start-rva:offset+end-rva])
        assert len(blobs) == 1
        assert hashlib.sha256(blobs[0]).hexdigest() == selected['bytes_sha256']
    guids = [g['guid'] for g in report['component_guids']]
    assert guids == ['cbe53db5-ee6a-4e2e-854c-d531436585f2',
                     'b3e9a7e1-7598-4165-bc8a-da7a9e3ee2d0',
                     'e809b7c2-c069-415a-a1e1-288775db9896',
                     '662ef14a-f435-441f-b718-46143f5c6f58']
    sys.dont_write_bytecode = True
    literal = module(inventory / 'audit_firmware.py', 'literal_review')
    # The helper's default paths depend on its repository depth. Verify the
    # live source against the frozen copy before importing at its original path.
    audit_source = Path(report['inputs']['audit_receiver_power.py']['path'])
    assert sha(audit_source) == entries['audit_receiver_power.py']
    audit = module(audit_source, 'receiver_review')
    source = (inventory / 'dsdt.dsl').read_text()
    assert audit.check_packages(literal.extract, source)['packages'] == report['packages']
    begin = source.index('Name (CPC1,')
    end = source.index('Name (CPC2,', begin)
    section = source[begin:end]
    assert section.count('0x11E1A300') == 8
    rate = source[:begin]+section.replace('0x11E1A300', '0x11F0E540', 1)+source[end:]
    order = source[:begin]+section.replace('"cam_cc_csi0phytimer_clk"',
                                          '"cam_cc_csiphy0_clk"', 1)+source[end:]
    fixtures = {
        'missing-cpc1': source.replace('Name (CPC1,', 'Name (CPC9,', 1),
        'wrong-mpcs-rate': rate,
        'wrong-mpcs-clock-order': order,
        'missing-c1md-return-method': source.replace('Method (C1MD,', 'Method (C9MD,', 1),
    }
    rejected = []
    for name, fixture in fixtures.items():
        path = out / f'{name}.dsl'
        path.write_text(fixture)
        try:
            audit.check_packages(literal.extract, fixture)
        except (AssertionError, ValueError) as error:
            rejected.append(dict(name=name, fixture_sha256=sha(path),
                                 error_type=type(error).__name__, reason=str(error)))
        else:
            raise AssertionError(f'accepted wrong firmware fixture: {name}')
    result = dict(inventory_manifest_sha256=sha(inventory / 'SHA256SUMS'),
                  inventory_files_verified=len(entries), selected_ranges_verified=8,
                  positive_raw_package_replay=True, rejected_fixtures=rejected,
                  hardware_operations=0)
    (out / 'review.json').write_text(json.dumps(result, indent=2)+'\n')
    manifest = ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(manifest)
    print(json.dumps(dict(files_verified=len(entries), negative_fixtures_rejected=len(rejected),
                          review_manifest_sha256=sha(out / 'SHA256SUMS'))))


if __name__ == '__main__':
    main()
