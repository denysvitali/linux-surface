#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Return only an actual AY startup trial after its bounded900s window."""
import json
import os
from pathlib import Path
import subprocess

from ay_boot_guard import X, RUNTIME, load, recovery, trial_identity


def main():
    os.umask(0o077)
    a = load()
    boot = trial_identity(a)
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    assert uptime >= 900
    assert not (X / 'fallback-recovery-check.json').exists()
    env = recovery(a)
    assert not env.get('next_entry', '')
    subprocess.run([str(RUNTIME / 'collect.sh')], check=True, timeout=120)
    assert trial_identity(a) == boot
    with (X / 'fallback-recovery-check.json').open('x') as stream:
        json.dump(dict(boot_id=boot, uptime_seconds=uptime,
                       known_good_payloads_modules_entry_verified=True,
                       next_entry_empty=True, efi_bootnext_absent=True), stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.sync()
    subprocess.run([str(RUNTIME / 'return.sh')], check=True, timeout=120)


if __name__ == '__main__':
    main()
