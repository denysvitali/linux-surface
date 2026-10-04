#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Decode bounded PAS9 diagnostics; reject ambiguous traces and retain raw evidence."""
import argparse
import json
from pathlib import Path
import re

HEX = r'0x[0-9a-fA-F]+'


def int32(value):
    value &= 0xffffffff
    return value - 0x100000000 if value & 0x80000000 else value


def remap(value):
    # qcom_scm_remap_error(int), pinned by the verification capsule.
    return {-1: -5, -2: -22, -3: -22, -4: -95, -5: -12, -12: -16}.get(int32(value), -22)


def parse(text):
    lines = [line for line in text.splitlines() if 'SPX PAS diag ' in line]
    assert len(lines) <= 32, 'Diagnostic budget exceeded'
    records, current = [], None
    counts = {'init-image': 0, 'mem-setup': 0, 'smc': 0}
    for line in lines:
        assert line.count('SPX PAS diag ') == 1
        payload = line.split('SPX PAS diag ', 1)[1].strip()
        begin = re.fullmatch(r'(init-image|mem-setup) begin pas=([0-9]+) (.+)', payload)
        if begin:
            assert current is None, 'Overlapping caller messages cannot be correlated'
            kind, pas, rest = begin.groups()
            assert int(pas) == 9
            counts[kind] += 1
            assert counts[kind] <= 4
            current = dict(kind=kind, pas_id=9, raw_lines=[line])
            if kind == 'init-image':
                match = re.fullmatch('metadata=(' + HEX + ')', rest)
                assert match
                current['metadata_address'] = int(match[1], 16)
            else:
                match = re.fullmatch('addr=(' + HEX + ') size=(' + HEX + ')', rest)
                assert match
                current['memory_address'], current['memory_size'] = (int(value, 16) for value in match.groups())
            continue
        assert current is not None, 'Orphan diagnostic message'
        current['raw_lines'].append(line)
        kind = current['kind']
        match = re.fullmatch(r'(init-image|mem-setup) (clock|bandwidth) ret=(-?[0-9]+)', payload)
        if match:
            assert match[1] == kind and 'smc_begin' not in current
            assert int(match[3]) != 0
            current.update(failure_origin=match[2], caller_return=int(match[3]), complete=True)
            records.append(current)
            current = None
            continue
        match = re.fullmatch('smc begin id=(' + HEX + r') convention=([0-9]+) arginfo=(' + HEX +
                             ') args=(' + HEX + ')/(' + HEX + ')/(' + HEX + ')', payload)
        if match:
            assert 'smc_begin' not in current
            counts['smc'] += 1
            assert counts['smc'] <= 8
            call_id, convention, arginfo, *args = match.groups()
            call_id, convention, arginfo = int(call_id, 16), int(convention), int(arginfo, 16)
            args = [int(value, 16) for value in args]
            assert convention in (2, 3) and args[0] == 9
            expected_id = (0x02000200 if convention == 2 else 0x42000200) + (1 if kind == 'init-image' else 2)
            assert call_id == expected_id
            assert arginfo == (0x82 if kind == 'init-image' else 3)
            expected_args = ([9, current['metadata_address'], 0] if kind == 'init-image'
                             else [9, current['memory_address'], current['memory_size']])
            assert args == expected_args
            current['smc_begin'] = dict(call_id=call_id, convention=convention, arginfo=arginfo, arguments=args)
            continue
        match = re.fullmatch('smc done id=(' + HEX + r') ret=(-?[0-9]+) raw_valid=([01])(.*)', payload)
        if match:
            assert 'smc_begin' in current and 'smc_done' not in current
            assert int(match[1], 16) == current['smc_begin']['call_id']
            ret, valid = int(match[2]), bool(int(match[3]))
            assert valid == (ret == 0)
            raw = None
            if valid:
                values = re.fullmatch(' a0=(' + HEX + ') a1=(' + HEX + ') a2=(' + HEX + ') a3=(' + HEX + ')', match[4])
                assert values
                raw = [int(value, 16) for value in values.groups()]
                assert all(0 <= value <= 0xffffffffffffffff for value in raw)
            else:
                assert not match[4]
            current['smc_done'] = dict(leaf_return=ret, raw_valid=valid, raw_registers=raw)
            continue
        match = re.fullmatch(r'(init-image|mem-setup) transport ret=(-?[0-9]+) service_valid=([01]) service=(' + HEX + ')', payload)
        assert match and match[1] == kind, 'Unknown or mismatched diagnostic message'
        ret, valid, service = int(match[2]), bool(int(match[3])), int(match[4], 16)
        assert valid == (ret == 0) and (valid or service == 0)
        current['caller_transport'] = dict(return_value=ret, service_valid=valid,
                                            service_raw=service if valid else None)
        origin = None
        if 'smc_begin' in current:
            assert 'smc_done' in current, 'Missing raw SMC result'
            result = current['smc_done']
            if not result['raw_valid']:
                assert ret == result['leaf_return']
                origin = 'smc-leaf-transport'
            else:
                raw = result['raw_registers']
                assert ret == (remap(raw[0]) if raw[0] else 0)
                if raw[0]:
                    origin = 'scm-a0-remap'
                else:
                    assert service == raw[1]
                    origin = 'secure-service-a1' if int32(service) else None
        else:
            # Legacy ABI, unknown convention or the SMC logging budget may
            # suppress low-level records. Keep the caller evidence unresolved.
            origin = 'caller-transport-unresolved' if ret else ('secure-service' if int32(service) else None)
        current.update(failure_origin=origin, caller_return=ret if ret else int32(service),
                       complete=True, raw_smc_observed='smc_done' in current)
        records.append(current)
        current = None
    assert current is None, 'Incomplete diagnostic call'
    return dict(diagnostic_lines=len(lines), calls=records, counts=counts,
                diagnostic_calls_observed=bool(records), hardware_acceptance_closed=False,
                limits=['Sequential correlation only; overlapping or incomplete traces are rejected.',
                        'No diagnostic lines do not prove PAS success.',
                        'Returned PAS status does not establish authentication, HFI or media operation.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    print(json.dumps(parse(args.log.read_text()), indent=2))


if __name__ == '__main__':
    main()
