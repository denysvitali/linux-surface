#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual BE startup review against sealed synthetic boot records."""
import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import traceback
from types import SimpleNamespace

import libfdt

sys.dont_write_bytecode = True
SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g

XBE = g.X.with_name('20261004be')
BOOT = '433a78d6-9748-422f-a1a7-aac43c784a7d'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def seal(root):
    (root / 'sha256.json').unlink(missing_ok=True)
    write(root / 'sha256.json', g.files(root))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    root = p.parse_args().out
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    root.mkdir(mode=0o700)
    for name in (Path(__file__).name, 'review-be-result.py', 'be_startup_review.py'):
        shutil.copy2(SRC / name, root / name)
    bodies = [n for n in ast.parse((root / 'review-be-result.py').read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name in ('read', 'sealed', 'startup')]
    assert len(bodies) == 3
    parent = g.load()
    assert parent['attempt'] == '20261004bd' and parent['state'].startswith('BD terminal;')
    cmdline = parent['cmdline'].replace('spx_attempt=20261004bd', 'spx_attempt=20261004be')
    a = dict(attempt='20261004be', release=parent['release'], preboot_id=BOOT, cmdline=cmdline,
             runtime_sha256={str(root / 'be_startup_review.py'): g.sha(root / 'be_startup_review.py')})
    origin = g.BASE / 'attempts/20261004bc/video-startup'
    raw = (origin / 'kernel.stdout').read_text().replace('video-firmware', 'video-firmware@8d300000')
    relocated = raw.replace('fe500000', '8d300000').replace('fe9fffff', '8d7fffff')
    good = relocated.replace('a0=0xffcfffba', 'a0=0x0').replace(
        'mem-setup transport ret=-22 service_valid=0 service=0x0',
        'mem-setup transport ret=0 service_valid=1 service=0x0')
    original = read(origin / 'result.json')
    positive = ('memory-failure', 'memory-success-later-probe-failure', 'bound-media-pending',
                'bound-media-scoped-pass', 'bound-media-scoped-failure', 'allocation-unobserved')
    negative = ('old-dt-range', 'dt-size', 'dt-alignment', 'mode', 'wrong-image', 'wrong-attempt',
                'wrong-release', 'same-preboot', 'provider-unbound', 'outside-aperture',
                'memory-address', 'startup-tamper', 'source-manifest', 'skip-boot-id',
                'skip-startup-hash', 'media-boot-id', 'media-release', 'media-tamper', 'nomap-lost', 'reserved-overlap', 'map-collector-failed')
    accepted, rejected = [], []
    for kind in positive + negative:
        case = root / kind
        case.mkdir()
        x, out = case / 'synthetic-attempt', case / 'review-output'
        x.mkdir()
        out.mkdir()
        for name in ('video-startup', 'camera-provider-result', 'camera-control-result'):
            shutil.copytree(g.X / name, x / name)
        build = x / 'build'
        build.mkdir()
        (build / 'pas-area-log-review').symlink_to(g.X / 'build/pas-area-log-review')
        shutil.copy2(g.X / 'build/config-extracted', build / 'config-extracted')
        dt = x / 'dtb-build'
        dt.mkdir()
        shutil.copy2(XBE / 'dtb-build/video_dt_contract.py', dt / 'video_dt_contract.py')
        shutil.copy2(XBE / 'dtb-build/candidate-source-files.json', dt / 'candidate-source-files.json')
        shutil.copy2(XBE / 'dtb-build/spx.dtb', x / 'video-startup/actual-fdt.dtb')
        result = deepcopy(original)
        result.update(attempt=a['attempt'], release=a['release'],
                      cmdline='BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz ' + cmdline)
        memory_root = g.X / 'actual-memory-aperture'
        memory = (memory_root / 'memblock-memory').read_text()
        reserved = (memory_root / 'memblock-reserved').read_text()
        if kind == 'nomap-lost':
            memory = memory.replace('NOMAP', 'NONE')
        if kind == 'reserved-overlap':
            reserved = '0: 0x8d300000..0x8d300fff 0 NONE\n'
        for label, data in (('memblock-memory', memory), ('memblock-reserved', reserved)):
            (x / 'video-startup' / (label + '.stdout')).write_text(data)
            (x / 'video-startup' / (label + '.stderr')).write_text('')
            result['commands'].append(dict(label=label, argv=['cat', '/sys/kernel/debug/memblock/' + label.removeprefix('memblock-')],
                exit_code=1 if kind == 'map-collector-failed' and label == 'memblock-memory' else 0))
        text = relocated if kind in ('memory-failure', 'outside-aperture', 'memory-address') else good
        bound = kind.startswith('bound-') or kind.startswith('media-')
        if bound:
            result['platform_devices'][0]['driver'] = '/sys/bus/platform/drivers/qcom-venus'
            result['video_nodes'] = [dict(name='qcom-venus-decoder'), dict(name='qcom-venus-encoder')]
        if kind == 'allocation-unobserved':
            text = '\n'.join(line for line in text.splitlines() if
                'SPX PAS ' not in line and 'OF: reserved mem:' not in line) + '\n'
        if kind in ('old-dt-range', 'dt-size', 'dt-alignment'):
            blob = libfdt.Fdt((x / 'video-startup/actual-fdt.dtb').read_bytes())
            blob.resize(blob.totalsize() + 1024)
            offset = blob.path_offset('/reserved-memory/video-firmware@8d300000')
            name, cells = {'old-dt-range': ('reg', (0, 0xfe500000, 0, 0x500000)),
                           'dt-size': ('reg', (0, 0x8d300000, 0, 0x600000)),
                           'dt-alignment': ('alignment', (0, 0x100000))}[kind]
            blob.setprop(offset, name, struct.pack('>' + 'I' * len(cells), *cells))
            (x / 'video-startup/actual-fdt.dtb').write_bytes(bytes(blob.as_bytearray()))
        if kind == 'mode':
            result['pas_parameters']['spx_pas_area_diag']['mode'] = '0o600'
        if kind == 'wrong-image':
            result['cmdline'] = result['cmdline'].replace('/spx-trial-20261004bc/vmlinuz', '/spx-trial-20261004be/vmlinuz')
        if kind == 'wrong-attempt':
            result['attempt'] = '20261004bc'
        if kind == 'wrong-release':
            result['release'] = '7.3.0-rc2-spx-mainline-20261004be+'
        if kind == 'same-preboot':
            result['boot_id'] = BOOT
        if kind == 'provider-unbound':
            result['clock_provider_devices'][0]['driver'] = None
        if kind == 'outside-aperture':
            text = raw
        if kind == 'memory-address':
            text = '\n'.join(line.replace('8d300000', '9a500000') if 'SPX PAS diag ' in line
                             else line for line in text.splitlines()) + '\n'
        if kind == 'source-manifest':
            rows = read(dt / 'candidate-source-files.json')
            rows['drivers/media/platform/qcom/venus/core.c']['sha256'] = '0' * 64
            write(dt / 'candidate-source-files.json', rows)
        write(x / 'video-startup/result.json', result)
        write(x / 'video-startup/pas-parameters.json', result['pas_parameters'])
        (x / 'video-startup/kernel.stdout').write_text(text)
        seal(x / 'video-startup')
        if kind == 'startup-tamper':
            (x / 'video-startup/kernel.stdout').write_text(text + 'tampered\n')
        if bound and kind != 'bound-media-pending':
            media = x / 'media-short-result'
            media.mkdir()
            verdict = dict(boot_id=result['boot_id'], release=a['release'],
                           scoped_passed=kind != 'bound-media-scoped-failure')
            if kind == 'media-boot-id':
                verdict['boot_id'] = BOOT
            if kind == 'media-release':
                verdict['release'] = '6.18.3-1-surface+'
            write(media / 'result.json', verdict)
            seal(media)
            if kind == 'media-tamper':
                (media / 'result.json').write_text(json.dumps(verdict) + ' ')
        elif not bound:
            skip = dict(boot_id=result['boot_id'], hardware_codec_used=False,
                        video_startup_sha256=g.sha(x / 'video-startup/result.json'))
            if kind == 'skip-boot-id':
                skip['boot_id'] = BOOT
            if kind == 'skip-startup-hash':
                skip['video_startup_sha256'] = '0' * 64
            write(x / 'media-not-run.json', skip)
        ns = dict(X=x, RUNTIME=root, Path=Path, json=json, shutil=shutil, sys=sys,
                  os=SimpleNamespace(uname=lambda: SimpleNamespace(release='6.18.3-1-surface+')),
                  files=g.files, sha=g.sha)
        exec(compile(ast.Module(body=bodies, type_ignores=[]), str(root / 'review-be-result.py'), 'exec'), ns)
        try:
            report = ns['startup'](out, a)
        except AssertionError as exc:
            assert kind in negative, kind
            if kind == 'reserved-overlap':
                assert str(exc) == 'Reserved range overlaps static video slot'
            (case / 'rejected.txt').write_text(traceback.format_exc())
            rejected.append(kind)
        else:
            assert kind in positive, kind
            assert report['normal_venus_driver_bound'] is bound
            assert not report['media_acceptance_passed'] and not report['hardware_acceptance_closed']
            if kind == 'memory-failure':
                assert report['pas_memory_returns'] == [-22]
            elif kind == 'allocation-unobserved':
                assert report['firmware_reservation'] is None and report['pas_memory_returns'] == []
            else:
                assert report['pas_memory_returns'] == [0]
            if kind in ('bound-media-scoped-pass', 'bound-media-scoped-failure'):
                assert report['media_short_producer_scoped_passed'] is (kind == 'bound-media-scoped-pass')
                assert report['media_independent_functional_review_pending']
            write(case / 'synthetic-review.json', report)
            accepted.append(kind)
    assert accepted == list(positive) and rejected == list(negative)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    report = dict(utc=datetime.now(timezone.utc).isoformat(), actual_startup_review_body=True,
                  explicitly_synthetic=True, accepted=accepted, rejected=rejected,
                  actual_provider_contract_checked=True, actual_source_hashes_checked=True,
                  untouched_actual_bc_evidence=True, hardware_operations=0,
                  hardware_acceptance_closed=False)
    write(root / 'report.json', report)
    write(root / 'symlinks.json', g.links(root))
    seal(root)
    assert g.files(root) == read(root / 'sha256.json') | {'sha256.json': g.sha(root / 'sha256.json')}
    os.sync()
    print(json.dumps(report | dict(files=len(read(root / 'sha256.json')),
                                  manifest_sha256=g.sha(root / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
