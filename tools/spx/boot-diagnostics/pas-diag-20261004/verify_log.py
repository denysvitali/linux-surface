#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze parser fixtures and reject corrupted PAS evidence without hardware calls."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
SRC = Path(__file__).resolve().parent
REPO = SRC.parents[3]
OUT = Path('/var/tmp/spx-mainline-trial-20261004bb/pas-log-review')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    OUT.mkdir(mode=0o700)
    spec = importlib.util.spec_from_file_location('pas_parser', SRC / 'parse_log.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ('parse_log.py', 'verify_log.py'):
        shutil.copy2(SRC / name, OUT / name)
    fixtures = OUT / 'fixtures'
    fixtures.mkdir()
    positive = []

    def check(name, lines, origin, expected_return):
        text = '\n'.join('qcom_scm firmware: SPX PAS diag ' + line for line in lines) + '\n'
        (fixtures / (name + '.log')).write_text(text)
        result = module.parse(text)
        assert len(result['calls']) == 1
        call = result['calls'][0]
        assert call['failure_origin'] == origin and call['caller_return'] == expected_return, name
        (fixtures / (name + '.json')).write_text(json.dumps(result, indent=2) + '\n')
        positive.append(name)
        return text

    reference = None
    for kind in ('init-image', 'mem-setup'):
        begin = (kind + ' begin pas=9 metadata=0x9b000000' if kind == 'init-image'
                 else kind + ' begin pas=9 addr=0xfe500000 size=0x500000')
        for stage in ('clock', 'bandwidth'):
            check(kind + '-' + stage, [begin, kind + ' ' + stage + ' ret=-22'], stage, -22)
        for convention in (2, 3):
            call_id = (0x02000200 if convention == 2 else 0x42000200) + (1 if kind == 'init-image' else 2)
            smc_begin = ('smc begin id=0x%x convention=%d arginfo=0x%x args=0x9/' %
                         (call_id, convention, 0x82 if kind == 'init-image' else 3))
            smc_begin += '0x9b000000/0x0' if kind == 'init-image' else '0xfe500000/0x500000'
            for a0, service in ((0, 0), (0, -22), (-1, 0), (-2, 0), (-3, 0),
                                (-4, 0), (-5, 0), (-12, 0), (17, 0)):
                # Independent expected errno table; never derive expected
                # classification from the parser's own remap implementation.
                ret = {-1: -5, -2: -22, -3: -22, -4: -95, -5: -12, -12: -16, 17: -22}.get(a0, 0)
                raw_a0, raw_a1 = a0 & 0xffffffffffffffff, service & 0xffffffffffffffff
                smc_done = 'smc done id=0x%x ret=0 raw_valid=1 a0=0x%x a1=0x%x a2=0x0 a3=0x0' % (call_id, raw_a0, raw_a1)
                transport = kind + ' transport ret=%d service_valid=%d service=0x%x' % (ret, not ret, raw_a1 if not ret else 0)
                origin = 'scm-a0-remap' if a0 else ('secure-service-a1' if service else None)
                text = check('%s-c%d-a0%d-a1%d' % (kind, convention, a0, service),
                             [begin, smc_begin, smc_done, transport], origin, ret or service)
                if kind == 'mem-setup' and convention == 3 and a0 == -2:
                    reference = text
            for leaf_ret in (-22, -5):
                check('%s-c%d-leaf%d' % (kind, convention, leaf_ret),
                    [begin, smc_begin, 'smc done id=0x%x ret=%d raw_valid=0' % (call_id, leaf_ret),
                     kind + ' transport ret=%d service_valid=0 service=0x0' % leaf_ret],
                    'smc-leaf-transport', leaf_ret)
        check(kind + '-legacy-transport', [begin, kind + ' transport ret=-22 service_valid=0 service=0x0'],
              'caller-transport-unresolved', -22)
        check(kind + '-legacy-service', [begin, kind + ' transport ret=0 service_valid=1 service=0xffffffffffffffea'],
              'secure-service', -22)
    empty = module.parse('ordinary BA log without diagnostic messages\n')
    assert not empty['diagnostic_calls_observed'] and not empty['hardware_acceptance_closed']
    negative = []
    assert reference
    mutations = {
        'wrong-pas': reference.replace('pas=9', 'pas=10'),
        'wrong-owner-call': reference.replace('0x42000202', '0x44000202'),
        'wrong-arginfo': reference.replace('arginfo=0x3', 'arginfo=0x2'),
        'wrong-arguments': reference.replace('args=0x9/', 'args=0x8/'),
        'wrong-address': reference.replace('args=0x9/0xfe500000', 'args=0x9/0xfd500000'),
        'wrong-return': reference.replace('transport ret=-22', 'transport ret=-5'),
        'invalid-service': reference.replace('service_valid=0', 'service_valid=1'),
        'invalid-raw': reference.replace('raw_valid=1', 'raw_valid=0'),
        'missing-result': '\n'.join(line for line in reference.splitlines() if 'smc done' not in line),
        'incomplete': '\n'.join(reference.splitlines()[:-1]),
        'orphan': '\n'.join(reference.splitlines()[1:]),
        'overlapping': reference.splitlines()[0] + '\n' + reference,
        'unknown-message': reference.replace('transport ret=', 'unknown ret='),
        'budget-exceeded': reference * 9,
    }
    for name, text in mutations.items():
        (fixtures / ('invalid-' + name + '.log')).write_text(text)
        try:
            module.parse(text)
        except AssertionError as error:
            negative.append(dict(name=name, reason=str(error)))
        else:
            raise AssertionError('Accepted corrupted evidence: ' + name)
    source_hashes = {}
    for name in ('drivers/firmware/qcom/qcom_scm.c', 'drivers/firmware/qcom/qcom_scm-smc.c',
                 'drivers/firmware/qcom/qcom_scm.h'):
        source_hashes[name] = sha(REPO / name)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), synthetic_positive_traces=len(positive),
                  rejected_corrupt_traces=negative, no_diagnostics_is_not_success=True,
                  production_source_sha256=source_hashes, hardware_operations=0,
                  hardware_acceptance_closed=False)
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = {str(path.relative_to(OUT)): sha(path) for path in sorted(OUT.rglob('*')) if path.is_file()}
    (OUT / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(positive_traces=len(positive), rejected_corrupt_traces=len(negative),
                          files=len(manifest), manifest_sha256=sha(OUT / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
