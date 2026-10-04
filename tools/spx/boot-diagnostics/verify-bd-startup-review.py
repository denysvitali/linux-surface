#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replay real BC syntax through BD's actual interpreter; test success/failure boundaries."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bc_boot_guard as g
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bd_startup_review import analyze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    out = p.parse_args().out
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(Path(__file__).with_name('bd_startup_review.py'), out / 'bd_startup_review.py')
    parser_root = g.X / 'build/pas-area-log-review'
    for name in ('parse_log.py', 'parse_pas.py'):
        shutil.copy2(parser_root / name, out / name)
    sys.path.insert(0, str(out))
    spec = importlib.util.spec_from_file_location('bd_frozen_parser', out / 'parse_log.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    origin = g.X / 'video-startup'
    assert g.sha(origin / 'sha256.json') == '2630290575cd17b9434537a5ef9aad786301ba5810364ec9d5ee8642a381391c'
    original = json.loads((origin / 'sha256.json').read_text())
    assert g.sha(origin / 'kernel.stdout') == original['kernel.stdout']
    kernel = (origin / 'kernel.stdout').read_text()
    relocated = kernel.replace('fe500000', '9a600000').replace('fe9fffff', '9aafffff')
    good = relocated.replace('a0=0xffcfffba', 'a0=0x0').replace(
        'mem-setup transport ret=-22 service_valid=0 service=0x0',
        'mem-setup transport ret=0 service_valid=1 service=0x0')
    state = dict(attempt='20261004bd', release='7.3.0-rc2-spx-mainline-20261004bc+',
        kernel_taint='0', pas_parameters={name: dict(value='Y', mode='0o400')
        for name in ('spx_pas_diag', 'spx_pas_area_diag')},
        platform_devices=[dict(driver=None)], video_nodes=[])
    positive, negative = [], []

    def check(name, text, startup, success=False, bound=False):
        decoded = parser.parse(text)
        report = analyze(startup, text, decoded)
        assert report['pas_memory_setup_zero_observed'] is success
        assert report['normal_venus_driver_bound'] is bound
        assert not report['media_acceptance_passed'] and not report['hardware_acceptance_closed']
        (out / (name + '.json')).write_text(json.dumps(report, indent=2) + '\n')
        (out / (name + '.log')).write_text(text)
        positive.append(name)

    check('relocated-memory-failure', relocated, state)
    check('memory-success-later-probe-failure', good, state, success=True)
    ready = deepcopy(state)
    ready['platform_devices'][0]['driver'] = '/sys/bus/platform/drivers/qcom-venus'
    ready['video_nodes'] = [dict(name='qcom-venus-decoder'), dict(name='qcom-venus-encoder')]
    check('memory-success-bound-nodes', good, ready, success=True, bound=True)
    no_diag = '\n'.join(line for line in good.splitlines()
                        if 'SPX PAS diag ' not in line and 'SPX PAS area query ' not in line) + '\n'
    check('allocation-only-pas-unobserved', no_diag, state)
    no_alloc = '\n'.join(line for line in no_diag.splitlines() if 'OF: reserved mem:' not in line) + '\n'
    check('allocation-failure-pas-unobserved', no_alloc, state)
    begin = next(line for line in relocated.splitlines() if 'SPX PAS diag init-image begin' in line)
    check('init-clock-failure-no-query', no_diag + begin + '\nqcom_scm firmware: SPX PAS diag init-image clock ret=-22\n', state)
    changed_query = good.replace('0x8b700000', '0x8c700000')
    check('changed-query-words-retained', changed_query, state, success=True)
    assert not json.loads((out / 'changed-query-words-retained.json').read_text())['pil_area_query_matches_bc']
    mutations = [
        ('stale-fe-reservation', kernel, state),
        ('wrong-reservation-size', good.replace('9aafffff', '9abfffff'), state),
        ('unaligned-reservation', good.replace('9a600000', '9a600001').replace('9aafffff', '9ab00000'), state),
        ('cross-upper-bound', good.replace('9a600000', '9a700000').replace('9aafffff', '9abfffff'), state),
        ('memory-base-disagrees', '\n'.join(line.replace('9a600000', '9a500000') if 'SPX PAS diag ' in line else line for line in good.splitlines()) + '\n', state),
        ('memory-length-disagrees', re.sub(r'(size=0x0*)500000', r'\g<1>600000', good).replace('/0x500000', '/0x600000'), state),
        ('bound-after-memory-failure', relocated, ready),
        ('bound-without-pas-records', no_diag, ready),
        ('duplicate-reservation', good + next(line for line in good.splitlines() if '(5120 KiB) nomap non-reusable video-firmware' in line) + '\n', state),
        ('corrupted-query-descriptor', good.replace('arginfo=0x1 args=0x0/0x0/0x0', 'arginfo=0x2 args=0x0/0x0/0x0'), state),
    ]
    for name, key, value in (('wrong-attempt', 'attempt', '20261004bc'),
                             ('wrong-release', 'release', '7.3.0-rc2-spx-mainline-20261004bd+'),
                             ('tainted', 'kernel_taint', '4096')):
        bad = deepcopy(state)
        bad[key] = value
        mutations.append((name, good, bad))
    for name, field, value in (('query-flag-disabled', 'value', 'N'), ('query-flag-writable', 'mode', '0o600')):
        bad = deepcopy(state)
        bad['pas_parameters']['spx_pas_area_diag'][field] = value
        mutations.append((name, good, bad))
    for name, text, startup in mutations:
        try:
            analyze(startup, text, parser.parse(text))
        except AssertionError:
            negative.append(name)
        else:
            raise AssertionError('Corruption accepted: ' + name)
    report = dict(actual_interpreter_positive_cases=len(positive), rejected_corruptions=len(negative),
                  actual_bc_log_syntax_replayed=True, raw_log_parser_exact_bc=True,
                  cases=positive, rejected=negative, hardware_operations=0,
                  deployed=False, hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    print(json.dumps(report | dict(manifest_sha256=g.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
