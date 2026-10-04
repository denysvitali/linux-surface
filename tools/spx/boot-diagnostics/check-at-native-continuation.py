#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Inspect only this Happy session's native continuation fields; no settings writes."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    assert not args.output.exists()
    session = os.environ['HAPPY_SESSION_ID']
    result = subprocess.run(['happy', 'debug', 'session', session, '--json',
                             '--no-messages', '--no-diagnostics'],
                            capture_output=True, text=True, check=True, timeout=30)
    fields = {}
    for key in ('codexThreadId', 'hostPid', 'lifecycleState', 'resumeOnDaemonStart',
                'resumeOnDaemonStartMessage', 'startedBy', 'startedFromDaemon'):
        values = re.findall(r'"' + key + r'"\s*:\s*(true|false|[0-9]+|"[^"\n]*")', result.stdout)
        assert len(values) == 1, key
        fields[key] = json.loads(values[0])
    assert fields['startedBy'] == 'daemon' and fields['startedFromDaemon']
    assert fields['lifecycleState'] == 'running'
    assert fields['resumeOnDaemonStart'] and fields['resumeOnDaemonStartMessage'] == 'continue'
    listing = json.loads(subprocess.check_output(['happy', 'daemon', 'list', '--json'],
                                                 text=True, timeout=30))
    matches = [x for x in listing if x.get('happySessionId') == session]
    assert len(matches) == 1 and matches[0]['pid'] == fields['hostPid']
    assert matches[0]['startedBy'] == 'daemon'
    os.kill(fields['hostPid'], 0)
    marker = Path('/home/dvitali/.local/state/spx-port/resume-armed.json')
    assert not marker.exists()
    fields.update({'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'happySessionId': session, 'checked_wall_time': time.time(),
                   'legacy_resume_marker_absent': True, 'settings_modified': False})
    with args.output.open('x') as file:
        file.write(json.dumps(fields, indent=2) + '\n')
    print('Current daemon session/thread continuation verified; no settings changed')


if __name__ == '__main__':
    main()
