#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute BF's real startup body and wrapper with explicitly modeled records."""
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
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

BF = g.X.with_name('20261004bf')
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def seal(path):
    (path / 'sha256.json').unlink(missing_ok=True)
    write(path / 'sha256.json', g.files(path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    root = p.parse_args().out
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a0 = g.load()
    assert a0['state'].startswith('BE terminal;') and not g.recovery(a0).get('next_entry', '')
    root.mkdir(mode=0o700)
    for name in ('verify-bf-result-review.py', 'review-bf-result.py', 'bf_startup_review.py', 'bf_venus_startup.py'):
        shutil.copy2(HERE / name, root / name)
    tree = ast.parse((root / 'review-bf-result.py').read_text())
    bodies = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('read', 'sealed', 'startup')]
    wrappers = bodies + [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    assert len(bodies) == 3 and len(wrappers) == 4
    cmdline = a0['cmdline'].replace('spx_attempt=20261004be', 'spx_attempt=20261004bf') + ' venus_core.spx_hfi_startup_diag=1'
    a = dict(attempt='20261004bf', release=RELEASE, preboot_id=BOOT, cmdline=cmdline,
             runtime_sha256={str(root / name): g.sha(root / name) for name in ('bf_startup_review.py', 'bf_venus_startup.py')})
    raw = (g.X / 'video-startup/kernel.stdout').read_text()
    native = (BF / 'preparation/venus-log-review/native-derived-synthetic.log').read_text()
    positive = ('memory-success-core-timeout', 'missing-parameter-no-new-logs', 'memory-failure',
                'bound-media-pending', 'bound-media-scoped-pass', 'bound-media-scoped-failure',
                'allocation-unobserved', 'queue-outside-mask-observed', 'raw-auth-rejection')
    negative = ('old-dt-range', 'dt-size', 'dt-alignment', 'no-map-lost', 'mode', 'wrong-image',
                'wrong-attempt', 'wrong-release', 'same-preboot', 'taint', 'uptime', 'provider-unbound',
                'memory-address', 'startup-tamper', 'source-manifest', 'skip-boot-id', 'skip-startup-hash',
                'media-boot-id', 'media-release', 'media-tamper', 'nomap-lost', 'reserved-overlap',
                'map-collector-failed', 'venus-mode', 'venus-disabled', 'venus-missing-with-logs',
                'venus-witness-mismatch', 'venus-poll-impossible', 'venus-cap-exceeded', 'parser-tamper')
    accepted, rejected = [], []
    for kind in positive + negative:
        case = root / kind
        x, out = case / 'synthetic-attempt', case / 'body-review'
        x.mkdir(parents=True)
        out.mkdir()
        for name in ('video-startup', 'camera-provider-result', 'camera-control-result'):
            shutil.copytree(g.X / name, x / name)
        assembly = x / 'assembly'
        dt = assembly / 'dtb-build'
        dt.mkdir(parents=True)
        for name in ('video_dt_contract.py',):
            shutil.copy2(BF / 'assembly/dtb-build' / name, dt / name)
        for name in ('source-files.json', 'config-extracted'):
            shutil.copy2(BF / 'assembly' / name, assembly / name)
        prep = x / 'preparation-reviewed'
        prep.mkdir()
        shutil.copytree(BF / 'preparation/pas-area-log-review', prep / 'pas-area-log-review')
        result = read(g.X / 'video-startup/result.json')
        result.update(attempt='20261004bf', release=RELEASE,
                      cmdline='BOOT_IMAGE=/spx-trial-20261004bf/vmlinuz ' + cmdline,
                      venus_startup_parameter=dict(observed=True, value='Y', mode='0o400'))
        memory = (x / 'video-startup/memblock-memory.stdout').read_text()
        reserved = (x / 'video-startup/memblock-reserved.stdout').read_text()
        text = raw + native
        if kind == 'missing-parameter-no-new-logs':
            text = raw
            result['venus_startup_parameter'] = dict(observed=False, error='explicitly synthetic absent module')
        if kind == 'memory-failure':
            text = '\n'.join(line.replace('a0=0x0', 'a0=0xffcfffba') if 'smc done id=0x42000202' in line else
                line.replace('mem-setup transport ret=0 service_valid=1', 'mem-setup transport ret=-22 service_valid=0')
                for line in raw.splitlines()) + '\n'
        bound = kind.startswith('bound-') or kind.startswith('media-')
        if bound:
            result['platform_devices'][0]['driver'] = '/sys/bus/platform/drivers/qcom-venus'
            result['video_nodes'] = [dict(name='qcom-venus-decoder'), dict(name='qcom-venus-encoder')]
            text = raw + native.replace('poll ret=-110 count=100 status=0x2', 'poll ret=0 count=1 status=0x1')
        if kind == 'allocation-unobserved':
            text = '\n'.join(line for line in raw.splitlines() if 'SPX PAS ' not in line and 'OF: reserved mem:' not in line) + '\n'
        if kind == 'queue-outside-mask-observed':
            text = text.replace('0x00000000abcdef00', '0x00000000df000000')
        if kind == 'raw-auth-rejection':
            text = raw + native.splitlines()[0].replace('ret=0', 'ret=-13') + '\n'
        if kind in ('old-dt-range', 'dt-size', 'dt-alignment', 'no-map-lost'):
            path = x / 'video-startup/actual-fdt.dtb'
            fdt = libfdt.Fdt(path.read_bytes())
            fdt.resize(fdt.totalsize() + 1024)
            offset = fdt.path_offset('/reserved-memory/video-firmware@8d300000')
            if kind == 'no-map-lost':
                fdt.delprop(offset, 'no-map')
            else:
                name, cells = {'old-dt-range': ('reg', (0, 0xfe500000, 0, 0x500000)),
                    'dt-size': ('reg', (0, 0x8d300000, 0, 0x600000)), 'dt-alignment': ('alignment', (0, 0x100000))}[kind]
                fdt.setprop(offset, name, struct.pack('>' + 'I' * len(cells), *cells))
            path.write_bytes(bytes(fdt.as_bytearray()))
        if kind == 'mode': result['pas_parameters']['spx_pas_area_diag']['mode'] = '0o600'
        if kind == 'wrong-image': result['cmdline'] = result['cmdline'].replace('/spx-trial-20261004bf/', '/spx-trial-20261004bc/')
        if kind == 'wrong-attempt': result['attempt'] = '20261004be'
        if kind == 'wrong-release': result['release'] = a0['release']
        if kind == 'same-preboot': result['boot_id'] = BOOT
        if kind == 'taint': result['kernel_taint'] = '4096'
        if kind == 'uptime': result['uptime_start'] = 500
        if kind == 'provider-unbound': result['clock_provider_devices'][0]['driver'] = None
        if kind == 'memory-address':
            text = '\n'.join(line.replace('8d300000', '9a500000') if 'SPX PAS diag ' in line else line for line in text.splitlines()) + '\n'
        if kind == 'source-manifest':
            rows = read(assembly / 'source-files.json')
            rows['drivers/media/platform/qcom/venus/hfi_venus.c']['sha256'] = '0' * 64
            write(assembly / 'source-files.json', rows)
        if kind == 'nomap-lost': memory = memory.replace('NOMAP', 'NONE')
        if kind == 'reserved-overlap': reserved = '0: 0x8d300000..0x8d300fff 0 NONE\n'
        if kind == 'map-collector-failed':
            next(row for row in result['commands'] if row['label'] == 'memblock-memory')['exit_code'] = 1
        if kind == 'venus-mode': result['venus_startup_parameter']['mode'] = '0o600'
        if kind == 'venus-disabled': result['venus_startup_parameter']['value'] = 'N'
        if kind == 'venus-missing-with-logs': result['venus_startup_parameter'] = dict(observed=False, error='missing')
        if kind == 'venus-poll-impossible': text = text.replace('poll ret=-110', 'poll ret=0')
        if kind == 'venus-cap-exceeded': text = raw + native * 9
        if kind == 'parser-tamper':
            with (prep / 'pas-area-log-review/parse_log.py').open('a') as stream: stream.write('\n# tampered\n')
        write(x / 'video-startup/result.json', result)
        write(x / 'video-startup/pas-parameters.json', result['pas_parameters'])
        write(x / 'video-startup/venus-parameter.json', result['venus_startup_parameter'] if kind != 'venus-witness-mismatch' else dict(observed=False, error='mismatch'))
        for label, data in (('kernel', text), ('memblock-memory', memory), ('memblock-reserved', reserved)):
            (x / 'video-startup' / (label + '.stdout')).write_text(data)
        seal(x / 'video-startup')
        if kind == 'startup-tamper': (x / 'video-startup/kernel.stdout').write_text(text + 'tampered\n')
        if bound and kind != 'bound-media-pending':
            media = x / 'media-short-result'
            media.mkdir()
            verdict = dict(boot_id=BOOT if kind == 'media-boot-id' else result['boot_id'],
                release='6.18.3-1-surface+' if kind == 'media-release' else RELEASE,
                scoped_passed=kind != 'bound-media-scoped-failure')
            write(media / 'result.json', verdict)
            seal(media)
            if kind == 'media-tamper': (media / 'result.json').write_text(json.dumps(verdict) + ' ')
        elif not bound:
            write(x / 'media-not-run.json', dict(boot_id=BOOT if kind == 'skip-boot-id' else result['boot_id'],
                hardware_codec_used=False, video_startup_sha256='0' * 64 if kind == 'skip-startup-hash' else g.sha(x / 'video-startup/result.json')))
        ns = dict(X=x, RUNTIME=root, Path=Path, json=json, shutil=shutil, sys=sys, files=g.files, sha=g.sha,
            os=SimpleNamespace(uname=lambda: SimpleNamespace(release='6.18.3-1-surface+')))
        exec(compile(ast.Module(body=bodies, type_ignores=[]), str(root / 'review-bf-result.py'), 'exec'), ns)
        try:
            report = ns['startup'](out, a)
        except (AssertionError, libfdt.FdtException):
            assert kind in negative, kind
            (case / 'rejected.txt').write_text(traceback.format_exc())
            rejected.append(kind)
        else:
            assert kind in positive, kind
            assert report['normal_venus_driver_bound'] is bound
            assert not report['media_acceptance_passed'] and not report['hardware_acceptance_closed']
            assert report['pas_memory_returns'] == ([] if kind == 'allocation-unobserved' else [-22] if kind == 'memory-failure' else [0])
            if kind == 'queue-outside-mask-observed': assert not report['venus_startup']['buffer_observations'][0]['queue_dma_within_declared_mask']
            if kind == 'raw-auth-rejection': assert report['venus_startup']['auth_reset_api_returns'] == [-13]
            write(case / 'synthetic-review.json', report)
            accepted.append(kind)
    assert accepted == list(positive) and rejected == list(negative)

    # Run the unmodified main wrapper too; only OS identity, commands and the
    # not-yet-installed artifact guard are modeled. All startup files are real
    # sealed synthetic fixtures, and the two archive reports are immutable BF.
    x = root / positive[0] / 'synthetic-attempt'
    for name in ('build-review.json', 'assembly-review.json'):
        shutil.copy2(BF / name, x / name)
    system = root / 'synthetic-system'
    system.mkdir()
    result = read(x / 'video-startup/result.json')
    proc = {'/proc/sys/kernel/random/boot_id': result['boot_id'], '/proc/cmdline': result['cmdline'],
            '/proc/sys/kernel/tainted': '0', '/sys/kernel/debug/devices_deferred': '',
            '/sys/bus/platform/devices/ab00000.clock-controller/uevent': 'DRIVER=video_cc-sm8150\n'}
    mapped = {}
    for i, (name, value) in enumerate(proc.items()):
        path = system / str(i)
        path.write_text(value + '\n')
        mapped[name] = path
    for name in ('spx_pas_diag', 'spx_pas_area_diag'):
        path = system / name
        path.write_text('Y\n')
        path.chmod(0o400)
        mapped['/sys/module/qcom_scm/parameters/' + name] = path
    mapped['/sys/module/qcom_scm/parameters'] = system
    driver = system / 'provider-driver'
    driver.symlink_to('/sys/bus/platform/drivers/video_cc-sm8150')
    mapped['/sys/bus/platform/devices/ab00000.clock-controller/driver'] = driver
    calls = []
    def command(*argv):
        calls.append(list(argv))
        if argv[0] == 'journalctl': return raw
        if argv[0] == 'grub-editenv': return 'saved_entry=spx-known-good\nnext_entry=\n'
        if argv[0] == 'efibootmgr': return 'BootCurrent: 0001\n'
        raise AssertionError(argv)
    ns = dict(__file__=str(root / 'review-bf-result.py'), X=x, RUNTIME=root, Path=lambda value: mapped.get(str(value), Path(value)), json=json,
        shutil=shutil, sys=sys, files=g.files, links=g.links, sha=g.sha, command=command,
        argparse=SimpleNamespace(ArgumentParser=lambda: SimpleNamespace(add_argument=lambda *args, **kw: None,
            parse_args=lambda: SimpleNamespace(phase='startup'))),
        os=SimpleNamespace(uname=lambda: SimpleNamespace(release=RELEASE), umask=os.umask, sync=os.sync),
        load=lambda: a, trial_identity=lambda metadata: result['boot_id'],
        recovery=lambda metadata: calls.append(['modeled-recovery-guard']) or {'saved_entry': 'spx-known-good', 'next_entry': ''},
        artifacts=lambda metadata: calls.append(['modeled-installed-artifact-guard']), traceback=traceback,
        datetime=datetime, timezone=timezone)
    exec(compile(ast.Module(body=wrappers, type_ignores=[]), str(root / 'review-bf-result.py'), 'exec'), ns)
    ns['main']()
    wrapper = read(x / 'startup-review/report.json')
    assert wrapper['build_files_verified'] == 243 and wrapper['assembly_files_verified'] == 818 and wrapper['assembly_links_verified'] == 272
    assert ['modeled-recovery-guard'] in calls and ['modeled-installed-artifact-guard'] in calls
    write(root / 'wrapper-calls.json', calls)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), actual_startup_body_executed=True,
        actual_main_wrapper_executed=True, accepted=accepted, rejected=rejected, explicitly_synthetic=True,
        physical_operations=0, main_identity_and_installed_guards_modeled=True,
        source_provider_map_and_log_checks_real=True, full_bf_archive_layout_exercised=True,
        untouched_actual_be_evidence=True, hardware_acceptance_closed=False)
    write(root / 'report.json', report)
    write(root / 'symlinks.json', g.links(root))
    seal(root)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    print(json.dumps(report | dict(manifest_sha256=g.sha(root / 'sha256.json'))), flush=True)


if __name__ == '__main__':
    main()
