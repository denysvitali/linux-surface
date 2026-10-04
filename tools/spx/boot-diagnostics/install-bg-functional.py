#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install BG's functional payload and bounded return, without selecting a boot."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bg_prepare', HERE / 'prepare-bg-functional.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == p.BOOT_ID
    r = p.recovery()
    prepared = json.loads((p.OUT / 'prepared.json').read_text())
    assert prepared['preboot_id'] == p.BOOT_ID and prepared['release'] == p.RELEASE
    assert not prepared['venus_trial']
    boot = Path('/boot/spx-trial-20261004bg')
    modules = Path('/usr/lib/modules') / p.RELEASE
    assert not boot.exists() and not modules.exists() and not (p.OUT / 'installed.json').exists()
    payloads = {'vmlinuz': p.STAGE / 'vmlinuz', 'initramfs.img': p.OUT / 'initramfs.img', 'spx.dtb': p.OUT / 'spx.dtb'}
    expected = dict(zip(payloads, (prepared['boot_payloads'][k] for k in ('vmlinuz', 'initramfs', 'dtb'))))
    for name, source in payloads.items():
        assert p.sha(source) == expected[name]
    space = os.statvfs('/boot')
    assert space.f_bavail * space.f_frsize > sum(f.stat().st_size for f in payloads.values()) + 1048576
    unit_dir = Path('/etc/systemd/system')
    service = '''[Unit]
Description=Capture mainline functional test and return to known-good
ConditionKernelCommandLine=spx_attempt=20261004bg
After=local-fs.target
RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -B /usr/local/lib/spx-boot-diagnostics/functional-return.py
TimeoutStartSec=120
'''
    timer = '''[Unit]
Description=Bounded mainline functional test return
ConditionKernelCommandLine=spx_attempt=20261004bg

[Timer]
OnBootSec=900
AccuracySec=1
Unit=spx-functional-return.service

[Install]
WantedBy=timers.target
'''
    for name, text in [('spx-functional-return.service', service), ('spx-functional-return.timer', timer)]:
        target = unit_dir / name
        assert not target.exists()
        target.write_text(text)
        target.chmod(0o644)
    helper = Path('/usr/local/lib/spx-boot-diagnostics/functional-return.py')
    assert not helper.exists()
    shutil.copy2(HERE / 'functional-return.py', helper)
    helper.chmod(0o755)
    subprocess.run(['systemd-analyze', 'verify', str(unit_dir / 'spx-functional-return.service'),
                    str(unit_dir / 'spx-functional-return.timer')], check=True, timeout=30)
    shutil.copytree(p.OUT / 'module-root/lib/modules' / p.RELEASE, modules, symlinks=True)
    boot.mkdir()
    for name, source in payloads.items():
        shutil.copy2(source, boot / name)
        assert p.sha(boot / name) == expected[name]
    shutil.copy2('/boot/grub/custom.cfg', p.OUT / 'previous-custom.cfg')
    shutil.copy2(p.OUT / 'entry.cfg', '/boot/grub/custom.cfg.bg-new')
    os.replace('/boot/grub/custom.cfg.bg-new', '/boot/grub/custom.cfg')
    subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)
    shutil.copy2(p.OLD / 'working-recovery.json', p.OUT / 'working-recovery.json')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'spx-functional-return.timer'], check=True)
    assert subprocess.check_output(['systemctl', 'is-enabled', 'spx-functional-return.timer'], text=True).strip() == 'enabled'
    p.recovery()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == p.BOOT_ID
    installed = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=p.BOOT_ID, release=p.RELEASE,
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=p.REPO, text=True).strip(),
        boot_payloads=expected, persistent_default='spx-known-good', next_entry_empty=True,
        return_timer_seconds=900, installed=True, boot_selected=False)
    (p.OUT / 'installed.json').write_text(json.dumps(installed, indent=2) + '\n')
    os.sync()
    print('BG installed with900s return; known-good default retained, no selection', flush=True)


if __name__ == '__main__':
    main()
