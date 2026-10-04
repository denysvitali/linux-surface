#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check nested area-query evidence and replay the immutable BB parser fixtures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_log import parse
from parse_pas import parse as old_parse

SRC = Path(__file__).resolve().parent
BB = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bb')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    out = p.parse_args().output
    os.umask(0o077)
    out.mkdir(mode=0o700)
    fixtures = out / 'fixtures'
    fixtures.mkdir()
    for name in ('parse_log.py', 'parse_pas.py', 'verify_log.py'):
        shutil.copy2(SRC / name, out / name)
    assert (SRC / 'parse_pas.py').read_bytes() == \
        (BB / 'build/pas-log-review/parse_log.py').read_bytes()
    positive, negative, references = [], [], {}
    bb_fixtures = BB / 'build/pas-log-review/fixtures'
    replayed = 0
    for log in sorted(bb_fixtures.glob('*.log')):
        if log.name.startswith('invalid-'):
            continue
        data = log.read_text()
        observed = parse(data)
        assert observed['pas'] == old_parse(data)
        assert not observed['area_query_observed']
        shutil.copy2(log, fixtures / ('bb-' + log.name))
        (fixtures / ('bb-' + log.stem + '.json')).write_text(json.dumps(observed, indent=2) + '\n')
        replayed += 1
    assert replayed == 52
    for log in sorted(bb_fixtures.glob('invalid-*.log')):
        try:
            parse(log.read_text())
        except AssertionError:
            negative.append('bb-' + log.stem)
        else:
            raise AssertionError(log.name)
        shutil.copy2(log, fixtures / ('bb-' + log.name))

    def caller(kind, mode, raw_a0=0, include_smc=True):
        call_id = (0x02000200 if mode == 2 else 0x42000200) + (1 if kind == 'init-image' else 2)
        begin = (kind + ' begin pas=9 metadata=0x9b000000' if kind == 'init-image' else
                 kind + ' begin pas=9 addr=0xfe500000 size=0x500000')
        lines = ['SPX PAS diag ' + begin]
        if include_smc:
            args = '0x9/0x9b000000/0x0' if kind == 'init-image' else '0x9/0xfe500000/0x500000'
            lines += ['SPX PAS diag smc begin id=0x%x convention=%d arginfo=0x%x args=%s' %
                      (call_id, mode, 0x82 if kind == 'init-image' else 3, args),
                      'SPX PAS diag smc done id=0x%x ret=0 raw_valid=1 a0=0x%x a1=0x0 a2=0x0 a3=0x0' %
                      (call_id, raw_a0)]
        ret = -22 if raw_a0 else 0
        lines += ['SPX PAS diag ' + kind + ' transport ret=%d service_valid=%d service=0x0' % (ret, not ret)]
        return lines

    def area(mode, failure, include_smc=True):
        call_id = 0x02000209 if mode == 2 else 0x42000209
        leaf = -110 if failure == 'leaf' else 0
        raw_a0 = 0xffcfffba if failure == 'a0' else 0
        ret = leaf or (-22 if raw_a0 else 0)
        lines = ['SPX PAS area query begin spare=0']
        if include_smc:
            lines += ['SPX PAS diag smc begin id=0x%x convention=%d arginfo=0x1 args=0x0/0x0/0x0' % (call_id, mode)]
            done = 'SPX PAS diag smc done id=0x%x ret=%d raw_valid=%d' % (call_id, leaf, not leaf)
            if not leaf:
                done += ' a0=0x%x a1=0x80000000 a2=0x90000000 a3=0x123456789' % raw_a0
            lines.append(done)
        words = [0, 0, 0] if ret else [0x80000000, 0x90000000, 0x123456789]
        lines += ['SPX PAS area query transport ret=%d result_valid=%d r0=0x%x r1=0x%x r2=0x%x' %
                  (ret, not ret, *words)]
        return lines

    def check(name, lines, expected_ret, expected_origin):
        data = '\n'.join('qcom_scm firmware: ' + line for line in lines) + '\n'
        (fixtures / (name + '.log')).write_text(data)
        observed = parse(data)
        assert len(observed['area_queries']) == 1
        query = observed['area_queries'][0]
        assert query['transport_return'] == expected_ret
        assert query['failure_origin'] == expected_origin
        assert query['result_words'] == (None if expected_ret else [0x80000000, 0x90000000, 0x123456789])
        assert not observed['memory_area_interpreted'] and not observed['hardware_acceptance_closed']
        (fixtures / (name + '.json')).write_text(json.dumps(observed, indent=2) + '\n')
        positive.append(name)
        references[name] = data
        return observed

    for mode in (2, 3):
        for failure, ret, origin in (('ok', 0, None), ('leaf', -110, 'smc-leaf-transport'),
                                     ('a0', -22, 'scm-a0-remap')):
            for existing in (False, True):
                query = area(mode, failure)
                lines = query
                if existing:
                    init = caller('init-image', mode)
                    lines = init[:1] + query + init[1:] + caller('mem-setup', mode, 0xffcfffba)
                result = check('area-c%d-%s-existing%d' % (mode, failure, existing), lines, ret, origin)
                assert len(result['pas']['calls']) == (2 if existing else 0)
                if existing:
                    assert result['pas']['calls'][0]['caller_return'] == 0
                    assert result['pas']['calls'][1]['failure_origin'] == 'scm-a0-remap'
                    assert result['pas']['calls'][1]['caller_return'] == -22
        for failure, ret in (('ok', 0), ('leaf', -110)):
            check('area-c%d-no-smc-%s' % (mode, failure), area(mode, failure, False),
                  ret, 'caller-transport-unresolved' if ret else None)
    saturated = caller('init-image', 3)
    saturated = saturated[:1] + area(3, 'ok') + saturated[1:]
    for i in range(1, 8):
        saturated += caller('init-image' if i < 4 else 'mem-setup', 3, include_smc=i < 7)
    result = check('saturated-budget', saturated, 0, None)
    assert result['diagnostic_lines'] == 34 and result['shared_smc_records'] == 8
    assert result['pas']['counts'] == {'init-image': 4, 'mem-setup': 4, 'smc': 7}
    assert not parse('ordinary log\n')['area_query_observed']
    reference = references['area-c3-ok-existing1']
    mutations = {
        'wrong-spare-begin': reference.replace('spare=0', 'spare=9'),
        'wrong-spare-smc': reference.replace('args=0x0/0x0/0x0', 'args=0x9/0x0/0x0'),
        'wrong-owner': reference.replace('0x42000209', '0x44000209'),
        'wrong-convention': reference.replace('id=0x42000209 convention=3', 'id=0x42000209 convention=2'),
        'wrong-arginfo': reference.replace('arginfo=0x1', 'arginfo=0x3'),
        'wrong-call-id': reference.replace('smc done id=0x42000209', 'smc done id=0x42000201'),
        'wrong-result': reference.replace('r1=0x90000000', 'r1=0x91000000'),
        'oversize-result': reference.replace('r2=0x123456789', 'r2=0x10000000000000000'),
        'wrong-result-valid': reference.replace('result_valid=1', 'result_valid=0'),
        'wrong-return': reference.replace('query transport ret=0', 'query transport ret=-22'),
        'wrong-raw-valid': reference.replace('id=0x42000209 ret=0 raw_valid=1', 'id=0x42000209 ret=0 raw_valid=0'),
        'invalid-query-data': references['area-c3-leaf-existing1'].replace('r0=0x0', 'r0=0xdead'),
        'missing-smc-result': '\n'.join(line for line in reference.splitlines() if 'smc done id=0x42000209' not in line),
        'missing-query-result': '\n'.join(line for line in reference.splitlines() if 'query transport' not in line),
        'orphan-query': references['area-c3-ok-existing0'].splitlines()[-1],
        'repeated-query': reference + references['area-c3-ok-existing0'],
        'caller-overlap': reference.replace('SPX PAS diag smc begin id=0x42000209', 'SPX PAS diag init-image begin pas=9 metadata=0x90000000\nSPX PAS diag smc begin id=0x42000209'),
        'budget-exceeded': references['saturated-budget'] + reference,
        'unknown-message': reference.replace('query transport', 'query unknown'),
    }
    for name, data in mutations.items():
        (fixtures / ('invalid-' + name + '.log')).write_text(data)
        try:
            parse(data)
        except AssertionError as error:
            negative.append(dict(name=name, reason=str(error)))
        else:
            raise AssertionError('Accepted corrupted evidence: ' + name)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), immutable_bb_parser_exact=True,
                  bb_positive_traces_replayed=replayed, synthetic_area_traces=len(positive),
                  corrupt_traces_rejected=negative, shared_smc_budget=8, maximum_lines=34,
                  raw_result_words_not_interpreted=True, no_diagnostics_is_not_success=True,
                  hardware_operations=0, hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*')) if path.is_file()}
    (out / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(bb_replays=replayed, area_traces=len(positive),
                          corrupt_traces_rejected=len(negative), files=len(manifest),
                          manifest_sha256=sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
