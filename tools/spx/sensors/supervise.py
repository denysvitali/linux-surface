#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Keep the first SensorsPD listener alive; notify only after SSC metadata exists."""
import os
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


def supervise(daemon_command, readiness_command, stopped, send=notify, timeout=60):
    daemon = checker = None
    deadline = time.monotonic() + timeout
    ready = False
    try:
        daemon = subprocess.Popen(daemon_command)
        while not stopped.is_set():
            if daemon.poll() is not None:
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
                        ready = True
                        send('READY=1\nSTATUS=SSC accelerometer ready; initial SensorsPD listener retained')
                    else:
                        stopped.wait(min(1, max(0, deadline - time.monotonic())))
            stopped.wait(0.1)
        send('STOPPING=1')
        return 0
    finally:
        stop_process(checker)
        stop_process(daemon)


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
                     [LIBEXEC + '/ready'], stopped)


if __name__ == '__main__':
    raise SystemExit(main())
