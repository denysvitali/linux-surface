#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise AU's actual boot/selection guard and frozen records with synthetic inputs."""
import json
from pathlib import Path
import tempfile

import au_boot_guard as guard


def rejected(fn):
    try:
        fn()
    except (AssertionError, FileNotFoundError, KeyError):
        return
    raise AssertionError('Invalid guard state accepted')


def main():
    a = {'preboot_id': 'synthetic-outgoing', 'preboot_release': '6.18.3-1-surface+',
         'preboot_cmdline': 'spx_boot=known-good', 'preboot_taint': '4096'}
    c = {'boot_id': a['preboot_id'], 'release': a['preboot_release'],
         'cmdline': a['preboot_cmdline'], 'taint': '4096', 'touch': 'ready', 'wifi_connected': True}
    env = {'saved_entry': 'spx-known-good', 'next_entry': ''}
    guard.check_state(a, c, env, '')
    guard.check_state(a, c, env | {'next_entry': 'AU'}, 'AU')
    bad = [{'boot_id': 'other'}, {'release': 'other'}, {'cmdline': 'other'},
           {'taint': '0'}, {'taint': '4608'}, {'touch': 'not-ready'}, {'wifi_connected': False}]
    for change in bad:
        rejected(lambda: guard.check_state(a, c | change, env, ''))
    rejected(lambda: guard.check_state(a, c, env | {'saved_entry': 'AU'}, ''))
    rejected(lambda: guard.check_state(a, c, env | {'next_entry': 'other'}, 'AU'))
    rejected(lambda: guard.check_state(a, c, env, 'AU'))
    with tempfile.TemporaryDirectory(prefix='spx-au-synthetic-guard-') as tmp:
        guard.X = Path(tmp)
        guard.RUNTIME = Path(__file__).resolve().parent
        root = guard.X / 'prequeue-records'
        root.mkdir()
        original = a | {'attempt': '20261003au', 'release': guard.RELEASE,
                        'state': 'prepared AU; no boot selection', 'runtime_sha256': {'fixture': 'hash'}}
        for n in ('attempt.json', 'installed-review.json', 'service-context-review.json',
                  'native-continuation-review.json', 'working-recovery.json', 'entry.cfg',
                  'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md', 'freeze-complete.json'):
            data = original if n == 'attempt.json' else {}
            if n == 'service-context-review.json':
                data = {'full_preboot_passed': True, 'sudo_uid_absent': True,
                        'boot_id': a['preboot_id'], 'guard_sha256': guard.sha(guard.RUNTIME / 'au_boot_guard.py')}
            if n == 'freeze-complete.json':
                data = {'inputs_validated_before_creation': True, 'preboot_checked_after_copy': True,
                        'boot_id': a['preboot_id']}
            (root / n).write_text(json.dumps(data))
            if n not in ('attempt.json', 'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md', 'freeze-complete.json'):
                (guard.X / n).write_bytes((root / n).read_bytes())
        (root / 'sha256.json').write_text(json.dumps(guard.files(root)))
        guard.frozen_prequeue(original)
        for key in original:
            if key != 'state':
                rejected(lambda: guard.frozen_prequeue(original | {key: 'wrong'}))
        (root / 'LOCAL-PROGRESS.md').write_text('changed')
        rejected(lambda: guard.frozen_prequeue(original))
    print(json.dumps({'synthetic_only': True, 'state_positive_cases': 2,
                      'state_negative_cases': len(bad) + 3, 'freeze_positive_cases': 1,
                      'freeze_negative_cases': len(original)}))


if __name__ == '__main__':
    main()
