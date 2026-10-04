#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Interpret observed BF allocation/PAS outcomes without requiring the old failure."""
import re
from bf_venus_startup import parse as parse_venus

BASE = 0x8d300000
LOW, HIGH, SIZE, ALIGN = 0x8b700000, 0x9ab00000, 0x500000, 0x100000
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'


def analyze(startup, kernel, decoded):
    assert startup['attempt'] == '20261004bf' and startup['release'] == RELEASE
    assert startup['kernel_taint'] == '0'
    assert startup['pas_parameters'] == {key: dict(value='Y', mode='0o400')
        for key in ('spx_pas_diag', 'spx_pas_area_diag')}
    lines = [line for line in kernel.splitlines()
             if 'OF: reserved mem:' in line and 'video-firmware' in line and 'nomap non-reusable' in line]
    assert len(lines) <= 1
    reservation = None
    if lines:
        found = re.search(r'OF: reserved mem: 0x([0-9a-f]+)\.\.0x([0-9a-f]+) '
                          r'\(5120 KiB\) nomap non-reusable video-firmware@8d300000$', lines[0])
        assert found, 'Unexpected static video reservation log'
        base, last = (int(word, 16) for word in found.groups())
        assert base == BASE and last + 1 == BASE + SIZE
        assert base % ALIGN == 0 and LOW <= base and last < HIGH
        reservation = dict(base=hex(base), inclusive_end=hex(last), bytes=SIZE)
    queries = decoded['area_queries']
    assert len(queries) <= 1
    query = queries[0] if queries else None
    query_matches = bool(query and query['transport_return'] == 0 and query['result_valid'] and
                         query['result_words'][:2] == [LOW, HIGH])
    if query:
        assert query['request'] == dict(service=2, command=9, arginfo=1, spare=0)
        assert query['complete']
    calls = decoded['pas']['calls']
    init, memory = [], []
    for call in calls:
        assert call['pas_id'] == 9 and call['complete']
        if call['kind'] == 'init-image':
            init.append(call)
        else:
            assert call['kind'] == 'mem-setup' and reservation is not None
            assert call['memory_address'] == int(reservation['base'], 16)
            assert call['memory_size'] == SIZE
            memory.append(call)
    init_zero = any(call['caller_return'] == 0 for call in init)
    if memory:
        assert init_zero, 'Memory setup observed after unsuccessful initialization'
    memory_zero = any(call['caller_return'] == 0 for call in memory)
    venus = parse_venus(kernel)
    parameter = startup['venus_startup_parameter']
    assert isinstance(parameter, dict) and isinstance(parameter.get('observed'), bool)
    if parameter['observed']:
        assert parameter == dict(observed=True, value='Y', mode='0o400')
    else:
        assert parameter.get('error') and not venus['records']
    venus['parameter_witness'] = parameter
    devices = startup['platform_devices']
    bound = any(row['driver'] and row['driver'].endswith('/qcom-venus') for row in devices)
    names = {row['name'] for row in startup['video_nodes']}
    both_nodes = {'qcom-venus-decoder', 'qcom-venus-encoder'} <= names
    if bound or both_nodes:
        assert init_zero and memory_zero and reservation is not None
    probe_errors = re.findall(r'qcom-venus aa00000.video-codec: '
        r'probe with driver qcom-venus failed with error (-?[0-9]+)', kernel)
    return dict(venus_startup=venus, firmware_reservation=reservation, allocation_within_measured_aperture=bool(reservation), static_reservation_matches_be=bool(reservation),
        pil_area_query_observed=bool(query), pil_area_query_matches_bc=query_matches,
        pil_area_query_transport_return=query['transport_return'] if query else None,
        pil_area_query_result_words=query['result_words'] if query else None,
        pas_init_returns=[call['caller_return'] for call in init],
        pas_memory_returns=[call['caller_return'] for call in memory],
        pas_memory_failures=[dict(origin=call['failure_origin'], return_value=call['caller_return'],
                                 smc_done=call.get('smc_done')) for call in memory if call['caller_return']],
        pas_initialization_zero_observed=init_zero, pas_memory_setup_zero_observed=memory_zero,
        normal_venus_driver_bound=bound, decoder_encoder_nodes_observed=both_nodes,
        hfi_initialization_inferred_from_completed_probe=bound and both_nodes,
        probe_errnos=[int(word) for word in probe_errors],
        media_acceptance_passed=False, hardware_acceptance_closed=False,
        limits=['Zero PAS returns are scoped observations; they do not prove media functionality.',
                'HFI initialization is inferred from the frozen normal probe ordering only when both nodes bind.',
                'No decoder/encoder reference workload or sustained media result is inferred from enumeration.'])


def intervals(text):
    rows = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(\d+): 0x([0-9a-f]+)\.\.0x([0-9a-f]+)\s+(\d+) (.+)', line)
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
