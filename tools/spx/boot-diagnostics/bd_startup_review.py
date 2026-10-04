#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Interpret observed BD allocation/PAS outcomes without requiring the old failure."""
import re

LOW, HIGH, SIZE, ALIGN = 0x8b700000, 0x9ab00000, 0x500000, 0x100000
RELEASE = '7.3.0-rc2-spx-mainline-20261004bc+'


def analyze(startup, kernel, decoded):
    assert startup['attempt'] == '20261004bd' and startup['release'] == RELEASE
    assert startup['kernel_taint'] == '0'
    assert startup['pas_parameters'] == {key: dict(value='Y', mode='0o400')
        for key in ('spx_pas_diag', 'spx_pas_area_diag')}
    found = re.findall(r'OF: reserved mem: 0x([0-9a-f]+)\.\.0x([0-9a-f]+) '
        r'\(5120 KiB\) nomap non-reusable video-firmware', kernel)
    assert len(found) <= 1
    reservation = None
    if found:
        base, last = (int(word, 16) for word in found[0])
        assert last + 1 - base == SIZE and base % ALIGN == 0
        assert LOW <= base and last < HIGH, 'Reservation outside the measured PIL aperture'
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
    memory_zero = any(call['caller_return'] == 0 for call in memory)
    devices = startup['platform_devices']
    bound = any(row['driver'] and row['driver'].endswith('/qcom-venus') for row in devices)
    names = {row['name'] for row in startup['video_nodes']}
    both_nodes = {'qcom-venus-decoder', 'qcom-venus-encoder'} <= names
    if bound or both_nodes:
        assert init_zero and memory_zero and reservation is not None
    probe_errors = re.findall(r'qcom-venus aa00000.video-codec: '
        r'probe with driver qcom-venus failed with error (-?[0-9]+)', kernel)
    return dict(firmware_reservation=reservation, allocation_within_measured_aperture=bool(reservation),
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
