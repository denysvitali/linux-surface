#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve BF's actual one-use handoff and read-only native session witness."""
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
import bf_boot_guard as g


def main():
    os.umask(0o077)
    a = g.load()
    bid = g.trial_identity(a)
    out = g.X / 'actual-handoff-records.partial'
    final = g.X / 'actual-handoff-records'
    assert not out.exists() and not final.exists()
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    try:
        for name in ('attempt.json', 'reboot-check.py', 'reboot-check-passed.json',
                     'reboot-exec-return.json', 'reboot-requested', 'reboot.stdout',
                     'reboot.stderr', 'reboot-schedule.json'):
            shutil.copy2(g.X / name, out / name)
        check = json.loads((out / 'reboot-check-passed.json').read_text())
        assert check['preboot']['boot_id'] == a['preboot_id']
        assert check['entry'] == a['entry']
        assert check['checker_sha256'] == g.sha(out / 'reboot-check.py')
        assert json.loads((out / 'reboot-exec-return.json').read_text())['exit_code'] == 0
        assert g.sha(out / 'reboot-check.py') == g.sha(g.X / 'preboot-records/reboot-check.py')
        for kind, options in (('outgoing-kernel', ['-k']), ('outgoing-journal', [])):
            argv = ['journalctl', '-b', a['preboot_id'].replace('-', '')] + options + ['--no-pager', '-o', 'short-monotonic']
            result = subprocess.run(argv, capture_output=True, check=True, timeout=60)
            (out / (kind + '.stdout')).write_bytes(result.stdout)
            (out / (kind + '.stderr')).write_bytes(result.stderr)
        journal = (out / 'outgoing-journal.stdout').read_text()
        assert 'Reached target System Reboot' in journal
        assert 'spx-trial-20261004bf-reboot.service' in journal
        native_before = json.loads((g.X / 'preboot-records/native-continuation.json').read_text())
        argv = native_before['read_only_debug_argv']
        native = subprocess.run(argv, capture_output=True, check=True, timeout=30)
        (out / 'native.stdout').write_bytes(native.stdout)
        (out / 'native.stderr').write_bytes(native.stderr)
        data = native.stdout.decode()
        selected = {}
        for key, expected in native_before['selected_metadata'].items():
            matches = re.findall(r'"' + re.escape(key) + r'"\s*:\s*("[^"\n]*"|true|false|\d+)', data)
            assert len(matches) == 1, (key, len(matches))
            selected[key] = json.loads(matches[0])
            if key != 'hostPid':
                assert selected[key] == expected, key
        os.kill(selected['hostPid'], 0)
        assert not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
        (out / 'native-after-boot.json').write_text(json.dumps(selected, indent=2) + '\n')
        env = g.recovery(a)
        assert not env.get('next_entry', '')
        assert env.get('spx_diag_attempt') == a['attempt']
        assert env.get('spx_diag_stage') == 'handoff-ready'
        (out / 'grubenv.json').write_text(json.dumps(env, indent=2) + '\n')
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
        report = dict(boot_id=bid, release=os.uname().release, outgoing_boot_id=a['preboot_id'],
            normal_outgoing_shutdown_verified=True, one_use_checker_exit=0,
            selection_consumed=True, persistent_default='spx-known-good',
            efi_bootnext_absent=True, recovery_artifacts_verified=True,
            native_same_thread_metadata_verified=True, hardware_acceptance_closed=False)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        expected = g.files(out)
        (out / 'sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
        assert g.files(out) == expected | {'sha256.json': g.sha(out / 'sha256.json')}
        os.sync()
        out.rename(final)
        print(json.dumps(report | {'manifest_sha256': g.sha(final / 'sha256.json')}, indent=2))
    except BaseException:
        (out / 'failure.txt').write_text(traceback.format_exc())
        (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
        os.sync()
        raise


if __name__ == '__main__':
    main()
