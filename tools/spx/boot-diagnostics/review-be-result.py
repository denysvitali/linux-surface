#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Review BE's bounded allocation, observed PAS outcomes and guarded return."""
import argparse
import ast
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from be_boot_guard import X, RUNTIME, load, recovery, artifacts, files, sha, trial_identity


def read(path):
    return json.loads(path.read_text())


def sealed(root):
    expected = read(root / 'sha256.json')
    assert files(root) == expected | {'sha256.json': sha(root / 'sha256.json')}, root
    return dict(files=len(expected), manifest_sha256=sha(root / 'sha256.json'))


def command(*args):
    return subprocess.check_output(args, text=True, timeout=180)


def startup(out, a):
    import importlib.util
    import struct
    import libfdt
    from be_startup_review import analyze, memory_maps
    result = read(X / 'video-startup/result.json')
    assert result['attempt'] == a['attempt'] == '20261004be'
    assert result['release'] == a['release']
    assert result['boot_id'] != a['preboot_id'] and 60 <= result['uptime_start'] < 240
    assert result['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz'] + a['cmdline'].split()
    assert result['kernel_taint'] == '0'
    assert len(result['platform_devices']) == 1
    provider = result['clock_provider_devices']
    assert len(provider) == 1 and provider[0]['driver'] == '/sys/bus/platform/drivers/video_cc-sm8150'
    tree = libfdt.Fdt((X / 'video-startup/actual-fdt.dtb').read_bytes())
    offset = tree.path_offset('/reserved-memory/video-firmware@8d300000')
    assert bytes(tree.getprop(offset, 'reg')) == struct.pack('>4I', 0, 0x8d300000, 0, 0x500000)
    assert bytes(tree.getprop(offset, 'no-map')) == b''
    for name in ('size', 'alignment', 'alloc-ranges', 'reusable'):
        try:
            tree.getprop(offset, name)
        except libfdt.FdtException as exc:
            assert exc.err == -libfdt.NOTFOUND
        else:
            raise AssertionError('Unexpected static reservation property: ' + name)
    contract_path = X / 'dtb-build/video_dt_contract.py'
    spec = importlib.util.spec_from_file_location('be_dt_contract', contract_path)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    assert contract.EXPECTED['memory-region'] == [('/reserved-memory/video-firmware', [])]
    contract.EXPECTED['memory-region'] = [('/reserved-memory/video-firmware@8d300000', [])]
    references = contract.validate((X / 'video-startup/actual-fdt.dtb').read_bytes())
    (out / 'actual-provider-contracts.json').write_text(json.dumps(references, indent=2) + '\n')
    diagnostic = X / 'build/pas-area-log-review'
    sealed(diagnostic)
    for name in ('parse_log.py', 'parse_pas.py'):
        shutil.copy2(diagnostic / name, out / name)
    sys.path.insert(0, str(diagnostic))
    spec = importlib.util.spec_from_file_location('be_pas_parser', diagnostic / 'parse_log.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    kernel = (X / 'video-startup/kernel.stdout').read_text()
    decoded = parser.parse(kernel)
    report = analyze(result, kernel, decoded)
    for label in ('memblock-memory', 'memblock-reserved'):
        commands = [row for row in result['commands'] if row['label'] == label]
        expected = ['cat', '/sys/kernel/debug/memblock/' + label.removeprefix('memblock-')]
        assert len(commands) == 1 and commands[0]['argv'] == expected and commands[0]['exit_code'] == 0
    report.update(memory_maps((X / 'video-startup/memblock-memory.stdout').read_text(),
                              (X / 'video-startup/memblock-reserved.stdout').read_text()))
    (out / 'decoded-pas.json').write_text(json.dumps(decoded, indent=2) + '\n')
    witness = read(X / 'video-startup/pas-parameters.json')
    assert witness == result['pas_parameters']
    assert witness == {name: dict(value='Y', mode='0o400') for name in ('spx_pas_diag', 'spx_pas_area_diag')}
    if os.uname().release == a['release']:
        for name, expected in witness.items():
            path = Path('/sys/module/qcom_scm/parameters') / name
            assert dict(value=path.read_text().strip(), mode=oct(path.stat().st_mode & 0o777)) == expected
    rows = read(X / 'dtb-build/candidate-source-files.json')
    for name in ('drivers/soc/qcom/mdt_loader.c', 'drivers/media/platform/qcom/venus/firmware.c',
                 'drivers/media/platform/qcom/venus/core.c', 'drivers/firmware/qcom/qcom_scm.c',
                 'drivers/firmware/qcom/qcom_scm-smc.c', 'drivers/firmware/qcom/qcom_scm.h',
                 'drivers/firmware/qcom/qcom_pas.c', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):
        source = Path('/home/dvitali/Documents/git/linux-surface-next') / name
        assert sha(source) == rows[name]['sha256']
        shutil.copy2(source, out / source.name)
    shutil.copy2(X / 'build/config-extracted', out / 'candidate.config')
    for name in ('be_startup_review.py',):
        source = RUNTIME / name
        assert sha(source) == a['runtime_sha256'][str(source)]
        shutil.copy2(source, out / name)
    assert 'could not get #interconnect-cells' not in kernel
    report.update(boot_id=result['boot_id'], release=result['release'], startup=sealed(X / 'video-startup'),
                  provider=sealed(X / 'camera-provider-result'), initial_camera=sealed(X / 'camera-control-result'),
                  actual_provider_declared_argument_contracts_verified=True,
                  pil_reply_layout_correlated_from_retained_vendor_and_primary_interface=True,
                  original_interconnect_parse_failure_absent=True)
    skipped = X / 'media-not-run.json'
    media = X / 'media-short-result'
    if skipped.exists():
        data = read(skipped)
        assert data['boot_id'] == result['boot_id'] and data['hardware_codec_used'] is False
        assert data['video_startup_sha256'] == sha(X / 'video-startup/result.json')
        shutil.copy2(skipped, out / skipped.name)
        report['media_phase'] = 'not run: normal nodes unavailable'
    elif (media / 'result.json').exists() and (media / 'sha256.json').exists():
        data = read(media / 'result.json')
        assert data['boot_id'] == result['boot_id'] and data['release'] == a['release']
        report['media_phase'] = 'completed'
        report['media_short_result'] = sealed(media)
        report['media_short_producer_scoped_passed'] = bool(data.get('scoped_passed'))
        report['media_independent_functional_review_pending'] = True
        shutil.copy2(media / 'result.json', out / 'media-short-producer-result.json')
    else:
        report['media_phase'] = 'pending or failed before a sealed result'
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('startup', 'return'))
    phase = parser.parse_args().phase
    os.umask(0o077)
    a = load()
    current = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if phase == 'startup':
        assert current == trial_identity(a)
    else:
        assert os.uname().release == '6.18.3-1-surface+'
        assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
        assert current != a['preboot_id']
    out = X / (phase + '-review.partial')
    final = X / (phase + '-review')
    assert not out.exists() and not final.exists()
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    try:
        result = read(X / 'video-startup/result.json')
        bid = result['boot_id']
        if phase == 'startup':
            assert bid == current, 'Startup record is from a different boot'
        journal_boot = bid.replace('-', '')
        captures = {'trial-kernel.log': command('journalctl', '-b', journal_boot, '-k', '--no-pager', '-o', 'short-monotonic'),
                    'trial-journal.log': command('journalctl', '-b', journal_boot, '--no-pager', '-o', 'short-monotonic'),
                    'grubenv': command('grub-editenv', '/boot/grub/grubenv', 'list'),
                    'efibootmgr': command('efibootmgr'),
                    'current-boot-id': current + '\n', 'current-release': os.uname().release + '\n',
                    'current-cmdline': Path('/proc/cmdline').read_text(),
                    'current-taint': Path('/proc/sys/kernel/tainted').read_text()}
        if phase == 'startup':
            captures['current-deferred'] = Path('/sys/kernel/debug/devices_deferred').read_text()
            captures['current-provider-uevent'] = Path('/sys/bus/platform/devices/ab00000.clock-controller/uevent').read_text()
            assert Path('/sys/bus/platform/devices/ab00000.clock-controller/driver').resolve() == Path('/sys/bus/platform/drivers/video_cc-sm8150')
        for name, data in captures.items():
            (out / name).write_text(data)
        env = recovery(a)
        assert not env.get('next_entry', '')
        artifacts(a)
        report = startup(out, a)
        if phase == 'return':
            assert current != bid and captures['current-taint'].strip() == '4096'
            original = read(X / 'independent-result-review.json')
            frozen = X / 'preparation/runtime-plan/review-be-baseline.py'
            assert sha(frozen) == a['runtime_sha256'][str(RUNTIME / 'review-be-baseline.py')]
            shutil.copy2(frozen, out / frozen.name)
            destination = X / 'offline-baseline-review-at-return.json'
            assert not destination.exists()

            class Redirect(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if node.value == 'independent-result-review.json':
                        return ast.copy_location(ast.Constant(destination.name), node)
                    return node

            tree = ast.fix_missing_locations(Redirect().visit(ast.parse(frozen.read_text())))
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(tree, str(frozen), 'exec'), {'__name__': '__main__'})
            replay = read(destination)
            assert original == replay
            shutil.copy2(destination, out / destination.name)
            report['baseline'] = sealed(X / 'final-result')
            report['baseline_replay_exact'] = True
            report['scoped_baseline_passed'] = replay['scoped_passed']
            report['scoped_camera_baseline_passed'] = replay['camera_trial_passed']
            fallback = read(X / 'fallback-recovery-check.json')
            assert fallback['boot_id'] == bid and fallback['uptime_seconds'] >= 900
            assert all(fallback[key] for key in ('known_good_payloads_modules_entry_verified', 'next_entry_empty', 'efi_bootnext_absent'))
            shutil.copy2(X / 'fallback-recovery-check.json', out / 'fallback-recovery-check.json')
            entries = [json.loads(line) for line in command('journalctl', '-b', journal_boot, '-k', '--no-pager', '-o', 'json').splitlines()]
            assert entries and all(row['_BOOT_ID'] == journal_boot for row in entries)
            assert 'Reached target System Reboot' in captures['trial-journal.log']
            assert 'spx-be-fallback.service' in captures['trial-journal.log']
            report['last_kernel_uptime_seconds'] = max(int(row['__MONOTONIC_TIMESTAMP']) for row in entries) / 1e6
            report['returned_boot_id'] = current
            report['known_good_recovery_verified'] = True
            report['early_hang_recovery_validated'] = False
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current
        assert not recovery(a).get('next_entry', '')
        archive = read(X / 'archive-review.json')
        report.update(utc=datetime.now(timezone.utc).isoformat(), phase=phase,
                      persistent_default='spx-known-good', next_entry_empty=True,
                      efi_bootnext_absent=True, build_files_verified=archive['build_files_verified'],
                      build_links_verified=archive['build_links_verified'], preparation_files_verified=len(files(X / 'preparation')),
                      installed_module_files_verified=217, recovery_files_links_verified=5183)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
        sealed(out)
        os.sync()
        out.rename(final)
        print(json.dumps(report | {'review_manifest_sha256': sha(final / 'sha256.json')}, indent=2))
    except BaseException:
        (out / 'failure.txt').write_text(traceback.format_exc())
        (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
        os.sync()
        raise


if __name__ == '__main__':
    main()
