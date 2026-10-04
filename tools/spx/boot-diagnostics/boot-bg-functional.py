#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Select the installed functional trial once, recheck state, and reboot."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bg_prepare', HERE / 'prepare-bg-functional.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def main():
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == p.BOOT_ID
    assert float(Path('/proc/uptime').read_text().split()[0]) > 120
    p.recovery()
    installed = json.loads((p.OUT / 'installed.json').read_text())
    prepared = json.loads((p.OUT / 'prepared.json').read_text())
    selected = p.OUT / 'selected.json'
    assert installed['installed'] and not selected.exists()
    for name, digest in installed['boot_payloads'].items():
        assert p.sha(Path('/boot/spx-trial-20261004bg') / name) == digest
    assert Path('/boot/grub/custom.cfg').read_bytes() == (p.OUT / 'entry.cfg').read_bytes()
    assert subprocess.check_output(['systemctl', 'is-enabled', 'spx-functional-return.timer'], text=True).strip() == 'enabled'
    assert subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=p.REPO, text=True).strip() == ''
    selected.write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=p.BOOT_ID,
        entry=prepared['entry'], source_commit=installed['source_commit'], select_once=True), indent=2) + '\n')
    subprocess.run(['grub-reboot', prepared['entry']], check=True)
    p.recovery(pending=prepared['entry'])
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == p.BOOT_ID
    os.sync()
    subprocess.run(['systemctl', 'reboot'], check=True)


if __name__ == '__main__':
    main()
