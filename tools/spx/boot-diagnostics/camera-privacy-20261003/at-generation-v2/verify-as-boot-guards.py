#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise real AS identity and complete-freeze guards without hardware mutations."""
import copy
import json
from pathlib import Path
import runpy
import tempfile


def rejected(fn):
    try:
        fn()
    except (AssertionError, FileNotFoundError):
        return
    raise AssertionError('Guard accepted an invalid input')


def main():
    root = Path(__file__).resolve().parent
    namespace = runpy.run_path(str(root / 'as_boot_guard.py'))
    check = namespace['check_state']
    a = {'preboot_id': 'outgoing-boot', 'preboot_release': 'outgoing-release',
         'preboot_cmdline': 'outgoing-cmdline'}
    current = {'boot_id': a['preboot_id'], 'release': a['preboot_release'],
               'cmdline': a['preboot_cmdline'], 'uptime': 620.0, 'taint': '0',
               'touch': 'ready', 'wifi_connected': True}
    env = {'saved_entry': 'spx-known-good', 'next_entry': ''}
    check(a, current, env, '')
    check(a, current, env | {'next_entry': 'spx-trial-20261003as'}, 'spx-trial-20261003as')
    for patch in ({'boot_id': 'different'}, {'release': 'different'}, {'cmdline': 'different'},
                  {'uptime': 619.9}, {'taint': '1'}, {'taint': '4608'}, {'taint': '4096'}, {'touch': 'not ready'}, {'wifi_connected': False}):
        rejected(lambda: check(a, current | patch, env, ''))
    for patch in ({'saved_entry': 'trial'}, {'next_entry': 'other-trial'}):
        rejected(lambda: check(a, current, env | patch, ''))
    rejected(lambda: check(a, current, env, 'spx-trial-20261003as'))
    freeze = namespace['frozen_prequeue']
    g = freeze.__globals__
    original_sha = namespace['sha']
    positive, negative = 0, 0
    with tempfile.TemporaryDirectory(prefix='spx-as-guard-') as temporary:
        x = Path(temporary)
        g['X'] = x
        guard = x / 'guard.py'
        guard.write_bytes((root / 'as_boot_guard.py').read_bytes())
        g['sha'] = lambda p: original_sha(guard if str(p) ==
            '/usr/local/lib/spx-boot-diagnostics/as_boot_guard.py' else p)
        fixture = a | {'attempt': '20261003as', 'entry': 'spx-trial-20261003as',
                       'release': '7.3.0-rc2-spx-mainline-20261003ar+',
                       'state': 'prepared AS; no boot selection', 'cmdline': 'target-cmdline',
                       'sha256': {'kernel': 'hash'}, 'recovery_sha256': {'recovery': 'hash'},
                       'runtime_sha256': {'helper': 'hash'}, 'build_manifest_sha256': 'hash',
                       'embedded_config_manifest_sha256': 'config-proof-hash',
                       'dt_input_manifest_sha256': 'dt-input-hash',
                       'parent_result_manifest_sha256': 'parent-result-hash',
                       'parent_post_result_manifest_sha256': 'parent-freeze-hash'}
        documents = {'attempt.json': fixture,
                     'installed-review.json': {'verified': True},
                     'service-context-review.json': {'full_preboot_passed': True,
                         'sudo_uid_absent': True, 'boot_id': fixture['preboot_id'],
                         'guard_sha256': original_sha(guard)},
                     'native-continuation-review.json': {'verified': True},
                     'working-recovery.json': {'verified': True}, 'entry.cfg': 'entry',
                     'PORT-CHECKLIST.md': 'checklist', 'LOCAL-PROGRESS.md': 'progress',
                     'freeze-complete.json': {'inputs_validated_before_creation': True,
                         'preboot_checked_after_copy': True, 'boot_id': fixture['preboot_id']}}

        def write(contents, extra=False):
            out = x / 'prequeue-records'
            out.mkdir(exist_ok=True)
            for p in out.iterdir():
                p.unlink()
            for name, obj in contents.items():
                value = obj if isinstance(obj, str) else json.dumps(obj)
                (out / name).write_text(value)
                if name in ('installed-review.json', 'service-context-review.json',
                            'native-continuation-review.json', 'working-recovery.json', 'entry.cfg'):
                    (x / name).write_text(value)
            hashes = namespace['files'](out)
            (out / 'sha256.json').write_text(json.dumps(hashes))
            if extra:
                (out / 'unexpected').write_text('unfrozen file')

        write(documents)
        freeze(fixture)
        positive += 1
        for key in ('entry', 'release', 'preboot_id', 'cmdline', 'build_manifest_sha256', 'embedded_config_manifest_sha256', 'dt_input_manifest_sha256',
                    'parent_result_manifest_sha256', 'parent_post_result_manifest_sha256'):
            rejected(lambda: freeze(fixture | {key: 'different'}))
            negative += 1
        for missing in ('attempt.json', 'PORT-CHECKLIST.md', 'freeze-complete.json'):
            modified = copy.deepcopy(documents)
            del modified[missing]
            write(modified)
            rejected(lambda: freeze(fixture))
            negative += 1
        for file, field in (('service-context-review.json', 'full_preboot_passed'),
                            ('service-context-review.json', 'sudo_uid_absent'),
                            ('freeze-complete.json', 'preboot_checked_after_copy')):
            modified = copy.deepcopy(documents)
            modified[file][field] = False
            write(modified)
            rejected(lambda: freeze(fixture))
            negative += 1
        write(documents, extra=True)
        rejected(lambda: freeze(fixture))
        negative += 1
        write(documents)
        (x / 'prequeue-records/entry.cfg').write_text('changed after freeze')
        rejected(lambda: freeze(fixture))
        negative += 1
    print(f'PASS real AS boot-state guard: 2 positive/12 negative; freeze guard: {positive} positive/{negative} negative; hardware actions=0')


if __name__ == '__main__':
    main()
