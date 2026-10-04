#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze BC's reviewed outgoing handoff while keeping selection empty."""
import ast
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bc_boot_guard as g

SRC = g.REPO / 'tools/spx/boot-diagnostics'


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'] == 'prepared BC; no boot selection'
    current = g.preboot(a)
    reviewed = json.loads((g.X / 'independent-deployment-review.json').read_text())
    assert reviewed['boot_id'] == current['boot_id'] and reviewed['helpers_exact_plan'] == 10
    assert reviewed['units_exact_plan'] == 12 and reviewed['timers_enabled']
    native = json.loads((g.X / 'native-continuation.json').read_text())
    assert native['boot_id'] == current['boot_id']
    selected = native['selected_metadata']
    assert selected['codexThreadId'] == '01a0fecc-e7bc-7953-b371-410bb330a8fb'
    assert selected['resumeOnDaemonStart'] and selected['resumeOnDaemonStartMessage'] == 'continue'
    assert selected['startedBy'] == 'daemon' and selected['startedFromDaemon']
    assert selected['lifecycleState'] == 'running' and 0 <= time.time() - native['checked_wall_time'] < 300
    os.kill(selected['hostPid'], 0)
    assert native['retired_fallback_marker_absent'] and not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
    assert not (g.X / 'reboot-requested').exists()
    checker = g.X / 'build/runtime-plan/bc-reboot-check.py'
    assert checker.read_bytes() == (SRC / 'bc-reboot-check.py').read_bytes()
    ast.parse(checker.read_text())
    shutil.copy2(checker, g.X / 'reboot-check.py')
    temporary, final = g.X / 'preboot-records.partial', g.X / 'preboot-records'
    assert not temporary.exists() and not final.exists()
    temporary.mkdir(mode=0o700)
    inputs = {name: g.X / name for name in ('attempt.json', 'deployed-preboot-review.json',
        'independent-deployment-review.json', 'native-continuation.json',
        'native-metadata-parser-failure.json', 'reboot-check.py', 'working-recovery.json')}
    inputs |= {name: g.REPO / name for name in ('LOCAL-PROGRESS.md', 'PORT-CHECKLIST.md')}
    inputs |= {name: SRC / name for name in ('PREPARED-20261004bc.md', 'freeze-bc-handoff.py',
        'review-bc-deployment.py', 'review-bc-result.py')}
    expected = {name: g.sha(path) for name, path in inputs.items()}
    for name, path in inputs.items():
        shutil.copy2(path, temporary / name)
    assert g.files(temporary) == expected
    (temporary / 'freeze-current.json').write_text(json.dumps(current, indent=2) + '\n')
    (temporary / 'sha256.json').write_text(json.dumps(g.files(temporary), indent=2) + '\n')
    assert g.files(temporary) == json.loads((temporary / 'sha256.json').read_text()) | {
        'sha256.json': g.sha(temporary / 'sha256.json')}
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current['boot_id']
    assert not g.recovery(a).get('next_entry', '')
    os.sync()
    temporary.rename(final)
    print(json.dumps(dict(boot_id=current['boot_id'], frozen_files=len(expected) + 1,
        manifest_sha256=g.sha(final / 'sha256.json'), checker_sha256=g.sha(g.X / 'reboot-check.py'),
        native_same_thread_resume_verified=True, boot_selected=False), indent=2), flush=True)


if __name__ == '__main__':
    main()
