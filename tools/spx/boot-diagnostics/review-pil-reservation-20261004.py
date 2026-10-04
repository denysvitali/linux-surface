#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Select an experimental static Venus slot from recorded PGCM exclusions."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    a = g.load()
    assert a['state'].startswith('BD terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['returned_boot_id']
    assert not g.recovery(a).get('next_entry', '')
    out = g.X / 'offline-pil-reservation-policy'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    capsules = {
        'actual-memory-aperture': 'bdef166c9bc560eaa30a8eef390d81df9d5b7770f8e362752653c392beeab0fc',
        'offline-pil-pool-owners': '0502ec49050cdfa9aa3e170f34d1a2f8152aaacb70848a3b72243eb2efb97776',
        'offline-pil-pgcm': '189bf7f17c2220a9dde2a186380501949e50ee47f67f97575fe5c7774dd0c57d',
    }
    for name, digest in capsules.items():
        folder = g.X / name
        assert g.sha(folder / 'sha256.json') == digest
        assert g.files(folder) == json.loads((folder / 'sha256.json').read_text()) | {'sha256.json': digest}
        shutil.copy2(folder / 'report.json', out / (name + '-report.json'))
    retained = Path('/home/dvitali/Documents/drivers/FileRepository')
    records, inputs = [], {}
    for path in sorted(retained.glob('*/*.inf')):
        raw = path.read_bytes()
        inputs[str(path.relative_to(retained))] = g.sha(path)
        try:
            text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8-sig')
        except UnicodeError:
            continue
        section, rows = None, []
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(r'^\[[^]]+\]', line):
                section = line.strip()
            if 'HKR' in line.upper() and any(word.lower() in line.lower() for word in
                    ('PGCM', 'MemoryAddress', 'MemoryReservation', 'DoNotReturnMemoryToHLOS')):
                rows.append(dict(line=number, section=section, value=line))
        if rows:
            shutil.copy2(path, out / path.name)
            (out / (path.name + '.decoded.txt')).write_text(text)
            records.append(dict(path=str(path), sha256=g.sha(path), rows=rows))
    assert len(records) == 6
    pilext = (out / 'surfaceprox_pilext.inf.decoded.txt').read_text()
    assert re.search(r'HKR\s*,SubsystemLoad\\VENUS,MemoryReservation,%REG_DWORD%,0x00500000', pilext)
    assert re.search(r'HKR\s*,SubsystemLoad\\VENUS,MemoryAlignment,%REG_DWORD%,0\s*$', pilext, re.M)
    (out / 'retained-inf-inventory.json').write_text(json.dumps(inputs, indent=2) + '\n')
    (out / 'retained-physical-requests.json').write_text(json.dumps(records, indent=2) + '\n')
    owners = json.loads((g.X / 'offline-pil-pool-owners/report.json').read_text())
    pool = owners['declared_pgcm']
    lower, upper = int(pool['base'], 16), int(pool['exclusive_end'], 16)
    dt = json.loads((g.X / 'actual-memory-aperture/explicit-dt-reservations.json').read_text())
    exclusions = [dict(base=row['start'], end=row['end'], owner='DT:' + row['node']) for row in dt]
    exclusions += [dict(base=row['base'], end=row['exclusive_end'], owner='/'.join(row['scopes']))
                   for row in owners['resource_claims']]
    gaps, cursor = [], lower
    for row in sorted(exclusions, key=lambda row: (row['base'], row['end'])):
        start, end = max(lower, row['base']), min(upper, row['end'])
        if start >= end:
            continue
        if cursor < start:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < upper:
        gaps.append((cursor, upper))
    size, alignment = 0x500000, 0x100000
    choices = [(start, end, (end-size) & ~(alignment-1)) for start, end in gaps
               if ((end-size) & ~(alignment-1)) >= start]
    assert len(choices) == 1
    gap_start, gap_end, base = choices[0]
    assert (gap_start, gap_end, base) == (0x8bd80000, 0x8d800000, 0x8d300000)
    assert lower <= base < base+size <= upper
    assert not any(base < row['end'] and base+size > row['base'] for row in exclusions)
    nomap = json.loads((g.X / 'actual-memory-aperture/parsed-memblock-memory.json').read_text())
    assert any(row['start'] <= base and base+size <= row['end'] and row['flags'] == 'NOMAP' for row in nomap)
    board = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'
    old = '\t\tvenus_mem: video-firmware {\n\t\t\tsize = <0 0x500000>;\n\t\t\talignment = <0 0x100000>;\n\t\t\talloc-ranges = <0 0x8b700000 0 0x0f400000>;\n\t\t\tno-map;\n\t\t};'
    new = '\t\tvenus_mem: video-firmware@8d300000 {\n\t\t\treg = <0 0x8d300000 0 0x500000>;\n\t\t\tno-map;\n\t\t};'
    source = (g.REPO / board).read_text()
    assert source.count(old) == 1
    candidate = source.replace(old, new)
    (out / 'board-before.dts').write_text(source)
    (out / 'board-candidate.dts').write_text(candidate)
    rows = json.loads((g.X / 'dtb-build/candidate-source-files.json').read_text())
    for name in (board, 'drivers/of/of_reserved_mem.c', 'mm/memblock.c',
                 'drivers/media/platform/qcom/venus/firmware.c'):
        assert g.sha(g.REPO / name) == rows[name]['sha256'], name
        if name != board:
            shutil.copy2(g.REPO / name, out / Path(name).name)
    of = (out / 'of_reserved_mem.c').read_text()
    block = of.split('static int __init early_init_dt_reserve_memory', 1)[1].split('\n}', 1)[0]
    assert 'return memblock_mark_nomap(base, size);' in block
    assert 'memblock_clear_nomap' not in block and 'memblock_phys_alloc' not in block
    assert 'r->flags |= flag;' in (out / 'memblock.c').read_text()
    report = dict(utc=datetime.now(timezone.utc).isoformat(), prior_capsules=capsules,
        retained_inf_count=len(inputs), retained_memory_request_files=records,
        pgcm_bounds=pool, exclusions=exclusions, unclaimed_intervals=gaps,
        selection_rule='highest 1MiB-aligned 5MiB span in the sole sufficiently large interval after recorded exclusions',
        proposed_video=dict(base=hex(base), size=hex(size), end_exclusive=hex(base+size)),
        candidate_board_sha256=g.sha(out / 'board-candidate.dts'),
        overlaps_recorded_acpi_or_dt_owner=False, remains_nomap=True,
        nomap_made_ordinary_ram=False, generic_of_or_memblock_allocator_changed=False,
        remaining_prefix_bytes_after_video=base-gap_start,
        ipa_spss_actual_placement_validated=False,
        original_efi_descriptor_type_observed=False, current_windows_allocations_observed=False,
        actual_unrecorded_owner_absence_proven=False, pas_acceptance_observed=False,
        candidate_source_applied=False, hardware_acceptance_closed=False,
        next_action='Verify exact DT delta and provider contracts, fully archive a distinct DT-only trial, then observe actual reservation/PAS/HFI/media and regressions.',
        limits=['Placement is an experimental Linux board reservation, not an observed Windows Venus address.',
                'The recorded DT/ACPI owner exclusions are exact; absence of every unrecorded owner is not established.',
                'IPA/SPSS have nonzero retained requests but no fixed retained address; their Linux acceptance remains open.',
                'Existing ramoops overlaps the QSM claim by 512KiB; this separate historical issue is preserved.'])
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    assert g.files(out) == json.loads((out / 'sha256.json').read_text()) | {'sha256.json': g.sha(out / 'sha256.json')}
    os.sync()
    print(json.dumps(dict(candidate=report['proposed_video'], inf_count=len(inputs), manifest_sha256=g.sha(out / 'sha256.json'))))


if __name__ == '__main__':
    main()
