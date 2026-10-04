#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Add frozen Venus nodes to AX's exact reviewed camera/privacy DT description."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import libfdt
from video_dt_contract import validate as validate_provider_contracts

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_aq_dtb_delta_ar import flatten

STAGE = Path('/var/tmp/spx-mainline-trial-20261003ay')
PARENT = Path('/var/tmp/spx-mainline-trial-20261003ax/dtb-build')
SOURCE = STAGE / 'source'
NODE = '/soc@0/video-codec@aa00000'
MEM = '/reserved-memory/video-firmware'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + ';\n'


def main():
    global STAGE, SOURCE, PARENT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--parent', type=Path, default=PARENT)
    args = parser.parse_args()
    STAGE, PARENT = args.stage, args.parent
    SOURCE = STAGE / 'source'
    assert SOURCE.is_dir()
    base = PARENT / 'spx.dtb'
    assert sha(base) == '50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c'
    output = STAGE / 'dtb-build'
    assert not output.exists(), 'Preserve existing DT preparation; use a fresh stage'
    output.mkdir(mode=0o700)
    shutil.copy2(Path(__file__), output / 'prepare_dtb.py')
    shutil.copy2(Path(__file__).with_name('video_dt_contract.py'), output / 'video_dt_contract.py')
    for name in ('as-base.pre.dts', 'spx-rear-privacy.dtsi'):
        shutil.copy2(PARENT / name, output / name)
    old = flatten(base.read_bytes())
    # Pin all historical phandles, including the added rear/LED nodes. New
    # consumers must not renumber any property in the actual AX boot tree.
    pins = []
    for path, props in old.items():
        if 'phandle' in props:
            value = int(props['phandle'], 16)
            pins.append(f'&{{{path}}} {{ phandle = <0x{value:x}>; }};\n')
    (output / 'parent-phandles.dtsi').write_text(''.join(pins))
    soc = (SOURCE / 'arch/arm64/boot/dts/qcom/sc8180x.dtsi').read_text()
    board = (SOURCE / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts').read_text()
    headers = ('clock/qcom,gcc-sc8180x.h', 'clock/qcom,videocc-sm8150.h',
               'interconnect/qcom,sc8180x.h', 'interrupt-controller/arm-gic.h',
               'power/qcom,rpmhpd.h')
    text = ''.join(f'#include <dt-bindings/{name}>\n' for name in headers)
    text += '&{/reserved-memory} {\n' + block(board, 'venus_mem: video-firmware') + '};\n'
    text += '&{/soc@0} {\n' + block(soc, 'venus: video-codec@aa00000') + '};\n'
    text += block(board, '&venus {')
    (output / 'video-candidate.dtsi').write_text(text)
    (output / 'candidate.dts').write_text('#include "as-base.pre.dts"\n'
        '#include "spx-rear-privacy.dtsi"\n#include "parent-phandles.dtsi"\n'
        '#include "video-candidate.dtsi"\n')
    commands = []

    def run(name, argv):
        with (output / (name + '.log')).open('x') as stream:
            result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, timeout=90)
        commands.append(dict(name=name, argv=argv, exit_code=result.returncode))
        assert result.returncode == 0, name

    run('cpp', ['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
                 '-I', str(SOURCE / 'include'), '-I', str(output), str(output / 'candidate.dts'),
                 '-o', str(output / 'candidate.pre.dts')])
    run('dtc', ['dtc', '-I', 'dts', '-O', 'dtb', '-H', 'epapr', '-o', str(output / 'spx.dtb'),
                 str(output / 'candidate.pre.dts')])
    raw = (output / 'spx.dtb').read_bytes()
    provider_contracts = validate_provider_contracts(raw)
    (output / 'provider-contracts.json').write_text(json.dumps(provider_contracts, indent=2) + '\n')
    new = flatten(raw)
    expected = {MEM, NODE, NODE + '/opp-table'} | {
        NODE + '/opp-table/opp-' + str(rate) for rate in
        (200000000, 240000000, 338000000, 365000000, 444000000, 533000000)}
    assert set(new) - set(old) == expected and not set(old) - set(new)
    added_phandles = {
        '/soc@0/clock-controller@ab00000',
        '/soc@0/rsc@18200000/power-controller/opp-table/opp9',
    }
    for path, props in old.items():
        right = dict(new[path])
        if path in added_phandles:
            assert 'phandle' not in props and 'phandle' in right
            del right['phandle']
        assert right == props, path
    before, after = libfdt.Fdt(base.read_bytes()), libfdt.Fdt(raw)
    assert before.num_mem_rsv() == after.num_mem_rsv()
    assert all(before.get_mem_rsv(i) == after.get_mem_rsv(i) for i in range(before.num_mem_rsv()))
    # Check every external phandle in the new consumer against its exact
    # physical provider, and the internal references against the new nodes.
    offset = after.path_offset(NODE)
    expected_paths = {
        'clocks': ['/soc@0/clock-controller@ab00000', '/soc@0/clock-controller@ab00000',
                   '/soc@0/clock-controller@100000', '/soc@0/clock-controller@ab00000',
                   '/soc@0/clock-controller@100000', '/soc@0/clock-controller@ab00000',
                   '/soc@0/clock-controller@100000'],
        'resets': ['/soc@0/clock-controller@100000', '/soc@0/clock-controller@ab00000'],
        'iommus': ['/soc@0/iommu@15000000'],
    }
    for prop, paths in expected_paths.items():
        values = bytes(after.getprop(offset, prop))
        cells = struct.unpack('>' + 'I' * (len(values) // 4), values)
        step = 3 if prop == 'iommus' else 2
        assert [after.get_path(after.node_offset_by_phandle(value)) for value in cells[::step]] == paths
    inputs = {str(path): sha(path) for path in (base, PARENT / 'as-base.pre.dts',
        PARENT / 'spx-rear-privacy.dtsi', SOURCE / 'arch/arm64/boot/dts/qcom/sc8180x.dtsi',
        SOURCE / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts')}
    report = dict(parent_dtb_sha256=sha(base), candidate_dtb_sha256=sha(output / 'spx.dtb'),
                  only_added_nodes=sorted(expected),
                  only_added_existing_properties={path: 'phandle' for path in sorted(added_phandles)},
                  all_existing_property_values_exact=True,
                  all_existing_memory_reservations_exact=True,
                  candidate_resources_extracted_from_frozen_source=True,
                  provider_argument_counts_and_interconnect_tags_verified=True,
                  inputs=inputs, commands=commands, hardware_operations=0, deployed=False)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'sha256.json').write_text(json.dumps({str(path.relative_to(output)): sha(path)
        for path in sorted(output.rglob('*')) if path.is_file()}, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
