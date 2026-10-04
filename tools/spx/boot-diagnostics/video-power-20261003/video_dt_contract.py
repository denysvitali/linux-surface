#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Parse Venus references using each provider's declared argument count."""
import argparse
import json
from pathlib import Path
import struct

import libfdt

NODE = '/soc@0/video-codec@aa00000'
ICC = [('/soc@0/interconnect@1740000', [7, 0]),
       ('/interconnect-mc-virt', [1, 0]),
       ('/soc@0/interconnect@9680000', [0, 0]),
       ('/soc@0/interconnect@1500000', [54, 0])]
VIDEOCC = '/soc@0/clock-controller@ab00000'
GCC = '/soc@0/clock-controller@100000'
RPMHPD = '/soc@0/rsc@18200000/power-controller'
EXPECTED = {
    'interconnects': ICC,
    'clocks': [(VIDEOCC, [4]), (VIDEOCC, [0]), (GCC, [227]),
               (VIDEOCC, [2]), (GCC, [225]), (VIDEOCC, [3]), (GCC, [226])],
    'resets': [(GCC, [41]), (VIDEOCC, [0])],
    'power-domains': [(VIDEOCC, [0]), (VIDEOCC, [1]), (VIDEOCC, [2]), (RPMHPD, [6])],
    'iommus': [('/soc@0/iommu@15000000', [0x2300, 0x60])],
    'memory-region': [('/reserved-memory/video-firmware', [])],
    'operating-points-v2': [(NODE + '/opp-table', [])],
}


def cells(tree, offset, prop):
    raw = bytes(tree.getprop(offset, prop))
    if len(raw) % 4:
        raise ValueError(f'{prop}: non-cell-aligned property')
    return list(struct.unpack('>' + 'I' * (len(raw) // 4), raw))


def references(tree, path, prop, count_prop=None):
    values = cells(tree, tree.path_offset(path), prop)
    result, index = [], 0
    while index < len(values):
        handle = values[index]
        try:
            provider = tree.node_offset_by_phandle(handle)
            provider_path = tree.get_path(provider)
            counts = cells(tree, provider, count_prop) if count_prop else [0]
        except libfdt.FdtException as error:
            raise ValueError(f'{path}:{prop}: cell {index}, phandle {handle:#x}: '
                             f'cannot resolve provider/{count_prop}') from error
        if len(counts) != 1 or not 0 <= counts[0] <= 16:
            raise ValueError(f'{provider_path}: invalid {count_prop} count {counts}')
        end = index + 1 + counts[0]
        if end > len(values):
            raise ValueError(f'{path}:{prop}: truncated arguments at cell {index}')
        result.append((provider_path, values[index + 1:end]))
        index = end
    return result


def validate(raw):
    tree = libfdt.Fdt(raw)
    parsed = {}
    for prop, width in [('interconnects', '#interconnect-cells'),
                        ('clocks', '#clock-cells'), ('resets', '#reset-cells'),
                        ('power-domains', '#power-domain-cells'),
                        ('iommus', '#iommu-cells'), ('memory-region', None),
                        ('operating-points-v2', None)]:
        parsed[prop] = references(tree, NODE, prop, width)
    for prop, expected in EXPECTED.items():
        if parsed[prop] != expected:
            raise ValueError(f'Unexpected {prop} providers/arguments: {parsed[prop]}')
    names = bytes(tree.getprop(tree.path_offset(NODE), 'interconnect-names'))
    if names != b'video-mem\0cpu-cfg\0':
        raise ValueError('Incorrect interconnect path names/order')
    parsed['required-opps'] = {}
    for hz, level in [(200000000, 64), (240000000, 64), (338000000, 128),
                      (365000000, 192), (444000000, 256), (533000000, 384)]:
        path = NODE + '/opp-table/opp-' + str(hz)
        refs = references(tree, path, 'required-opps')
        if len(refs) != 1 or not refs[0][0].startswith(RPMHPD + '/opp-table/'):
            raise ValueError(f'{path}: incorrect required OPP provider')
        actual = cells(tree, tree.path_offset(refs[0][0]), 'opp-level')
        if actual != [level]:
            raise ValueError(f'{path}: incorrect required OPP level {actual}')
        parsed['required-opps'][path] = refs
    return parsed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.dtb.read_bytes()), indent=2))
