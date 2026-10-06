#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in, once-per-boot SensorsPD failure recovery; never reattach before proof."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import lifecycle

RUNTIME = Path('/run/spx-sensors')
LOCK = '/usr/local/libexec/spx-sensors/spx-lock'
BASE = Path('/var/lib/spx-boot-diagnostics/functional')


def eligible(record, boot_id, attempt, release):
    return (record.get('ready') is True and record.get('eligible') is True and
            record.get('unexpected_exit') is True and record.get('boot_id') == boot_id and
            record.get('attempt') == attempt and record.get('release') == release and
            isinstance(record.get('host_pid'), int) and record['host_pid'] > 1 and
            isinstance(record.get('host_start_ticks'), int) and record['host_start_ticks'] > 0)


def claim_once(path, record):
    # Atomic reservation occurs before services or remoteproc can be touched.
    with path.open('x') as stream:
        json.dump(record, stream)
    path.chmod(0o600)


def observer_proxy(observer, record, boot_id, attempt, owner):
    if observer is None:
        return None
    if (observer.get('boot_id') != boot_id or observer.get('attempt') != attempt or
            observer.get('host_pid') != record['host_pid'] or
            observer.get('host_start_ticks') != record['host_start_ticks'] or
            observer.get('owner') != owner or observer.get('proxy_pid', 0) <= 1):
        raise lifecycle.Refused('stale or mismatched test observer; no lock handoff')
    return observer['proxy_pid']


def recover(ops):
    result = dict(complete=False, restore_proven=False, restarted=False)
    effects_started = False
    try:
        result['before'] = ops.gate()
        ops.reserve()
        ops.save(result)
        cursor = ops.cursor()
        effects_started = True
        ops.stop_services()
        ops.stop_slpi()
        log = ops.kernel_since(cursor, 'teardown-kernel.log')
        if not lifecycle.teardown_proven(log):
            raise lifecycle.Refused('fresh users=0/pending=0 and final HLOS restoration missing; no restart')
        result['restore_proven'] = True
        ops.save(result)
        cursor = ops.cursor()
        ops.start_slpi()
        result['restarted'] = True
        ops.start_services()
        after = ops.backend()
        result['after'] = after
        if after['host_pid'] == result['before']['host_pid']:
            raise lifecycle.Refused('new host PID proof missing')
        after['proxy_pid'] = ops.proxy_pid()
        if after['proxy_pid'] == result['before'].get('proxy_pid'):
            raise lifecycle.Refused('new proxy PID proof missing')
        startup = ops.kernel_since(cursor, 'restart-kernel.log')
        if not re.search(r'SDSP heap .*shared owners=0x28\b', startup):
            raise lifecycle.Refused('fresh sharing owners=0x28 proof missing')
        result['complete'] = True
        result['scope'] = 'automatic reset and fresh backend readiness; delivery requires functional test'
    except Exception as error:
        result['error'] = str(error)
        if effects_started:
            try:
                ops.stop_services()
                ops.stop_slpi()
                result['failure_backend_stopped'] = True
            except Exception as stop_error:
                result['failure_stop_error'] = str(stop_error)
    finally:
        ops.save(result)
    return result


class Live(lifecycle.Live):
    def __init__(self, output, attempt, release, record):
        super().__init__(output, attempt, release)
        self.record = record
        self.owner = 'sensor-crash-' + attempt

    def gate(self):
        if not eligible(self.record, self.boot_id, self.attempt, self.release):
            raise lifecycle.Refused('no current-boot READY host unexpected exit')
        words = Path('/proc/cmdline').read_text().split()
        prepared = json.loads((BASE / self.attempt / 'prepared.json').read_text())
        if not (prepared.get('sensors_crash_recovery') is True and prepared.get('sensors_private_ssc') is True and
                prepared.get('release') == self.release and prepared.get('attempt') == self.attempt):
            raise lifecycle.Refused('prepared feature/release/attempt mismatch')
        if 'spx_sensors_recovery=1' not in words or not self.private:
            raise lifecycle.Refused('recovery/private SSC opt-in missing')
        if self.checked('provider-failed', ['systemctl', 'show', lifecycle.PROVIDER, '-p', 'ActiveState', '--value']).strip() != 'failed':
            raise lifecycle.Refused('OnFailure requires actual failed provider')
        proc = Path('/proc') / str(self.record['host_pid'])
        if proc.exists():
            # The supervisor must have reaped the failed host before triggering OnFailure.
            raise lifecycle.Refused('recorded failed host PID still present or reused')
        timer_budget(self, 300)
        observer_path = RUNTIME / 'test-observer.json'
        observer = json.loads(observer_path.read_text()) if observer_path.exists() else None
        old_proxy = observer_proxy(observer, self.record, self.boot_id, self.attempt, self.owner)
        if old_proxy is None:
            # BindsTo may already have stopped the proxy. ExecMainPID retains its
            # last owned process identity after MainPID becomes zero.
            old_proxy = int(self.checked('old-owned-proxy-pid', ['systemctl', 'show', lifecycle.PROXY,
                '-p', 'ExecMainPID', '--value'], 5).strip())
            if old_proxy <= 1:
                raise lifecycle.Refused('previous owned proxy ExecMainPID missing')
        before = dict(host_pid=self.record['host_pid'], provider_pid=self.record['provider_pid'],
                      proxy_pid=old_proxy)
        return super().gate(before=before, allow_native=True)

    def reserve(self):
        claim_once(RUNTIME / ('attempt-' + self.boot_id + '.json'), self.record)

    def proxy_pid(self):
        return int(self.checked('proxy-pid', ['systemctl', 'show', lifecycle.PROXY, '-p', 'MainPID', '--value']).strip())

    def start_services(self):
        self.checked('reset-provider-failed', ['systemctl', 'reset-failed', lifecycle.PROVIDER], 5)
        super().start_services()


def timer_budget(ops, seconds):
    ops.checked('return-timer-active', ['systemctl', 'is-active', 'spx-trial-return@' + ops.attempt + '.timer'], 5)
    raw = ops.checked('return-deadline', ['busctl', 'get-property', 'org.freedesktop.systemd1',
         '/org/freedesktop/systemd1/unit/spx_2dtrial_2dreturn_40' + ops.attempt + '_2etimer',
         'org.freedesktop.systemd1.Timer', 'NextElapseUSecMonotonic'], 5).split()
    if len(raw) != 2 or raw[0] != 't' or int(raw[1]) / 1e6 - time.monotonic() < seconds:
        raise lifecycle.Refused('automatic return reserve insufficient')


def main():
    words = Path('/proc/cmdline').read_text().split()
    attempt = next(w.split('=', 1)[1] for w in words if w.startswith('spx_attempt='))
    record = json.loads((RUNTIME / 'crash.json').read_text())
    output = BASE / attempt / 'sensors-auto-recovery'
    if output.exists():
        raise lifecycle.Refused('automatic recovery evidence already exists; no retry')
    live = Live(output, attempt, os.uname().release, record)
    subprocess.run([LOCK, 'acquire', 'device', live.owner], check=True, timeout=5)
    # A functional tester may already own this identical lock: it only observes
    # while this unit mutates, and retains responsibility for final release.
    delegated = False
    try:
        observer = json.loads((RUNTIME / 'test-observer.json').read_text())
        delegated = observer_proxy(observer, record, live.boot_id, attempt, live.owner) is not None
    except (OSError, ValueError, lifecycle.Refused):
        pass
    def expired(*_):
        raise lifecycle.Refused('bounded recovery deadline expired')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(180)
    try:
        result = recover(live)
        return 0 if result['complete'] else 1
    finally:
        signal.alarm(0)
        if not delegated:
            subprocess.run([LOCK, 'release', 'device', live.owner], check=True, timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
