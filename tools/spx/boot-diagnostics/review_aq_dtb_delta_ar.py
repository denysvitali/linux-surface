#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify the single touch timing property against AQ's frozen DTB."""
import hashlib
import json
import libfdt


def flatten(raw):
    fdt = libfdt.Fdt(raw)
    result = {}
    offset, depth = 0, 0
    while offset >= 0 and depth >= 0:
        path = fdt.get_path(offset)
        properties = {}
        p = fdt.first_property_offset(offset, quiet=(libfdt.NOTFOUND,))
        while p >= 0:
            value = fdt.get_property_by_offset(p)
            properties[value.name] = bytes(value).hex()
            p = fdt.next_property_offset(p, quiet=(libfdt.NOTFOUND,))
        result[path] = properties
        offset, depth = fdt.next_node(offset, depth, quiet=(libfdt.NOTFOUND,))
    return result


def compare(before_raw, after_raw):
    before = flatten(before_raw)
    after = flatten(after_raw)
    assert set(before) == set(after), 'Node delta exceeds touch timing property'
    delta = []
    for path in before:
        for name in set(before[path]) | set(after[path]):
            left, right = before[path].get(name), after[path].get(name)
            if left != right:
                delta.append({'path': path, 'property': name, 'before': left, 'after': right})
    assert delta == [{'path': '/ts-5p0-regulator', 'property': 'startup-delay-us',
                      'before': None, 'after': (300000).to_bytes(4, 'big').hex()}], delta
    old, new = libfdt.Fdt(before_raw), libfdt.Fdt(after_raw)
    assert old.num_mem_rsv() == new.num_mem_rsv()
    assert all(old.get_mem_rsv(n) == new.get_mem_rsv(n) for n in range(old.num_mem_rsv()))
    return {'delta': delta, 'all_other_nodes_properties_exact_aq': True,
            'memory_reservations_exact_aq': True,
            'before_sha256': hashlib.sha256(before_raw).hexdigest(),
            'after_sha256': hashlib.sha256(after_raw).hexdigest()}


def verify_base(parent, stage):
    dtb = 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    report = compare((parent / 'build' / dtb).read_bytes(), (stage / dtb).read_bytes())
    (stage / 'base-touch-delta-review.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
