#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual BC startup-review body with explicitly synthetic evidence."""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bb_boot_guard as g

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bc')
CODE = REPO / 'tools/spx/boot-diagnostics/review-bc-result.py'
ROOT = STAGE / 'result-review-offline'
BOOT = 'e00a2d25-03f7-4265-b56e-0eac05b234d3'


def read(path):
    return json.loads(path.read_text())


def seal(root):
    (root / 'sha256.json').write_text(json.dumps(g.files(root), indent=2) + '\n')


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    ROOT.mkdir(mode=0o700)
    shutil.copy2(__file__, ROOT / Path(__file__).name)
    shutil.copy2(CODE, ROOT / CODE.name)
    tree = ast.parse(CODE.read_text())
    bodies = [node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name in ('read', 'sealed', 'startup')]
    assert len(bodies) == 3
    raw = (g.X / 'video-startup/kernel.stdout').read_text()
    original = read(g.X / 'video-startup/result.json')
    parent = g.load()
    cmdline = parent['cmdline'].replace('spx_attempt=20261004bb', 'spx_attempt=20261004bc')
    cmdline += ' qcom_scm.spx_pas_area_diag=1'
    a = dict(attempt='20261004bc', release='7.3.0-rc2-spx-mainline-20261004bc+',
             preboot_id=BOOT, cmdline=cmdline)
    positives, negatives = [], []
    for kind in ('ok', 'unknown-a0', 'leaf', 'wrong-spare', 'wrong-result', 'wrong-mode',
                 'repeated-query', 'changed-memory-error'):
        case = ROOT / kind
        case.mkdir()
        x, out = case / 'synthetic-attempt', case / 'review-output'
        x.mkdir()
        out.mkdir()
        for name in ('video-startup', 'camera-provider-result', 'camera-control-result'):
            shutil.copytree(g.X / name, x / name)
        build = x / 'build'
        build.mkdir()
        dt = build / 'dtb-build'
        dt.mkdir()
        shutil.copy2(g.X / 'build/dtb-build/video_dt_contract.py', dt / 'video_dt_contract.py')
        shutil.copytree(g.X / 'offline-pas-area-diag-20261004/log-v1', build / 'pas-area-log-review')
        shutil.copy2(STAGE / 'source-files.json', build / 'source-files.json')
        shutil.copy2(STAGE / 'work-build/.config', build / 'config-extracted')
        result = original | dict(attempt=a['attempt'], release=a['release'],
            boot_id='00000000-0000-0000-0000-000000000042',
            cmdline='BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz ' + cmdline)
        witness = {name: dict(value='Y', mode='0o400') for name in ('spx_pas_diag', 'spx_pas_area_diag')}
        if kind == 'wrong-mode':
            witness['spx_pas_area_diag']['mode'] = '0o600'
        result['pas_parameters'] = witness
        (x / 'video-startup/result.json').write_text(json.dumps(result, indent=2) + '\n')
        (x / 'video-startup/pas-parameters.json').write_text(json.dumps(witness, indent=2) + '\n')
        leaf = -110 if kind == 'leaf' else 0
        a0 = 0xffcfffba if kind == 'unknown-a0' else 0
        ret = leaf or (-22 if a0 else 0)
        query = ['SPX PAS area query begin spare=0',
                 'SPX PAS diag smc begin id=0x42000209 convention=3 arginfo=0x1 args=0x0/0x0/0x0',
                 'SPX PAS diag smc done id=0x42000209 ret=%d raw_valid=%d' % (leaf, not leaf)]
        if not leaf:
            query[-1] += ' a0=0x%x a1=0x80000000 a2=0x90000000 a3=0x123456789' % a0
        words = [0, 0, 0] if ret else [0x80000000, 0x90000000, 0x123456789]
        query += ['SPX PAS area query transport ret=%d result_valid=%d r0=0x%x r1=0x%x r2=0x%x' %
                  (ret, not ret, *words)]
        if kind == 'wrong-spare':
            query[1] = query[1].replace('args=0x0/', 'args=0x9/')
        if kind == 'wrong-result':
            query[-1] = query[-1].replace('r1=0x90000000', 'r1=0x91000000')
        lines = raw.splitlines()
        insert = next(i + 1 for i, line in enumerate(lines) if 'SPX PAS diag init-image begin' in line)
        lines[insert:insert] = ['qcom_scm firmware: ' + line for line in query]
        if kind == 'repeated-query':
            lines += ['qcom_scm firmware: ' + line for line in query]
        data = '\n'.join(lines) + '\n'
        if kind == 'changed-memory-error':
            data = data.replace('a0=0xffcfffba', 'a0=0xfffffffe')
        (x / 'video-startup/kernel.stdout').write_text(data)
        seal(x / 'video-startup')
        media = read(g.X / 'media-not-run.json') | dict(boot_id=result['boot_id'],
                video_startup_sha256=g.sha(x / 'video-startup/result.json'))
        (x / 'media-not-run.json').write_text(json.dumps(media, indent=2) + '\n')
        ns = dict(X=x, RUNTIME=g.RUNTIME, Path=Path, json=json, shutil=shutil, sys=sys, re=__import__('re'),
                  os=SimpleNamespace(uname=lambda: SimpleNamespace(release='6.18.3-1-surface+')),
                  files=g.files, sha=g.sha)
        exec(compile(ast.Module(body=bodies, type_ignores=[]), str(CODE), 'exec'), ns)
        try:
            report = ns['startup'](out, a)
        except AssertionError:
            assert kind not in ('ok', 'unknown-a0', 'leaf'), kind
            (case / 'rejected.txt').write_text(traceback.format_exc())
            negatives.append(kind)
        else:
            assert kind in ('ok', 'unknown-a0', 'leaf'), kind
            assert report['pil_area_query_return'] == ret
            assert report['pil_area_query_result_words'] == (None if ret else words)
            assert report['original_pas_init_and_memory_outcomes_match_bb']
            assert report['pil_area_raw_result_layout_unverified']
            assert not report['suitable_allocation_established'] and not report['hardware_acceptance_closed']
            (case / 'synthetic-review.json').write_text(json.dumps(report, indent=2) + '\n')
            positives.append(kind)
    assert positives == ['ok', 'unknown-a0', 'leaf'] and len(negatives) == 5
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    report = dict(utc=datetime.now(timezone.utc).isoformat(), actual_startup_review_body=True,
                  synthetic_positive_cases=positives, corrupt_cases_rejected=negatives,
                  os_release_read_mocked=True, evidence_explicitly_synthetic=True,
                  startup_reviewer_sha256=g.sha(CODE), untouched_bb_evidence=True,
                  uninferred_raw_result_words=True, hardware_operations=0,
                  hardware_acceptance_closed=False)
    (ROOT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    seal(ROOT)
    expected = read(ROOT / 'sha256.json')
    assert g.files(ROOT) == expected | {'sha256.json': g.sha(ROOT / 'sha256.json')}
    os.sync()
    print(json.dumps(report | dict(files=len(expected), manifest_sha256=g.sha(ROOT / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
