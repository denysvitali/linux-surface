#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Review BA's PAS memory-setup failure and actual guarded return without rearming it."""
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
from ba_boot_guard import X, RUNTIME, load, recovery, artifacts, files, sha, trial_identity


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
    result = read(X / 'video-startup/result.json')
    assert result['attempt'] == a['attempt'] and result['release'] == a['release']
    assert result['boot_id'] != a['preboot_id'] and 60 <= result['uptime_start'] < 240
    assert result['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261004ba/vmlinuz'] + a['cmdline'].split()
    assert result['kernel_taint'] == '0'
    assert all(row['exit_code'] == 0 for row in result['commands'])
    assert len(result['platform_devices']) == 1 and not result['video_nodes']
    device = result['platform_devices'][0]
    assert device['driver'] is None and device['power/runtime_status'] == 'unsupported'
    assert device['modalias'] == 'of:Nvideo-codecT(null)Cqcom,sc8180x-venus'
    provider = result['clock_provider_devices']
    assert len(provider) == 1 and provider[0]['driver'] == '/sys/bus/platform/drivers/video_cc-sm8150'
    assert provider[0]['power/runtime_status'] == 'suspended'
    config = (X / 'build/config-extracted').read_text()
    assert 'CONFIG_SM_VIDEOCC_8150=m' in config.splitlines()
    parser = X / 'build/integration-boot/video_dt_contract.py'
    shutil.copy2(parser, out / parser.name)
    spec = importlib.util.spec_from_file_location('ba_video_dt_contract', parser)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    references = contract.validate((X / 'video-startup/actual-fdt.dtb').read_bytes())
    (out / 'actual-provider-contracts.json').write_text(json.dumps(references, indent=2) + '\n')
    kernel = (X / 'video-startup/kernel.stdout').read_text()
    assert 'could not get #interconnect-cells' not in kernel
    assert 'qcom-venus aa00000.video-codec: non legacy binding' in kernel
    firmware = 'qcom/msft/surface/pro-x-sq2/qcvss8180.mbn'
    assert f'error -22 setting up firmware {firmware}' in kernel
    assert f'failed to load video firmware {firmware} (-22)' in kernel
    assert 'qcom-venus aa00000.video-codec: probe with driver qcom-venus failed with error -22' in kernel
    assert 'initializing firmware ' + firmware not in kernel
    allocations = re.findall(r'OF: reserved mem: 0x([0-9a-f]+)\.\.0x([0-9a-f]+) \(5120 KiB\) nomap non-reusable video-firmware', kernel)
    assert len(allocations) == 1
    base, end = (int(value, 16) for value in allocations[0])
    assert base == 0xfe500000 and end == 0xfe9fffff
    source_rows = read(X / 'build/source-files.json')
    for name in ('drivers/soc/qcom/mdt_loader.c', 'drivers/media/platform/qcom/venus/firmware.c',
                 'drivers/firmware/qcom/qcom_scm.c', 'drivers/firmware/qcom/qcom_pas.c'):
        source = Path('/home/dvitali/Documents/git/linux-surface-next') / name
        assert sha(source) == source_rows[name]['sha256']
        shutil.copy2(source, out / source.name)
    loader = (out / 'mdt_loader.c').read_text()
    assert 'ret = qcom_pas_mem_setup(pas_id, mem_phys, max_addr - min_addr);' in loader
    assert 'error %d setting up firmware %s' in loader
    assert 'ret = qcom_pas_init_image(pas_id, metadata, metadata_len, ctx);' in loader
    media = read(X / 'media-not-run.json')
    assert media['boot_id'] == result['boot_id'] and media['hardware_codec_used'] is False
    assert media['video_startup_sha256'] == sha(X / 'video-startup/result.json')
    shutil.copy2(X / 'media-not-run.json', out / 'media-not-run.json')
    shutil.copy2(X / 'build/config-extracted', out / 'candidate.config')
    return dict(boot_id=result['boot_id'], release=result['release'],
        startup=sealed(X / 'video-startup'), provider=sealed(X / 'camera-provider-result'),
        initial_camera=sealed(X / 'camera-control-result'),
        actual_provider_declared_argument_contracts_verified=True,
        original_interconnect_parse_failure_absent=True,
        firmware_reservation_base=hex(base), firmware_reservation_end=hex(end),
        firmware_load_failure_stage='qcom_pas_mem_setup', firmware_load_errno=-22,
        pas_initialization_returned_zero_inferred_from_compiled_control_flow=True,
        mem_setup_secure_result_vs_transport_or_clock_errno_unresolved=True,
        firmware_authentication_passed=False, hfi_startup_passed=False,
        media_acceptance_passed=False, hardware_acceptance_closed=False)


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
            frozen = X / 'runtime-plan-v2/review-ba-baseline.py'
            assert sha(frozen) == a['runtime_sha256'][str(RUNTIME / 'review-ba-baseline.py')]
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
            assert 'spx-ba-fallback.service' in captures['trial-journal.log']
            report['last_kernel_uptime_seconds'] = max(int(row['__MONOTONIC_TIMESTAMP']) for row in entries) / 1e6
            report['returned_boot_id'] = current
            report['known_good_recovery_verified'] = True
            report['early_hang_recovery_validated'] = False
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current
        assert not recovery(a).get('next_entry', '')
        report.update(utc=datetime.now(timezone.utc).isoformat(), phase=phase,
                      persistent_default='spx-known-good', next_entry_empty=True,
                      efi_bootnext_absent=True, build_files_verified=972,
                      build_links_verified=272, preparation_files_verified=625,
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
