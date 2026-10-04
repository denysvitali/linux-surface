#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check complete AX inputs before atomically publishing its prequeue freeze."""
import ast
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ax_boot_guard import X, load, preboot, files, sha, frozen_prequeue

SRC = Path('/home/dvitali/Documents/git/linux-surface-next/tools/spx/boot-diagnostics')
REPO = SRC.parents[2]


def main():
    os.umask(0o077)
    a = load()
    assert a['state'] == 'prepared AX; no boot selection'
    preboot(a)
    service = json.loads((X / 'service-context-review.json').read_text())
    assert service['full_preboot_passed'] and service['sudo_uid_absent']
    assert service['boot_id'] == a['preboot_id']
    native = json.loads((X / 'native-continuation-review.json').read_text())
    assert native['boot_id'] == a['preboot_id'] and native['startedBy'] == 'daemon'
    assert native['startedFromDaemon'] and native['lifecycleState'] == 'running'
    assert native['resumeOnDaemonStart'] and native['resumeOnDaemonStartMessage'] == 'continue'
    assert native['legacy_resume_marker_absent'] and not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
    assert 0 <= time.time() - native['checked_wall_time'] < 300
    os.kill(native['hostPid'], 0)
    for name, digest in json.loads((X / 'deployment-sources-sha256.json').read_text()).items():
        assert sha(SRC / name) == digest, name
    local = ('attempt.json', 'archive-review.json', 'installed-review.json',
             'service-context-review.json', 'native-continuation-review.json',
             'working-recovery.json', 'deployment-sources-sha256.json', 'build-sha256.json',
             'build-symlinks.json', 'criteria-test.log', 'gpu-core-test.log',
             'boot-guards-test.log', 'units-verify.log', 'entry.cfg')
    local += ('rtc-review-test.log', 'rtc-core-test.log', 'rtc-probe-review.json')
    inputs = {name: X / name for name in local}
    inputs |= {name: REPO / name for name in ('PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md')}
    inputs |= {name: SRC / name for name in ('PREPARED-20261003ax.md', 'freeze-ax-prequeue.py',
                                          'queue-ax-once.py', 'check-ax-service-context.py')}
    for name, path in inputs.items():
        assert path.is_file() and not path.is_symlink(), name
        if name.endswith('.py'):
            ast.parse(path.read_text())
    expected = {name: sha(path) for name, path in inputs.items()}
    temporary, final = X / 'prequeue-records.new', X / 'prequeue-records'
    assert not temporary.exists() and not final.exists()
    temporary.mkdir(mode=0o700)
    for name, path in inputs.items():
        shutil.copy2(path, temporary / name)
    assert files(temporary) == expected
    (temporary / 'outgoing-snapshot-manifest-sha256').write_text(sha(X / 'preboot-snapshot/sha256.json') + '\n')
    preboot(a)
    (temporary / 'freeze-complete.json').write_text(json.dumps({
        'attempt': a['attempt'], 'boot_id': a['preboot_id'],
        'inputs_validated_before_creation': True, 'preboot_checked_after_copy': True}, indent=2) + '\n')
    h = files(temporary)
    (temporary / 'sha256.json').write_text(json.dumps(h, indent=2) + '\n')
    assert files(temporary) == h | {'sha256.json': sha(temporary / 'sha256.json')}
    os.sync()
    temporary.rename(final)
    frozen_prequeue(a)
    os.sync()
    print(json.dumps({'files_verified': len(h), 'manifest_sha256': sha(final / 'sha256.json'),
                      'boot_selected': False}))


if __name__ == '__main__':
    main()
