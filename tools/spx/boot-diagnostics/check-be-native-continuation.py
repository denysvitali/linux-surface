#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Record only native same-thread continuation fields before BE's one-use reboot."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g


def main():
    os.umask(0o077)
    a = g.load()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot == a['preboot_id'] == '433a78d6-9748-422f-a1a7-aac43c784a7d'
    before = json.loads((g.X.with_name('20261004bd') / 'native-continuation.json').read_text())
    argv = before['read_only_debug_argv']
    assert argv == ['runuser', '-u', 'dvitali', '--', '/home/dvitali/go/bin/happy', 'debug',
        'session', 'cff5ed9402541cd71f9d24e77', '--json', '--no-messages', '--no-diagnostics', '--no-process']
    start = time.monotonic()
    response = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=30)
    selected = {}
    for key, expected in before['selected_metadata'].items():
        values = re.findall(r'"' + re.escape(key) + r'"\s*:\s*("[^"\n]*"|true|false|\d+)', response.stdout)
        assert len(values) == 1, (key, len(values))
        selected[key] = json.loads(values[0])
        if key != 'hostPid':
            assert selected[key] == expected, key
    os.kill(selected['hostPid'], 0)
    args = (Path('/proc') / str(selected['hostPid']) / 'cmdline').read_bytes().split(b'\0')
    assert any(word == b'--happy-session-id' and args[index + 1] == b'cff5ed9402541cd71f9d24e77'
               for index, word in enumerate(args[:-1]))
    assert not Path('/home/dvitali/.local/state/spx-port/resume-armed.json').exists()
    record = dict(selected_metadata=selected, read_only_debug_argv=argv,
        exit_code=response.returncode, seconds=round(time.monotonic() - start, 3),
        host_process_live=True, host_process_session_identity_verified=True,
        retired_fallback_marker_absent=True, boot_id=boot, checked_wall_time=time.time())
    with (g.X / 'native-continuation.json').open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    os.sync()
    print('BE native same-thread resume/continue and live session process verified.')


if __name__ == '__main__':
    main()
