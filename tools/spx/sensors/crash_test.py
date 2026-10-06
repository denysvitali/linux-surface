#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One verified host kill, observe automatic reset, require fresh native delivery."""
import json
import math
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import threading
import time
import lifecycle
import recovery
import supervise


def desktop_proven(accel, compass):
    orientation = re.findall(r'(?:Accelerometer orientation changed:\s*|Has accelerometer \(orientation:\s*)([^\s,)]+)', accel)
    headings = re.findall(r'Compass heading changed:\s*([^\s]+)', compass)
    try:
        return (any(x in ('normal', 'bottom-up', 'left-up', 'right-up') for x in orientation)
                and len(headings) >= 3 and all(math.isfinite(float(x)) for x in headings))
    except ValueError:
        return False


def kernel_fault_lines(log):
    pattern = r'BUG:|Oops:|blocked for more than|SMMU.*fault|watchdog received|Kernel panic|fatal error received|crash detected in|timeout waiting for shutdown response'
    return [line for line in log.splitlines() if re.search(pattern, line, re.I)]


class Client:
    def __init__(self, flag, credentials, output):
        self.lines = []
        self.output = output
        self.credentials = credentials
        self.scope = 'spx-sensor-test-' + flag.lstrip('-') + '.scope'
        self.env = os.environ.copy()
        self.env.pop('LD_LIBRARY_PATH', None)
        self.env.update(HOME=pwd.getpwuid(credentials['user']).pw_dir,
                        XDG_RUNTIME_DIR='/run/user/1000',
                        DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus')
        state = subprocess.run(['systemctl', '--user', 'show', self.scope, '-p', 'LoadState', '--value'],
                               capture_output=True, text=True, env=self.env, timeout=5, **credentials)
        if state.returncode or state.stdout.strip() != 'not-found':
            raise lifecycle.Refused('client scope already exists or user manager unavailable')
        # UID alone in the root trial service is not an active desktop subject.
        # A user scope supplies the existing user manager's session association;
        # installed polkit policy still decides each real sensor claim.
        self.process = subprocess.Popen(['systemd-run', '--user', '--scope', '--collect', '--quiet',
            '--unit=' + self.scope, 'timeout', '--signal=TERM', '--kill-after=2s', '240s',
            'stdbuf', '-oL', '-eL', 'monitor-sensor', flag], env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True, **credentials)
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        with self.output.open('w') as stream:
            for line in self.process.stdout:
                self.lines.append(line)
                stream.write(str(time.monotonic()) + ' ' + line)
                stream.flush()

    def text(self):
        return ''.join(self.lines)

    def stop(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=3)
        self.thread.join(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = subprocess.run(['systemctl', '--user', 'show', self.scope, '-p', 'ActiveState', '--value'],
                capture_output=True, text=True, env=self.env, timeout=3, **self.credentials)
            if state.returncode == 0 and state.stdout.strip() in ('inactive', 'failed'):
                return self.process.poll() is not None and not self.thread.is_alive()
            time.sleep(.1)
        return False


def stop_clients(clients, errors):
    complete = True
    for client in clients:
        try:
            if not client.stop():
                complete = False
                errors.append('owned client/thread remains live')
        except Exception as error:
            complete = False
            errors.append(str(error))
    return complete


def exercise(ops):
    result = dict(complete=False, host_killed=False, old_client_continuity_proven=False, cleanup_errors=[])
    clients = []
    try:
        before = ops.gate()
        result['before'] = before
        cursor = ops.cursor()
        ops.save(result)
        clients = ops.clients('pre-crash')
        ops.require_delivery(clients)
        result['pre_crash_delivery'] = True
        ops.save(result)
        ops.kill_host(before)
        result['host_killed'] = True
        result['kill_monotonic'] = time.monotonic()
        ops.save(result)
        # Observe old clients without asserting they retain their D-Bus claim.
        time.sleep(2)
        result['old_clients_after_crash'] = [dict(pid=c.process.pid, returncode=c.process.poll(), text=c.text()) for c in clients]
        result['old_clients_stopped'] = stop_clients(clients, result['cleanup_errors'])
        clients = []
        if not result['old_clients_stopped']:
            raise lifecycle.Refused('owned pre-crash client cleanup missing')
        result['automatic_recovery'] = ops.observe_recovery()
        ops.save(result)
        result['streams'] = {}
        for sensor in ('accelerometer', 'gyroscope', 'magnetometer'):
            record = ops.stream(sensor)
            result['streams'][sensor] = record
            ops.save(result)
            if not lifecycle.stream_proven(record):
                raise lifecycle.Refused(sensor + ': post-reset finite delivery/clean disable missing')
        result['fresh_desktop'] = []
        for phase in ('fresh-open', 'fresh-reopen'):
            clients = ops.clients(phase)
            ops.require_delivery(clients)
            result['fresh_desktop'].append(dict(phase=phase, clients=[dict(pid=c.process.pid, text=c.text()) for c in clients]))
            stopped = stop_clients(clients, result['cleanup_errors'])
            clients = []
            if not stopped:
                raise lifecycle.Refused('owned fresh client cleanup missing')
            ops.save(result)
        result['delivery_complete'] = True
        faults = ops.kernel_since(cursor, 'crash-workload-kernel.log')
        result['fault_lines'] = kernel_fault_lines(faults)
        if result['fault_lines']:
            raise lifecycle.Refused('new kernel/DSP/SMMU fault during recovery')
        result['after'] = ops.backend()
        result['complete'] = True
        result['scope'] = 'fresh client recovery after one verified host failure; old-client continuity unproven'
    except Exception as error:
        result['error'] = str(error)
    finally:
        result['remaining_clients_stopped'] = stop_clients(clients, result['cleanup_errors'])
        if not result['remaining_clients_stopped']:
            result['complete'] = False
        ops.save(result)
        try:
            ops.capture()
        except Exception as error:
            result['capture_error'] = str(error)
            result['complete'] = False
        ops.save(result)
    return result


class Live(lifecycle.Live):
    def __init__(self, output, attempt, release):
        super().__init__(output, attempt, release)
        self.owner = 'sensor-crash-' + attempt
        self.pidfd = None

    def gate(self):
        if 'spx_sensors_recovery=1' not in Path('/proc/cmdline').read_text().split() or not self.private:
            raise lifecycle.Refused('explicit crash/private SSC opt-in missing')
        before = super().gate()
        recovery.timer_budget(self, 420)
        rows = self.checked('desktop-sessions', ['loginctl', 'list-sessions', '--no-legend']).splitlines()
        found = False
        for row in rows:
            session = row.split()[0]
            props = dict(line.split('=', 1) for line in self.checked('desktop-session-' + session,
                ['loginctl', 'show-session', session, '-p', 'User', '-p', 'Active', '-p', 'LockedHint', '-p', 'Seat', '-p', 'Type']).splitlines())
            if props == dict(User='1000', Active='yes', LockedHint='no', Seat='seat0', Type='wayland'):
                found = True
        if not found:
            raise lifecycle.Refused('active unlocked UID1000 Wayland seat0 required; no policy bypass')
        user = pwd.getpwuid(1000)
        self.credentials = dict(user=user.pw_uid, group=user.pw_gid, extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
        # Record the installed policy; never modify it for this test.
        self.checked('native-policy', ['cat', '/usr/share/polkit-1/actions/net.hadess.SensorProxy.policy'])
        before.update(supervise.host_identity(before['host_pid']))
        before['proxy_pid'] = int(self.checked('old-proxy-pid', ['systemctl', 'show', lifecycle.PROXY, '-p', 'MainPID', '--value']).strip())
        if before['proxy_pid'] <= 1:
            raise lifecycle.Refused('old proxy PID missing')
        ready = json.loads((recovery.RUNTIME / 'ready.json').read_text())
        if ready.get('boot_id') != self.boot_id or ready.get('host_start_ticks') != before['host_start_ticks'] or ready.get('host_pid') != before['host_pid']:
            raise lifecycle.Refused('supervisor readiness witness mismatches live verified host')
        self.pidfd = os.pidfd_open(before['host_pid'])
        # Opening a pidfd followed by identity verification rejects PID reuse.
        if supervise.host_identity(before['host_pid'])['host_start_ticks'] != before['host_start_ticks']:
            raise lifecycle.Refused('host identity changed during pidfd acquisition')
        marker = dict(boot_id=self.boot_id, attempt=self.attempt, host_pid=before['host_pid'],
                      host_start_ticks=before['host_start_ticks'], proxy_pid=before['proxy_pid'], owner=self.owner)
        recovery.claim_once(recovery.RUNTIME / 'test-observer.json', marker)
        return before

    def clients(self, phase):
        clients = []
        try:
            for flag in ('--accel', '--compass'):
                clients.append(Client(flag, self.credentials, self.output / (phase + flag + '.log')))
            return clients
        except Exception:
            for client in clients:
                client.stop()
            raise

    def require_delivery(self, clients):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if any(c.process.poll() is not None for c in clients):
                raise lifecycle.Refused('native UID1000 monitor exited before delivery')
            if desktop_proven(clients[0].text(), clients[1].text()):
                return
            time.sleep(.1)
        raise lifecycle.Refused('UID1000 valid orientation and three finite compass updates missing')

    def kill_host(self, before):
        recovery.timer_budget(self, 360)
        current = supervise.host_identity(before['host_pid'])
        if current['host_start_ticks'] != before['host_start_ticks']:
            raise lifecycle.Refused('host changed before injected failure')
        signal.pidfd_send_signal(self.pidfd, signal.SIGKILL)
        os.close(self.pidfd)
        self.pidfd = None

    def observe_recovery(self):
        deadline = time.monotonic() + 205
        path = recovery.BASE / self.attempt / 'sensors-auto-recovery/result.json'
        while time.monotonic() < deadline:
            # Never manually heal: the only effects come from actual OnFailure.
            state = self.checked('automatic-unit-state', ['systemctl', 'show', 'spx-sensors-recovery.service',
                '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainStatus'], 5)
            values = dict(line.split('=', 1) for line in state.splitlines())
            if path.exists() and values.get('ActiveState') in ('inactive', 'failed'):
                record = json.loads(path.read_text())
                if not record.get('complete') or values.get('Result') != 'success' or values.get('ExecMainStatus') != '0':
                    raise lifecycle.Refused('actual automatic recovery failed: ' + record.get('error', state))
                if record.get('boot_id') != self.boot_id:
                    raise lifecycle.Refused('automatic recovery belongs to another boot')
                return dict(record=record, unit=values)
            time.sleep(.2)
        raise lifecycle.Refused('automatic recovery did not finish within bounded observation')

    def capture(self):
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None
        super().capture()
        state = self.checked('recovery-final-state', ['systemctl', 'show', 'spx-sensors-recovery.service', '-p', 'ActiveState', '--value'], 5).strip()
        if state not in ('active', 'activating', 'deactivating'):
            (recovery.RUNTIME / 'test-observer.json').unlink(missing_ok=True)
