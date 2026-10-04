#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Schedule BE's frozen one-use checker; it selects only after final checks pass."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'] == 'prepared BE; no boot selection'
    assert not (g.X / 'reboot-requested').exists()
    assert not (g.X / 'reboot-schedule.json').exists()
    records = g.X / 'preboot-records'
    expected = json.loads((records / 'sha256.json').read_text())
    assert g.files(records) == expected | {'sha256.json': g.sha(records / 'sha256.json')}
    assert g.sha(Path(__file__)) == expected['queue-be-once.py']
    checker = g.X / 'reboot-check.py'
    assert g.sha(checker) == expected['reboot-check.py']
    assert checker.read_bytes() == (g.X / 'preparation/runtime-plan/be-reboot-check.py').read_bytes()
    current = g.preboot(a)
    native = json.loads((records / 'native-continuation.json').read_text())
    assert native['boot_id'] == current['boot_id']
    assert native['selected_metadata']['resumeOnDaemonStart']
    assert native['selected_metadata']['resumeOnDaemonStartMessage'] == 'continue'
    os.kill(native['selected_metadata']['hostPid'], 0)
    assert not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
    wrapper = g.X / 'reboot-launch.py'
    with wrapper.open('x') as stream:
        stream.write('import json, subprocess\nfrom pathlib import Path\n'
            'root = Path(' + repr(str(g.X)) + ')\n'
            'checker = root / "reboot-check.py"\n'
            'with (root / "reboot.stdout").open("xb") as out, (root / "reboot.stderr").open("xb") as err:\n'
            '    result = subprocess.run(["/usr/bin/python3", str(checker)], stdout=out, stderr=err)\n'
            'with (root / "reboot-exec-return.json").open("x") as stream:\n'
            '    json.dump({"exit_code": result.returncode, "checker": str(checker)}, stream)\n'
            '    stream.write("\\n")\n'
            'raise SystemExit(result.returncode)\n')
    shutil.copy2(__file__, g.X / Path(__file__).name)
    unit = 'spx-trial-20261004be-reboot'
    argv = ['systemd-run', '--unit=' + unit, '--on-active=30s',
            '--property=TimeoutStartSec=600', '/usr/bin/python3', str(wrapper)]
    result = subprocess.run(argv, capture_output=True, check=True, timeout=30)
    (g.X / 'reboot-schedule.stdout').write_bytes(result.stdout)
    (g.X / 'reboot-schedule.stderr').write_bytes(result.stderr)
    assert g.command('systemctl', 'is-active', unit + '.timer') == 'active'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current['boot_id']
    env = dict(line.split('=', 1) for line in g.command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert env.get('saved_entry') == 'spx-known-good' and not env.get('next_entry', '')
    record = dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=current['boot_id'],
        entry=a['entry'], scheduled_once=True, checked_handoff_timer_active=True,
        initial_delay_seconds=30, unit=unit, checker_sha256=g.sha(checker),
        wrapper_sha256=g.sha(wrapper), freeze_manifest_sha256=g.sha(records / 'sha256.json'),
        persistent_default='spx-known-good', selection_deferred_to_frozen_checker=True,
        next_entry_empty_at_schedule=True, hardware_result_available=False)
    with (g.X / 'reboot-schedule.json').open('x') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')
    os.sync()
    print(json.dumps(record, indent=2), flush=True)


if __name__ == '__main__':
    main()
