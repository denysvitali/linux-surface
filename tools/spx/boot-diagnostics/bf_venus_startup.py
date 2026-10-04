#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Parse bounded Venus observations; preserve missing values and raw API returns."""
import re

PREFIX = 'SPX Venus startup '
DEVICE = 'qcom-venus aa00000.video-codec: '
HEX = r'(?:0x)?[0-9a-f]+'
PATTERNS = {
    'auth-reset': re.compile(r'auth-reset pas=(\d+) ret=(-?\d+)$'),
    'remote-state': re.compile(r'remote-state resume=(\d+) ret=(-?\d+)$'),
    'buffers': re.compile(r'buffers queue=(' + HEX + r') queue_size=(\d+) uc_size=(\d+) '
                          r'sfr=(' + HEX + r') sfr_size=(\d+) tz=(\d+)$'),
    'poll': re.compile(r'poll ret=(-?\d+) count=(\d+) status=(' + HEX + r') '
                       r'mask=(' + HEX + r') hw=(' + HEX + r')$'),
}


def integer(word, bits, signed=False, hexadecimal=False):
    value = int(word, 16 if hexadecimal else 10)
    low = -(1 << (bits - 1)) if signed else 0
    high = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    assert low <= value <= high, 'Diagnostic value out of range'
    return value


def parse(kernel):
    records = []
    for line_number, line in enumerate(kernel.splitlines(), 1):
        if PREFIX not in line:
            continue
        assert DEVICE + PREFIX in line, 'Unexpected diagnostic device/prefix'
        body = line.split(DEVICE + PREFIX, 1)[1]
        matched = [(kind, regex.fullmatch(body)) for kind, regex in PATTERNS.items()]
        matched = [(kind, match) for kind, match in matched if match]
        assert len(matched) == 1, 'Malformed startup diagnostic'
        kind, match = matched[0]
        words = match.groups()
        row = dict(kind=kind, line_number=line_number, raw=line)
        if kind == 'auth-reset':
            row.update(pas=integer(words[0], 32), return_value=integer(words[1], 32, signed=True))
            assert row['pas'] == 9
        elif kind == 'remote-state':
            row.update(resume=integer(words[0], 32), return_value=integer(words[1], 32, signed=True))
            assert row['resume'] in (0, 1)
            row['resume_einval_fallback_applicable'] = bool(row['resume'] and row['return_value'] == -22)
        elif kind == 'buffers':
            row.update(queue_dma=integer(words[0], 64, hexadecimal=True), queue_bytes=integer(words[1], 32),
                       uc_bytes=integer(words[2], 32), sfr_dma=integer(words[3], 64, hexadecimal=True),
                       sfr_bytes=integer(words[4], 32), tz=integer(words[5], 32))
            assert row['uc_bytes'] == 3145728 and row['tz'] in (0, 1)
            row['queue_dma_within_declared_mask'] = row['queue_dma'] <= 0xbfffffff
            row['sfr_dma_within_declared_mask'] = row['sfr_dma'] <= 0xbfffffff
        else:
            row.update(return_value=integer(words[0], 32, signed=True), count=integer(words[1], 32),
                       status=integer(words[2], 32, hexadecimal=True), mask=integer(words[3], 32, hexadecimal=True),
                       hardware_version=integer(words[4], 32, hexadecimal=True))
            assert row['count'] <= 100 and not row['mask'] & 0x14
            # Exact frozen boot_core: count increments after a normal poll/sleep,
            # and the error-status branch exits before incrementing it.
            if row['status'] & 0xfe == 4:
                expected = -22
                assert row['count'] < 100
            elif row['count'] == 100:
                expected = -110
            else:
                expected = 0
                assert row['status'] != 0 and row['count'] > 0
            assert row['return_value'] == expected, 'Poll return/count/status contradict frozen control flow'
            row['late_nonzero_timeout'] = row['return_value'] == -110 and row['status'] != 0
        records.append(row)
    assert len(records) <= 32, 'Shared diagnostic cap exceeded'
    groups = {kind: [r for r in records if r['kind'] == kind] for kind in PATTERNS}
    return dict(records=records, line_count=len(records), at_shared_line_cap=len(records) == 32,
        auth_reset_api_observed=bool(groups['auth-reset']), auth_reset_api_returns=[r['return_value'] for r in groups['auth-reset']],
        remote_state_api_observations=groups['remote-state'], buffer_observations=groups['buffers'],
        poll_observations=groups['poll'], firmware_execution_observed=False,
        hfi_initialization_proved=False, media_acceptance_passed=False,
        limits=['Existing API returns and poll variables are observations, not raw auth SMC or firmware-execution proof.',
                'Missing stages remain unobserved, including records omitted after the shared cap.',
                'DMA values are recorded without imposing retained Windows UC placement or allocation policy.',
                'No HFI reply or codec workload is inferred from a zero API/poll return.'])
