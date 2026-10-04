#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve BD's actual NOMAP aperture and explain its normal allocator exclusion."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

import libfdt

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g

LOW, HIGH = 0x8b700000, 0x9ab00000
BOOT = 'fcfdc410-495e-46fb-876a-f78bffaed21e'


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def intervals(text):
    rows = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(\d+): 0x([0-9a-f]+)\.\.0x([0-9a-f]+)\s+(\d+) (.+)', line)
        assert match, line
        rows.append(dict(index=int(match[1]), start=int(match[2], 16),
                         end=int(match[3], 16)+1, node=int(match[4]), flags=match[5]))
    return rows


def clipped(rows):
    return [row | dict(start=max(row['start'], LOW), end=min(row['end'], HIGH))
            for row in rows if row['start'] < HIGH and row['end'] > LOW]


def children(tree, parent):
    try:
        child = tree.first_subnode(parent)
        while True:
            yield child
            child = tree.next_subnode(child)
    except libfdt.FdtException as exc:
        assert exc.err == -libfdt.NOTFOUND


def main():
    os.umask(0o077)
    a = g.load()
    assert g.trial_identity(a) == BOOT
    out = g.X / 'actual-memory-aperture'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    captures = {'memblock-memory': Path('/sys/kernel/debug/memblock/memory'),
                'memblock-reserved': Path('/sys/kernel/debug/memblock/reserved'),
                'iomem': Path('/proc/iomem'), 'cmdline': Path('/proc/cmdline'),
                'taint': Path('/proc/sys/kernel/tainted'), 'uptime': Path('/proc/uptime')}
    for name, source in captures.items():
        (out / name).write_bytes(source.read_bytes())
    (out / 'kernel.log').write_bytes(subprocess.check_output(
        ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], timeout=60))
    shutil.copy2('/sys/firmware/fdt', out / 'actual-fdt.dtb')
    memory = intervals((out / 'memblock-memory').read_text())
    reserved = intervals((out / 'memblock-reserved').read_text())
    aperture = clipped(memory)
    assert aperture == [dict(index=8, start=LOW, end=HIGH, node=0, flags='NOMAP')]
    assert clipped(reserved) == []
    assert (out / 'taint').read_text().strip() == '0'
    log = (out / 'kernel.log').read_text()
    assert "failed to allocate memory for node 'video-firmware': size 5 MiB" in log
    assert 'SPX PAS diag init-image begin' not in log and 'SPX PAS area query begin' not in log
    assert 'failed to lookup reserved memory-region' in log
    sources = ('mm/memblock.c', 'drivers/of/of_reserved_mem.c', 'drivers/firmware/efi/efi-init.c',
               'include/linux/memblock.h', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts')
    rows = json.loads((g.X / 'dtb-build/candidate-source-files.json').read_text())
    for name in sources:
        assert g.sha(g.REPO / name) == rows[name]['sha256'], name
        shutil.copy2(g.REPO / name, out / Path(name).name)
    memblock = (out / 'memblock.c').read_text()
    assert 'if (!(flags & MEMBLOCK_NOMAP) && memblock_is_nomap(m))' in memblock
    assert 'return true;' in memblock.split('if (!(flags & MEMBLOCK_NOMAP) && memblock_is_nomap(m))', 1)[1].split('\n\n', 1)[0]
    allocation = memblock.split('phys_addr_t __init memblock_phys_alloc_range', 1)[1].split('\n}', 1)[0]
    assert 'return memblock_alloc_range_nid(size, align, start, end, NUMA_NO_NODE,' in allocation
    selection = memblock.split('static enum memblock_flags __init_memblock choose_memblock_flags(void)', 1)[1].split('\n}', 1)[0]
    assert 'MEMBLOCK_NOMAP' not in selection
    assert 'MEMBLOCK_NONE' in selection
    bounded = memblock.split('phys_addr_t __init memblock_alloc_range_nid', 1)[1].split('\n}', 1)[0]
    assert 'enum memblock_flags flags = choose_memblock_flags();' in bounded
    assert 'base = memblock_phys_alloc_range(size, align, start, end);' in (out / 'of_reserved_mem.c').read_text()
    fdt = libfdt.Fdt((out / 'actual-fdt.dtb').read_bytes())
    root = fdt.path_offset('/reserved-memory')
    regions = []
    for child in children(fdt, root):
        try:
            raw = bytes(fdt.getprop(child, 'reg'))
        except libfdt.FdtException:
            continue
        assert len(raw) % 16 == 0
        for at in range(0, len(raw), 16):
            start, size = struct.unpack('>2Q', raw[at:at+16])
            regions.append(dict(node=fdt.get_name(child), start=start, end=start+size, bytes=size))
    overlaps = clipped(regions)
    write(out / 'parsed-memblock-memory.json', memory)
    write(out / 'parsed-memblock-reserved.json', reserved)
    write(out / 'explicit-dt-reservations.json', regions)
    write(out / 'dt-reservations-in-aperture.json', overlaps)
    efi = subprocess.run(['ls', '/sys/firmware/efi/memmap', '/sys/kernel/debug/efi'],
                         capture_output=True, timeout=30)
    (out / 'efi-map-export.stdout').write_bytes(efi.stdout)
    (out / 'efi-map-export.stderr').write_bytes(efi.stderr)
    # Absence of exported EFI descriptors does not identify their original type.
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT, release=a['release'],
        uptime_seconds=float((out / 'uptime').read_text().split()[0]),
        measured_pil_range=dict(start=hex(LOW), exclusive_end=hex(HIGH), bytes=HIGH-LOW),
        observed_memory_flags_in_aperture='NOMAP', ordinary_allocatable_aperture_bytes=0,
        memblock_reserved_intersections=0, explicit_dt_reservations_in_aperture=len(overlaps),
        bounded_dynamic_allocation_failed=True, pas_calls_not_reached=True,
        source_allocator_skips_nomap_verified=True, ordinary_memory_release_not_performed=True,
        original_efi_descriptor_types_observed=False, efi_descriptor_export_exit=efi.returncode,
        firmware_pool_owner_of_each_gap_established=False, suitable_video_physical_region_established=False,
        hardware_operations='read-only captures', hardware_acceptance_closed=False,
        limits=['The entire queried range is already NOMAP; the normal allocator flags do not request NOMAP memory.',
                'No NOMAP range was cleared or read through a physical-memory interface.',
                'Subtracting DT reservations does not prove remaining gaps are unowned.',
                'Camera and QSM labels in historical board comments are retained, not accepted as complete ownership proof.'])
    write(out / 'report.json', report)
    write(out / 'sha256.json', g.files(out))
    assert g.files(out) == json.loads((out / 'sha256.json').read_text()) | {'sha256.json': g.sha(out / 'sha256.json')}
    assert g.trial_identity(a) == BOOT
    os.sync()
    print(json.dumps(report | dict(manifest_sha256=g.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
