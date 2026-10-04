#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive distinct BE runtime from sealed BD with exact BC executable identity."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bd/preparation/runtime-plan')
NAMES = ('bd_boot_guard.py', 'bd-video.py', 'bd-return.py', 'bd-baseline.py',
         'bd-camera-provider.py', 'bd-camera-control.py', 'bd_camera_core.py',
         'review-bd-baseline.py', 'bd-media.py', 'bd-media-run.py',
         'bd-reboot-check.py', 'bd_startup_review.py', 'review-bd-result.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=SRC)
    out = parser.parse_args().out
    if out != SRC:
        out.mkdir(mode=0o700)
    manifest = json.loads((PARENT / 'sha256.json').read_text())
    assert hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest() == \
        '2d07decf54cf92ddee25cd020b3d922f5aaac0db5abcda1ce66a1400611d6842'
    outputs, changes = {}, {}
    for name in NAMES:
        origin = PARENT / name
        assert hashlib.sha256(origin.read_bytes()).hexdigest() == manifest[name]
        text = origin.read_text().replace('20261004bd', '20261004be').replace(
            '78d60cce-ef40-4cea-93e1-42727db4a851', '433a78d6-9748-422f-a1a7-aac43c784a7d')
        text = re.sub(r'\bbd(?=[-_.])', 'be', text).replace('BD', 'BE')
        target = re.sub(r'\bbd(?=[-_.])', 'be', name)
        if target == 'be_boot_guard.py':
            text = text.replace('exactly_one_dt_property_changed', 'exactly_one_reserved_memory_node_changed')
            text = text.replace('exactly_one_raw_and_boot_property_delta', 'exactly_one_raw_and_boot_reserved_node_delta')
        if target == 'be-video.py':
            marker = "    capture('iomem', ['cat', '/proc/iomem'])\n"
            assert text.count(marker) == 1
            text = text.replace(marker, marker +
                "    capture('memblock-memory', ['cat', '/sys/kernel/debug/memblock/memory'])\n"
                "    capture('memblock-reserved', ['cat', '/sys/kernel/debug/memblock/reserved'])\n")
        if target == 'be_startup_review.py':
            text = text.replace('LOW, HIGH, SIZE, ALIGN = ', 'BASE = 0x8d300000\nLOW, HIGH, SIZE, ALIGN = ')
            start = text.index('    found = re.findall(')
            end = text.index("    queries = decoded['area_queries']", start)
            text = text[:start] + '''    lines = [line for line in kernel.splitlines()
             if 'OF: reserved mem:' in line and 'video-firmware' in line and 'nomap non-reusable' in line]
    assert len(lines) <= 1
    reservation = None
    if lines:
        found = re.search(r'OF: reserved mem: 0x([0-9a-f]+)\\.\\.0x([0-9a-f]+) '
                          r'\\(5120 KiB\\) nomap non-reusable video-firmware@8d300000$', lines[0])
        assert found, 'Unexpected static video reservation log'
        base, last = (int(word, 16) for word in found.groups())
        assert base == BASE and last + 1 == BASE + SIZE
        assert base % ALIGN == 0 and LOW <= base and last < HIGH
        reservation = dict(base=hex(base), inclusive_end=hex(last), bytes=SIZE)
''' + text[end:]
            text = text.replace('allocation_within_measured_aperture=bool(reservation),',
                'allocation_within_measured_aperture=bool(reservation), static_reservation_matches_be=bool(reservation),')
            text = text.replace('    memory_zero = any(', '    if memory:\n        assert init_zero, \'Memory setup observed after unsuccessful initialization\'\n    memory_zero = any(')
            text += '''

def intervals(text):
    rows = []
    for line in text.splitlines():
        match = re.fullmatch(r'\\s*(\\d+): 0x([0-9a-f]+)\\.\\.0x([0-9a-f]+)\\s+(\\d+) (.+)', line)
        assert match, line
        rows.append(dict(index=int(match[1]), start=int(match[2], 16),
                         end=int(match[3], 16)+1, node=int(match[4]), flags=match[5]))
    assert rows
    assert all(row['start'] < row['end'] for row in rows)
    assert all(left['end'] <= right['start'] for left, right in zip(rows, rows[1:]))
    return rows


def memory_maps(memory, reserved):
    rows = intervals(memory)
    reservations = intervals(reserved)
    cursor = LOW
    overlaps = []
    for row in rows:
        start, end = max(LOW, row['start']), min(HIGH, row['end'])
        if start >= end:
            continue
        assert start == cursor and 'NOMAP' in row['flags'].split(), 'Firmware pool mapping changed'
        cursor = end
        overlaps.append(row)
    assert cursor == HIGH
    assert not any(row['start'] < BASE + SIZE and row['end'] > BASE for row in reservations), 'Reserved range overlaps static video slot'
    return dict(measured_aperture_nomap_retained=True, static_video_range_nomap=True,
                video_overlaps_memblock_reserved=False, aperture_memory_regions=overlaps)
'''
        if target == 'review-be-result.py':
            text = text.replace('from be_startup_review import analyze', 'from be_startup_review import analyze, memory_maps')
            start = text.index("    offset = tree.path_offset('/reserved-memory/video-firmware')")
            end = text.index("    contract_path =", start)
            text = text[:start] + '''    offset = tree.path_offset('/reserved-memory/video-firmware@8d300000')
    assert bytes(tree.getprop(offset, 'reg')) == struct.pack('>4I', 0, 0x8d300000, 0, 0x500000)
    assert bytes(tree.getprop(offset, 'no-map')) == b''
    for name in ('size', 'alignment', 'alloc-ranges', 'reusable'):
        try:
            tree.getprop(offset, name)
        except libfdt.FdtException as exc:
            assert exc.err == -libfdt.NOTFOUND
        else:
            raise AssertionError('Unexpected static reservation property: ' + name)
''' + text[end:]
            marker = '    spec.loader.exec_module(contract)\n'
            assert text.count(marker) == 1
            text = text.replace(marker, marker +
                "    assert contract.EXPECTED['memory-region'] == [('/reserved-memory/video-firmware', [])]\n"
                "    contract.EXPECTED['memory-region'] = [('/reserved-memory/video-firmware@8d300000', [])]\n")
            marker = '    report = analyze(result, kernel, decoded)\n'
            assert text.count(marker) == 1
            text = text.replace(marker, marker + '''    for label in ('memblock-memory', 'memblock-reserved'):
        commands = [row for row in result['commands'] if row['label'] == label]
        expected = ['cat', '/sys/kernel/debug/memblock/' + label.removeprefix('memblock-')]
        assert len(commands) == 1 and commands[0]['argv'] == expected and commands[0]['exit_code'] == 0
    report.update(memory_maps((X / 'video-startup/memblock-memory.stdout').read_text(),
                              (X / 'video-startup/memblock-reserved.stdout').read_text()))
''')
            marker = "        bid = result['boot_id']\n"
            assert text.count(marker) == 1
            text = text.replace(marker, marker + "        if phase == 'startup':\n            assert bid == current, 'Startup record is from a different boot'\n")
        ast.parse(text)
        assert not (out / target).exists(), target
        outputs[target] = text
        changes[target] = dict(parent_name=name, parent_sha256=manifest[name],
            exact_except_identity=target not in ('be_boot_guard.py', 'be-video.py', 'be_startup_review.py', 'review-be-result.py'))
    for name, text in outputs.items():
        with (out / name).open('x') as stream:
            stream.write(text)
        changes[name]['sha256'] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    print(json.dumps(dict(helpers=len(outputs), release='7.3.0-rc2-spx-mainline-20261004bc+',
        expected_kernel_image='BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz', changes=changes,
        parent_runtime_manifest_sha256=hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest(),
        installed=False, boot_selected=False), indent=2))


if __name__ == '__main__':
    main()
