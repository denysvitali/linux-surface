#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile disabled review DTS and compare its camera topology to pinned v23."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import libfdt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SCRATCH = Path('/var/tmp/spx-camera-offline-20260922')
PHANDLE_PROPS = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
                 'power-domains': '#power-domain-cells', 'iommus': '#iommu-cells',
                 'interconnects': '#interconnect-cells', 'reset-gpios': '#gpio-cells',
                 'enable-gpios': '#gpio-cells', 'pinctrl-0': None,
                 'remote-endpoint': None}


def words(value):
    return struct.unpack('>' + 'I' * (len(value) // 4), value)


def properties(fdt, node):
    result = {}
    offset = fdt.first_property_offset(node, quiet=(libfdt.NOTFOUND,))
    while offset >= 0:
        prop = fdt.get_property_by_offset(offset)
        result[prop.name] = bytes(prop)
        offset = fdt.next_property_offset(offset, quiet=(libfdt.NOTFOUND,))
    return result


def subtree(fdt, path):
    result = {}

    def visit(node):
        result[fdt.get_path(node)] = properties(fdt, node)
        child = fdt.first_subnode(node, quiet=(libfdt.NOTFOUND,))
        while child >= 0:
            visit(child)
            child = fdt.next_subnode(child, quiet=(libfdt.NOTFOUND,))

    visit(fdt.path_offset(path))
    return result


def normalized(fdt, prop, value):
    if prop not in PHANDLE_PROPS:
        return value.hex()
    data, result, i = words(value), [], 0
    while i < len(data):
        provider = fdt.node_offset_by_phandle(data[i])
        count_prop = PHANDLE_PROPS[prop]
        count = words(fdt.getprop(provider, count_prop))[0] if count_prop else 0
        result.append([fdt.get_path(provider), *data[i + 1:i + 1 + count]])
        i += 1 + count
    assert i == len(data)
    return result


def main():
    manifest = json.loads((HERE / 'extraction-manifest.json').read_text())
    reference = Path(manifest['reference'])
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == manifest['reference_sha256']
    for name, source in [('base', REPO / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'),
                         ('review', HERE / 'spx-camera-review.dts')]:
        pre = SCRATCH / f'{name}.preprocessed.dts'
        with pre.open('w') as stream:
            subprocess.run(['cpp', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
                            '-I', str(REPO / 'include'), '-I', str(REPO / 'arch/arm64/boot/dts/qcom'),
                            '-I', str(HERE), str(source)], stdout=stream, check=True)
        with (SCRATCH / f'{name}-dtc.log').open('w') as stream:
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(SCRATCH / f'{name}.dtb'),
                            str(pre)], stderr=stream, check=True)
    old = libfdt.Fdt(Path(manifest['reference_dtb']).read_bytes())
    new = libfdt.Fdt((SCRATCH / 'review.dtb').read_bytes())
    errors, intended, count, nodes = [], [], 0, 0
    status_paths = {manifest['included_roots'][0], manifest['included_roots'][1],
                    *manifest['excluded_supply_properties']}
    for root in manifest['included_roots']:
        before, after = subtree(old, root), subtree(new, root)
        if set(before) != set(after):
            errors.append({'root': root, 'missing_nodes': sorted(set(before) - set(after)),
                           'extra_nodes': sorted(set(after) - set(before))})
        for path in sorted(set(before) & set(after)):
            nodes += 1
            a, b = before[path], after[path]
            for prop in sorted(set(a) | set(b)):
                if prop in ('phandle', 'linux,phandle'):
                    continue
                if prop == 'status' and path in status_paths:
                    assert b.get(prop) == b'disabled\0', path
                    intended.append({'path': path, 'property': prop, 'change': 'disabled'})
                    continue
                if prop in manifest['excluded_supply_properties'].get(path, []):
                    assert prop in a and prop not in b, (path, prop)
                    intended.append({'path': path, 'property': prop, 'change': 'unresolved supply omitted'})
                    continue
                if prop not in a or prop not in b:
                    errors.append({'path': path, 'property': prop, 'before_present': prop in a,
                                   'after_present': prop in b})
                    continue
                count += 1
                av, bv = normalized(old, prop, a[prop]), normalized(new, prop, b[prop])
                if av != bv:
                    errors.append({'path': path, 'property': prop, 'before': av, 'after': bv})
    base_warnings = (SCRATCH / 'base-dtc.log').read_bytes()
    review_warnings = (SCRATCH / 'review-dtc.log').read_bytes()
    assert base_warnings == review_warnings, 'review added or changed DTC warnings'
    # Namespace checks are independent of numeric DTB equivalence.
    from extract_v23 import header_numbers
    clock_ids = header_numbers('clock/qcom,sc8180x-camcc.h', 'clocks', 'CAM_CC_')
    assert clock_ids[8] == 'CAM_CC_CCI_0_CLK'
    assert header_numbers('clock/qcom,sc8180x-camcc.h', 'resets')[8] == 'CAM_CC_FD_BCR'
    assert header_numbers('clock/qcom,sc8180x-camcc.h', 'power-domains')[7] == 'TITAN_TOP_GDSC'
    report = {'result': 'pass' if not errors else 'fail', 'reference_sha256': manifest['reference_sha256'],
              'review_dtb_sha256': hashlib.sha256((SCRATCH / 'review.dtb').read_bytes()).hexdigest(),
              'nodes_compared': nodes, 'properties_equal': count, 'intentional_changes': intended,
              'unexpected_differences': errors, 'dtc_warning_log_matches_base': True,
              'clock_reset_domain_namespaces_checked': True, 'scratch': str(SCRATCH)}
    (HERE / 'topology-review.json').write_text(json.dumps(report, indent=2) + '\n')
    for name in ('base-dtc.log', 'review-dtc.log', 'reference-v23-dtc.log'):
        (HERE / name).write_bytes((SCRATCH / name).read_bytes())
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
