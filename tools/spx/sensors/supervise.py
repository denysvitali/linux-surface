#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Keep the first SensorsPD listener alive; notify only after SSC metadata exists."""
import os
import json
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

ROOT = '/usr/share/qcom/sc8180x/Microsoft/spx'
LIBEXEC = '/usr/local/libexec/spx-sensors'
DEVICE = '/dev/fastrpc-sdsp-secure'


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect('\0' + address[1:] if address.startswith('@') else address)
            sock.sendall(message.encode())


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def supervise(daemon_command, readiness_command, stopped, send=notify, timeout=60, witness=None):
    daemon = checker = None
    deadline = time.monotonic() + timeout
    ready = False
    try:
        daemon = subprocess.Popen(daemon_command)
        while not stopped.is_set():
            if daemon.poll() is not None:
                if ready and witness and not stopped.is_set():
                    witness('crash', daemon)
                send('STATUS=SensorsPD listener exited; restart disabled')
                # Upstream can report listener errors yet return zero.
                return 1
            if not ready:
                if time.monotonic() >= deadline:
                    send('STATUS=SSC accelerometer metadata did not become ready')
                    return 1
                if checker is None:
                    checker = subprocess.Popen(readiness_command)
                result = checker.poll()
                if result is not None:
                    checker = None
                    if result == 0:
                        # Do not publish readiness after a simultaneous daemon exit.
                        if daemon.poll() is not None:
                            return 1
                        if witness:
                            witness('ready', daemon)
                        ready = True
                        send('READY=1\nSTATUS=SSC accelerometer ready; initial SensorsPD listener retained')
                    else:
                        stopped.wait(min(1, max(0, deadline - time.monotonic())))
            stopped.wait(0.1)
        if witness:
            witness('intentional-stop', daemon)
        send('STOPPING=1')
        return 0
    finally:
        stop_process(checker)
        stop_process(daemon)


def host_identity(pid):
    proc = Path('/proc') / str(pid)
    argv = [os.fsdecode(x) for x in (proc / 'cmdline').read_bytes().split(b'\0') if x]
    expected = [LIBEXEC + '/hexagonrpcd/hexagonrpcd', '-f', DEVICE, '-d', 'sdsp', '-s', '-R', ROOT]
    if argv != expected or (proc / 'exe').resolve() != Path(expected[0]).resolve():
        raise RuntimeError('retained host identity does not match installed SensorsPD command')
    if not any(os.readlink(fd) == DEVICE for fd in (proc / 'fd').iterdir()):
        raise RuntimeError('retained host secure FastRPC fd missing')
    return dict(host_pid=pid, host_start_ticks=int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]),
                host_exe=str((proc / 'exe').resolve()), host_argv=argv,
                provider_pid=int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[1]))


class Witness:
    def __init__(self):
        self.directory = Path('/run/spx-sensors')
        self.record = None
        self.enabled = 'spx_sensors_recovery=1' in Path('/proc/cmdline').read_text().split()
        if self.enabled:
            (self.directory / 'crash.json').unlink(missing_ok=True)

    def __call__(self, event, daemon):
        if not self.enabled:
            return
        if event == 'ready':
            self.record = dict(host_identity(daemon.pid), boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                               release=os.uname().release, ready=True, monotonic=time.monotonic())
            words = Path('/proc/cmdline').read_text().split()
            self.record['attempt'] = next(w.split('=', 1)[1] for w in words if w.startswith('spx_attempt='))
            path = self.directory / 'ready.json'
        elif event == 'crash' and self.record and daemon.poll() is not None:
            self.record = dict(self.record, eligible=True, unexpected_exit=True, host_returncode=daemon.returncode)
            path = self.directory / 'crash.json'
        else:
            (self.directory / 'crash.json').unlink(missing_ok=True)
            return
        temporary = path.with_suffix('.new')
        temporary.write_text(json.dumps(self.record) + '\n')
        temporary.chmod(0o600)
        os.replace(temporary, path)


def main():
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    deadline = time.monotonic() + 30
    while not Path(DEVICE).exists():
        if stopped.wait(0.1):
            return 0
        if time.monotonic() >= deadline:
            notify('STATUS=SDSP FastRPC device unavailable')
            return 1
    return supervise([LIBEXEC + '/hexagonrpcd/hexagonrpcd', '-f', DEVICE, '-d', 'sdsp', '-s', '-R', ROOT],
                     [LIBEXEC + '/ready'], stopped, witness=Witness())


if __name__ == '__main__':
    raise SystemExit(main())
