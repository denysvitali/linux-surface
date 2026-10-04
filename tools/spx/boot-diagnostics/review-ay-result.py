#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Review AY's blocked Venus startup and actual guarded return without rearming it."""
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
from ay_boot_guard import X, RUNTIME, load, recovery, artifacts, files, sha, trial_identity


def read(path):
    return json.loads(path.read_text())


def sealed(root):
    expected = read(root / 'sha256.json')
    assert files(root) == expected | {'sha256.json': sha(root / 'sha256.json')}, root
    return dict(files=len(expected), manifest_sha256=sha(root / 'sha256.json'))


def command(*args):
    return subprocess.check_output(args, text=True, timeout=180)


def startup(out, a):
    result = read(X / 'video-startup/result.json')
    assert result['attempt'] == a['attempt'] and result['release'] == a['release']
    assert result['boot_id'] != a['preboot_id'] and 60 <= result['uptime_start'] < 240
    assert result['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261003ay/vmlinuz'] + a['cmdline'].split()
    assert result['kernel_taint'] == '0'
    for row in result['commands']:
        assert row['exit_code'] == 0, row
    assert len(result['platform_devices']) == 1 and not result['video_nodes']
    device = result['platform_devices'][0]
    assert device['driver'] is None and device['power/runtime_status'] == 'unsupported'
    assert device['modalias'] == 'of:Nvideo-codecT(null)Cqcom,sc8180x-venus'
    assert 'supplier ab00000.clock-controller not ready' in (X / 'video-startup/deferred.stdout').read_text()
    config = (X / 'build/config-extracted').read_text()
    assert '# CONFIG_SM_VIDEOCC_8150 is not set' in config.splitlines()
    assert 'CONFIG_SM_GCC_8150=y' in config.splitlines() and 'CONFIG_QCOM_GDSC=y' in config.splitlines()
    module_names = read(X / 'build/module-sha256.json')
    assert not any('videocc-sm8150' in name for name in module_names)
    source = Path('/var/tmp/spx-mainline-trial-20261003ay/source')
    records = read(X / 'build/source-files.json')
    for name in ('drivers/clk/qcom/Kconfig', 'drivers/clk/qcom/Makefile',
                 'drivers/clk/qcom/videocc-sm8150.c'):
        assert sha(source / name) == records[name]['sha256']
        shutil.copy2(source / name, out / Path(name).name)
    driver = (source / 'drivers/clk/qcom/videocc-sm8150.c').read_text()
    assert '.compatible = "qcom,sm8150-videocc"' in driver
    assert 'obj-$(CONFIG_SM_VIDEOCC_8150) += videocc-sm8150.o' in (source / 'drivers/clk/qcom/Makefile').read_text()
    fdt = X / 'video-startup/actual-fdt.dtb'
    compat = command('fdtget', '-t', 's', str(fdt), '/soc@0/clock-controller@ab00000', 'compatible').split()
    assert compat == ['qcom,sc8180x-videocc', 'qcom,sm8150-videocc']
    kernel = (X / 'video-startup/kernel.stdout').read_text()
    allocations = re.findall(r'OF: reserved mem: 0x([0-9a-f]+)\.\.0x([0-9a-f]+) \(5120 KiB\) nomap non-reusable video-firmware', kernel)
    assert len(allocations) == 1
    base, end = (int(value, 16) for value in allocations[0])
    assert base % 0x100000 == 0 and end - base + 1 == 0x500000
    assert 0x80000000 <= base < end < 0x100000000
    shutil.copy2(X / 'build/config-extracted', out / 'candidate.config')
    return dict(boot_id=result['boot_id'], release=result['release'],
                startup=sealed(X / 'video-startup'), provider=sealed(X / 'camera-provider-result'),
                initial_camera=sealed(X / 'camera-control-result'),
                clock_provider_compatible=compat, clock_provider_config='disabled',
                video_startup_blocked_by_missing_clock_provider=True,
                firmware_reservation_base=hex(base), firmware_reservation_end=hex(end),
                early_physical_reservation_observed=True,
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
            assert not Path('/sys/bus/platform/devices/ab00000.clock-controller/driver').exists()
        for name, data in captures.items():
            (out / name).write_text(data)
        env = recovery(a)
        assert not env.get('next_entry', '')
        artifacts(a)
        report = startup(out, a)
        if phase == 'return':
            assert current != bid and captures['current-taint'].strip() == '4096'
            original = read(X / 'independent-result-review.json')
            frozen = X / 'deployment-preparation/review-ay-baseline.py'
            assert sha(frozen) == a['runtime_sha256'][str(RUNTIME / 'review-ay-baseline.py')]
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
            assert 'spx-ay-fallback.service' in captures['trial-journal.log']
            report['last_kernel_uptime_seconds'] = max(int(row['__MONOTONIC_TIMESTAMP']) for row in entries) / 1e6
            report['returned_boot_id'] = current
            report['known_good_recovery_verified'] = True
            report['early_hang_recovery_validated'] = False
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current
        assert not recovery(a).get('next_entry', '')
        report.update(utc=datetime.now(timezone.utc).isoformat(), phase=phase,
                      persistent_default='spx-known-good', next_entry_empty=True,
                      efi_bootnext_absent=True, build_files_verified=794,
                      build_links_verified=272, preparation_files_verified=209,
                      installed_module_files_verified=216, recovery_files_links_verified=5183)
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
