#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Collect actual BD Venus startup, memory and advertised formats with provenance."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from bd_boot_guard import X, load, trial_identity, files, sha


def main():
    os.umask(0o077)
    a = load()
    boot = trial_identity(a)
    start = float(Path('/proc/uptime').read_text().split()[0])
    assert 60 <= start < 240, start
    root = X / 'video-startup'
    root.mkdir(mode=0o700)
    commands = []

    def capture(label, argv, timeout=30):
        t = time.monotonic()
        try:
            result = subprocess.run(argv, capture_output=True, timeout=timeout)
            stdout, stderr, rc = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, rc = error.stdout or b'', error.stderr or b'', 124
        except FileNotFoundError as error:
            stdout, stderr, rc = b'', str(error).encode(), 127
        (root / (label + '.stdout')).write_bytes(stdout)
        (root / (label + '.stderr')).write_bytes(stderr)
        commands.append(dict(label=label, argv=argv, exit_code=rc,
                             seconds=round(time.monotonic() - t, 3)))
        return stdout.decode(errors='replace')

    capture('kernel', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'])
    capture('modules', ['lsmod'])
    capture('iomem', ['cat', '/proc/iomem'])
    capture('interrupts', ['cat', '/proc/interrupts'])
    capture('genpd', ['cat', '/sys/kernel/debug/pm_genpd/pm_genpd_summary'])
    capture('clocks', ['cat', '/sys/kernel/debug/clk/clk_summary'])
    capture('deferred', ['cat', '/sys/kernel/debug/devices_deferred'])
    capture('failed-units', ['systemctl', '--failed', '--no-pager'])
    capture('grubenv', ['grub-editenv', '/boot/grub/grubenv', 'list'])
    capture('firmware-hash', ['sha256sum', '/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn'])
    fdt = Path('/sys/firmware/fdt')
    if fdt.exists():
        shutil.copyfile(fdt, root / 'actual-fdt.dtb')
    def snapshot(pattern):
        records = []
        for path in sorted(Path('/sys/bus/platform/devices').glob(pattern)):
            row = dict(path=str(path), real_path=str(path.resolve()))
            for name in ('driver', 'iommu_group'):
                target = path / name
                row[name] = str(target.resolve()) if target.is_symlink() else None
            for name in ('modalias', 'power/runtime_status', 'power/runtime_active_time',
                         'power/runtime_suspended_time'):
                target = path / name
                try:
                    row[name] = target.read_text().strip()
                except (OSError, ValueError) as error:
                    row[name] = dict(error=str(error))
            records.append(row)
        return records

    devices = snapshot('*aa00000*')
    providers = snapshot('*ab00000*')
    for row in providers:
        assert row['modalias'] == 'of:Nclock-controllerT(null)Cqcom,sc8180x-videoccCqcom,sm8150-videocc'
    videos = []
    for path in sorted(Path('/sys/class/video4linux').glob('video*')):
        name = (path / 'name').read_text().strip()
        row = dict(device='/dev/' + path.name, name=name, sysfs=str(path.resolve()))
        if 'venus' in name.casefold():
            for suffix, options in [('capabilities', ['--all']),
                                    ('capture-formats', ['--list-formats-ext']),
                                    ('output-formats', ['--list-formats-out-ext'])]:
                capture(path.name + '-' + suffix, ['v4l2-ctl', '-d', row['device']] + options, 15)
        videos.append(row)
    assert trial_identity(a) == boot
    parameters = {}
    for name in ('spx_pas_diag', 'spx_pas_area_diag'):
        path = Path('/sys/module/qcom_scm/parameters') / name
        parameters[name] = dict(value=path.read_text().strip(), mode=oct(path.stat().st_mode & 0o777))
        assert parameters[name] == dict(value='Y', mode='0o400')
    (root / 'pas-parameters.json').write_text(json.dumps(parameters, indent=2) + '\n')
    result = dict(utc=datetime.now(timezone.utc).isoformat(), attempt=a['attempt'], boot_id=boot,
                  release=os.uname().release, cmdline=Path('/proc/cmdline').read_text().strip(),
                  uptime_start=start, uptime_end=float(Path('/proc/uptime').read_text().split()[0]),
                  kernel_taint=Path('/proc/sys/kernel/tainted').read_text().strip(),
                  platform_devices=devices, clock_provider_devices=providers,
                  video_nodes=videos, commands=commands,
                  pas_parameters=parameters, memory_area_result_uninterpreted=True, physical_firmware_allocation_passed=False, firmware_authentication_passed=False,
                  media_acceptance_passed=False,
                  limits=['Raw startup and advertised formats only; review original logs/FDT before conclusions.',
                          'No decode/encode/stream, secure-media, watchdog, sustained or suspend test runs.'])
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (root / 'sha256.json').write_text(json.dumps(files(root), indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(boot_id=boot, files=len(files(root)), manifest_sha256=sha(root / 'sha256.json'))))


if __name__ == '__main__':
    main()
