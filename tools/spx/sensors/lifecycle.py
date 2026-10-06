#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One guarded SLPI stop/start; require fresh ownership restoration evidence."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

PRIVATE_SSC = '/usr/local/libexec/spx-sensors/libssc'
PROVIDER = 'spx-sensors.service'
PROXY = 'iio-sensor-proxy.service'


class Refused(RuntimeError):
    pass


def teardown_proven(log):
    removed = list(re.finditer(r'channel remove users=(\d+) pending=(\d+)', log))
    restored = re.search(r'SDSP heap restored to HLOS owners=0x8; final context drained', log)
    return bool(removed and restored and all(m[1] == '0' and m[2] == '0' for m in removed)
                and restored.start() > removed[-1].start()
                and 'SDSP heap restore failed' not in log)


def stream_proven(record):
    values = re.findall(r'sensor measurement: X=(\S+) Y=(\S+) Z=(\S+)', record['stdout'] + record['stderr'])
    finite = all(math.isfinite(float(value)) for row in values for value in row)
    return record['returncode'] == 0 and len(values) >= 20 and finite and \
        'Sensor disable request sent successfully' in record['stdout'] + record['stderr']


def exercise(ops):
    """Effects are deliberately sequenced behind explicit positive proofs."""
    result = dict(complete=False, restore_proven=False, restarted=False)
    try:
        result['before'] = ops.gate()
        ops.save(result)
        cursor = ops.cursor()
        ops.stop_services()
        ops.stop_slpi()
        teardown = ops.kernel_since(cursor, 'teardown-kernel.log')
        if not teardown_proven(teardown):
            raise Refused('fresh quiescent removal/HLOS restoration proof missing; backend remains stopped')
        result['restore_proven'] = True
        ops.save(result)
        cursor = ops.cursor()
        ops.start_slpi()
        result['restarted'] = True
        ops.start_services()
        result['after'] = ops.backend()
        if result['after']['host_pid'] == result['before']['host_pid']:
            raise Refused('SensorsPD host PID did not change')
        startup = ops.kernel_since(cursor, 'restart-kernel.log')
        if not re.search(r'SDSP heap .*shared owners=0x28\b', startup):
            raise Refused('fresh SDSP sharing owners=0x28 not observed')
        result['streams'] = {}
        for sensor in ('accelerometer', 'gyroscope', 'magnetometer'):
            record = ops.stream(sensor)
            result['streams'][sensor] = record
            ops.save(result)
            if not stream_proven(record):
                raise Refused(sensor + ': finite samples/clean disable proof missing')
        result['desktop'] = ops.desktop()
        accel = result['desktop']['accelerometer']
        compass = result['desktop']['compass']
        orientations = re.findall(r'(?:Accelerometer orientation changed:\s*|Has accelerometer \(orientation:\s*)([^\s,)]+)', accel['stdout'] + accel['stderr'])
        headings = re.findall(r'Compass heading changed:\s*([^\s]+)', compass['stdout'] + compass['stderr'])
        if accel.get('harness_timeout') or accel['returncode'] != 124 or not any(value in ('normal', 'bottom-up', 'left-up', 'right-up') for value in orientations):
            raise Refused('native accelerometer orientation observation missing')
        if compass.get('harness_timeout') or compass['returncode'] != 124 or not headings or not all(math.isfinite(float(value)) for value in headings):
            raise Refused('native finite compass observation missing')
        result['complete'] = True
        result['limits'] = 'Identity fallback is compatibility only; physical axes/rotation, seated GNOME and arbitrary crash restart remain unverified.'
    except Exception as error:
        result['error'] = str(error)
    finally:
        ops.save(result)
        try:
            ops.capture()
        except Exception as error:
            result['capture_error'] = str(error)
            result['complete'] = False
        ops.save(result)
    return result


class Live:
    def __init__(self, output, attempt, release):
        self.output, self.attempt, self.release = output, attempt, release
        output.mkdir(mode=0o700)
        self.result_path = output / 'result.json'
        self.steps = []
        self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.private = 'spx_sensors_libssc=private' in Path('/proc/cmdline').read_text().split()
        self.remote = None

    def run(self, name, argv, timeout=15, env=None, input=None):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, input=input)
            record = dict(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        except subprocess.TimeoutExpired as error:
            record = dict(returncode=124, stdout=(error.stdout or b'').decode() if isinstance(error.stdout, bytes) else error.stdout or '',
                          stderr='process exceeded harness timeout')
            # This is distinct from the intentionally bounded monitor's rc124.
            record['harness_timeout'] = True
        if argv[0] == 'journalctl':
            self.steps.append(dict(name=name, argv=argv, returncode=record['returncode'],
                                   captured_lines=len(record['stdout'].splitlines())))
        else:
            self.steps.append(dict(name=name, argv=argv, **record))
        return record

    def checked(self, name, argv, timeout=15, input=None):
        record = self.run(name, argv, timeout, input=input)
        if record['returncode']:
            raise Refused(name + ': ' + record['stderr'].strip())
        return record['stdout']

    def save(self, result):
        result.update(attempt=self.attempt, release=self.release, boot_id=self.boot_id, steps=self.steps)
        self.result_path.write_text(json.dumps(result, indent=2) + '\n')

    def cursor(self):
        log = self.checked('journal-cursor', ['journalctl', '-b', '--show-cursor', '-n', '0', '--no-pager'])
        match = re.search(r'-- cursor: (\S+)', log)
        if not match:
            raise Refused('journal cursor unavailable')
        return match[1]

    def kernel_since(self, cursor, filename):
        log = self.checked(filename, ['journalctl', '-b', '-k', '--after-cursor=' + cursor, '--no-pager', '-o', 'short-monotonic'])
        (self.output / filename).write_text(log)
        return log

    def backend(self):
        status = self.checked('provider-status', ['systemctl', 'show', PROVIDER, '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID'])
        values = dict(line.split('=', 1) for line in status.splitlines())
        if values.get('ActiveState') != 'active' or values.get('SubState') != 'running':
            raise Refused('provider is not READY/running')
        pid = int(values['MainPID'])
        children = Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
        hosts = [int(child) for child in children if Path('/proc/' + child + '/comm').read_text().strip() == 'hexagonrpcd']
        if len(hosts) != 1:
            raise Refused('expected one retained SensorsPD host child')
        return dict(provider_pid=pid, host_pid=hosts[0])

    def gate(self):
        words = Path('/proc/cmdline').read_text().split()
        if os.geteuid() != 0 or os.uname().release != self.release or \
                'spx_attempt=' + self.attempt not in words or 'spx_boot=mainline-functional' not in words or 'spx_sensors=1' not in words:
            raise Refused('current opted-in attempt/release does not match')
        memory = Path('/proc/iomem').read_text()
        if 'FastRPC SDSP DMA ownership' not in memory:
            raise Refused('loaded module has no patched SDSP ownership lease; no actions permitted')
        kernel = self.checked('initial-kernel', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'])
        (self.output / 'initial-kernel.log').write_text(kernel)
        if not re.search(r'SDSP heap .*shared owners=0x28\b', kernel):
            raise Refused('current boot has no patched sharing owners=0x28 evidence')
        matching = [path for path in Path('/sys/class/remoteproc').glob('remoteproc*')
                    if (path / 'name').read_text().strip() == 'slpi' and
                    (path / 'firmware').read_text().strip() == 'qcom/microsoft/spx/qcslpi8180.mbn']
        if len(matching) != 1 or (matching[0] / 'state').read_text().strip() != 'running':
            raise Refused('exact SPX SLPI backend is not uniquely running')
        self.remote = matching[0]
        before = self.backend()
        # Never terminate unknown clients. Owned service stops close their users.
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                argv = (proc / 'cmdline').read_bytes().split(b'\0')
                if argv and os.path.basename(os.fsdecode(argv[0])) in ('ssccli', 'monitor-sensor'):
                    raise Refused('external sensor client PID ' + proc.name + '; no actions permitted')
                for fd in (proc / 'fd').iterdir():
                    try:
                        if os.readlink(fd) == '/dev/fastrpc-sdsp-secure' and int(proc.name) != before['host_pid']:
                            raise Refused('external secure FastRPC client PID ' + proc.name + '; no actions permitted')
                    except FileNotFoundError:
                        pass
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        before['remoteproc'] = str(self.remote)
        return before

    def stop_services(self):
        self.checked('stop-proxy', ['systemctl', 'stop', PROXY], 20)
        self.checked('stop-provider', ['systemctl', 'stop', PROVIDER], 20)

    def state(self, wanted):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            value = (self.remote / 'state').read_text().strip()
            if value == wanted:
                return
            time.sleep(.1)
        raise Refused('SLPI did not reach ' + wanted)

    def stop_slpi(self):
        self.checked('slpi-stop', ['tee', str(self.remote / 'state')], 20, input='stop\n')
        self.state('offline')

    def start_slpi(self):
        self.checked('slpi-start', ['tee', str(self.remote / 'state')], 20, input='start\n')
        self.state('running')

    def start_services(self):
        self.checked('start-provider', ['systemctl', 'start', PROVIDER], 100)
        self.backend()
        self.checked('start-proxy', ['systemctl', 'start', PROXY], 20)
        deadline = time.monotonic() + 15
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Refused('proxy HasAccelerometer did not become true within 15s')
            props = self.run('proxy-accelerometer', ['gdbus', 'call', '--system', '--dest', 'net.hadess.SensorProxy',
                             '--object-path', '/net/hadess/SensorProxy', '--method', 'org.freedesktop.DBus.Properties.Get',
                             'net.hadess.SensorProxy', 'HasAccelerometer'], min(3, remaining))
            if props['returncode'] == 0 and 'true' in props['stdout']:
                break
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        if self.private:
            pid = int(self.checked('proxy-pid', ['systemctl', 'show', PROXY, '-p', 'MainPID', '--value']).strip())
            if PRIVATE_SSC + '/libssc.so.2' not in Path(f'/proc/{pid}/maps').read_text():
                raise Refused('proxy private libssc mapping missing')

    def stream(self, sensor):
        env = os.environ.copy()
        env.pop('LD_LIBRARY_PATH', None)
        if self.private:
            env['LD_LIBRARY_PATH'] = PRIVATE_SSC
        return self.run(sensor, ['ssccli', '--debug', '--sensor', sensor, '--timeout', '3'], 12, env)

    def desktop(self):
        return {name: self.run('native-' + name, ['timeout', '--signal=TERM', '--kill-after=2s', str(seconds) + 's',
                                               'stdbuf', '-oL', '-eL', 'monitor-sensor', flag], seconds + 5)
                for name, flag, seconds in [('accelerometer', '--accel', 12), ('compass', '--compass', 10)]}

    def capture(self):
        for name, argv in [('kernel.log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic']),
                           ('services.log', ['journalctl', '-b', '-u', PROVIDER, '-u', PROXY, '--no-pager', '-o', 'short-monotonic'])]:
            record = self.run('capture-' + name, argv, 15)
            (self.output / name).write_text(record['stdout'] + record['stderr'])
