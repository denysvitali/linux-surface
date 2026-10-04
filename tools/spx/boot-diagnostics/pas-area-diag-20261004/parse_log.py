#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Correlate a single PIL area query and the unchanged BB PAS diagnostics."""
import argparse
import json
from pathlib import Path
import re

from parse_pas import parse as parse_pas, remap

HEX = r'0x[0-9a-fA-F]+'


def parse(text):
    lines = [line for line in text.splitlines()
             if 'SPX PAS diag ' in line or 'SPX PAS area query ' in line]
    assert len(lines) <= 34, 'Diagnostic budget exceeded'
    pas_lines, queries, current = [], [], None
    caller_open, caller_smc = None, False
    smc_count = 0
    for line in lines:
        area = 'SPX PAS area query ' in line
        assert line.count('SPX PAS area query ' if area else 'SPX PAS diag ') == 1
        assert not (area and 'SPX PAS diag ' in line)
        payload = line.split('SPX PAS area query ' if area else 'SPX PAS diag ', 1)[1].strip()
        if area and payload == 'begin spare=0':
            assert current is None and not queries, 'Repeated area query'
            assert caller_open in (None, 'init-image') and not caller_smc
            current = dict(request=dict(service=2, command=9, arginfo=1, spare=0),
                           raw_lines=[line])
            continue
        if current is None:
            assert not area, 'Orphan area message'
            match = re.match(r'(init-image|mem-setup) begin ', payload)
            if match:
                assert caller_open is None
                caller_open, caller_smc = match[1], False
            elif payload.startswith('smc begin '):
                caller_smc = True
                smc_count += 1
            elif re.match(r'(init-image|mem-setup) (clock|bandwidth|transport) ', payload):
                caller_open, caller_smc = None, False
            pas_lines.append(line)
            continue
        current['raw_lines'].append(line)
        if not area:
            match = re.fullmatch('smc begin id=(' + HEX + r') convention=([0-9]+) arginfo=(' + HEX +
                                 ') args=(' + HEX + ')/(' + HEX + ')/(' + HEX + ')', payload)
            if match:
                assert 'smc_begin' not in current
                call_id, convention, arginfo, *args = match.groups()
                call_id, convention, arginfo = int(call_id, 16), int(convention), int(arginfo, 16)
                args = [int(value, 16) for value in args]
                assert convention in (2, 3)
                assert call_id == (0x02000209 if convention == 2 else 0x42000209)
                assert arginfo == 1 and args == [0, 0, 0]
                current['smc_begin'] = dict(call_id=call_id, convention=convention,
                                            arginfo=arginfo, arguments=args)
                smc_count += 1
                continue
            match = re.fullmatch('smc done id=(' + HEX + r') ret=(-?[0-9]+) raw_valid=([01])(.*)', payload)
            assert match and 'smc_begin' in current and 'smc_done' not in current, 'Uncorrelated query SMC'
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
        match = re.fullmatch(r'transport ret=(-?[0-9]+) result_valid=([01]) r0=(' + HEX +
                             ') r1=(' + HEX + ') r2=(' + HEX + ')', payload)
        assert match, 'Unknown area message'
        ret, valid = int(match[1]), bool(int(match[2]))
        results = [int(value, 16) for value in match.groups()[2:]]
        assert all(0 <= value <= 0xffffffffffffffff for value in results)
        assert valid == (ret == 0) and (valid or results == [0, 0, 0])
        origin = 'caller-transport-unresolved' if ret else None
        if 'smc_begin' in current:
            assert 'smc_done' in current, 'Missing query SMC result'
            result = current['smc_done']
            if not result['raw_valid']:
                assert ret == result['leaf_return']
                origin = 'smc-leaf-transport'
            else:
                raw = result['raw_registers']
                assert ret == (remap(raw[0]) if raw[0] else 0)
                if ret:
                    origin = 'scm-a0-remap'
                else:
                    assert results == raw[1:]
        current.update(transport_return=ret, result_valid=valid,
                       result_words=results if valid else None,
                       failure_origin=origin, raw_smc_observed='smc_done' in current,
                       interpretation='Uninterpreted raw result words; device range and layout unverified.',
                       complete=True)
        queries.append(current)
        current = None
    assert current is None, 'Incomplete area query'
    assert smc_count <= 8, 'Shared SMC budget exceeded'
    pas = parse_pas('\n'.join(pas_lines))
    return dict(diagnostic_lines=len(lines), pas=pas, area_queries=queries,
                shared_smc_records=smc_count, area_query_observed=bool(queries),
                memory_area_interpreted=False, hardware_acceptance_closed=False,
                limits=pas['limits'] + [
                    'One sequential area query; overlapping or incomplete records are rejected.',
                    'A completed query does not prove a suitable firmware allocation.',
                    'Raw result layout and completion status are not inferred.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    print(json.dumps(parse(args.log.read_text()), indent=2))


if __name__ == '__main__':
    main()
