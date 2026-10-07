#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One bounded AC-only normal systemd sleep, retaining persistent sleep masks."""
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import struct
import subprocess
import tempfile
import time

import pmic_rtc
from sensors import lifecycle

UNITS = ('sleep.target', 'suspend.target')
AUDIO = {'wcd934x', 'soundwire_qcom', 'snd_soc_wsa881x', 'snd_soc_wcd934x'}
WHO = 'spx-systemd-suspend'
RUNTIME = Path('/run/systemd/system.control')
PERSISTENT = Path('/etc/systemd/system')
STOCK = Path('/usr/lib/systemd/system')


def sleep_proven(r):
    return bool(r['boot_unchanged'] and 15 <= r['sleep_seconds'] <= 45 and
                r['kernel_entered'] and r['kernel_exited'] and r['service_completed'] and
                r['irq_after'] > r['irq_before'] and r['event'] & 0x20 and r['event'] & 0x80 and
                r['alarm_disabled'] and r['user_thawed'])


def service_completed(before, after):
    return (after['ActiveState'] == 'inactive' and after['SubState'] == 'dead' and
            after['Result'] == 'success' and after['ExecMainStatus'] == '0' and
            int(after['ExecMainExitTimestampMonotonic']) > int(before['ExecMainExitTimestampMonotonic']))


def exercise(ops):
    result = dict(complete=False, scope='normal30s systemd s2idle on AC; retained network/sensors and disposable storage',
                  full_suspend_acceptance=False, audio_tested=False)
    try:
        result['before'] = ops.gate()
        ops.save(result)
        result['direct_prerequisite'] = ops.direct()
        ops.gate()  # Recheck the reserve immediately before the owned window.
        ops.inhibit_idle()
        ops.open_shadows()
        result['sleep'] = ops.sleep()
        if not sleep_proven(result['sleep']):
            raise RuntimeError('kernel/normal-service/RTC/slept/thaw proof incomplete')
        result['after'] = ops.post(result['before'])
        result['functional_pass'] = True
    except Exception as error:
        result['error'] = str(error)
        if hasattr(ops, 'sleep_result'):
            result['sleep'] = ops.sleep_result
    finally:
        try:
            result['cleanup'] = ops.cleanup()
        except Exception as error:
            result['cleanup_error'] = str(error)
        result['complete'] = bool(result.get('functional_pass') and result.get('cleanup', {}).get('masks_restored'))
        ops.save(result)
    return result


class Live:
    def __init__(self, output, attempt, release):
        self.output, self.attempt, self.release = output, attempt, release
        output.mkdir(mode=0o700, exist_ok=False)
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.started = time.monotonic()
        self.owned, self.steps = {}, []
        self.idle = self.fd = self.sensor = None
        self.armed = self.original_verified = self.runtime_created = False
        self.handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            self.handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda signum, frame: (_ for _ in ()).throw(RuntimeError('sleep helper interrupted/deadline')))
        #100s active work plus15/30s sleep and at most31s cleanup.
        signal.setitimer(signal.ITIMER_REAL, 100)

    def run(self, name, argv, timeout=5):
        remaining = 95 - (time.monotonic() - self.started)
        assert remaining > 0, 'helper deadline'
        p = subprocess.run(argv, text=True, capture_output=True, timeout=min(timeout, remaining))
        self.steps.append(dict(name=name, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr))
        assert p.returncode == 0, name + ': ' + p.stderr.strip()
        return p.stdout.strip()

    def properties(self, unit, *names):
        text = self.run(unit, ['systemctl', 'show', unit, *['-p' + name for name in names]])
        return dict(line.split('=', 1) for line in text.splitlines())

    def save(self, result):
        result.update(attempt=self.attempt, release=self.release, boot_id=self.boot, steps=self.steps)
        tmp = self.output / 'result.json.new'
        tmp.write_text(json.dumps(result, indent=2) + '\n')
        os.replace(tmp, self.output / 'result.json')

    def masks(self):
        for unit in UNITS:
            mask = PERSISTENT / unit
            assert mask.is_symlink() and os.readlink(mask) == '/dev/null'
            p = self.properties(unit, 'LoadState', 'FragmentPath', 'DropInPaths')
            assert p['LoadState'] == 'masked' and p['FragmentPath'] == str(mask) and not p['DropInPaths']

    def ac(self):
        assert any((p / 'online').read_text().strip() == '1' for p in Path('/sys/class/power_supply').glob('*')
                   if (p / 'type').read_text().strip() == 'Mains'), 'AC required'

    def services(self):
        data = self.sensor.backend()
        for unit in (lifecycle.PROVIDER, lifecycle.PROXY):
            p = self.properties(unit, 'ActiveState', 'SubState', 'MainPID', 'NRestarts')
            assert p['ActiveState'] == 'active' and p['SubState'] == 'running'
            assert int(p['MainPID']) > 0 and p['NRestarts'] == '0', 'sensor service restarted'
            data[unit] = p
        return data

    def streams(self, phase):
        records = {}
        for sensor in ('accelerometer', 'gyroscope', 'magnetometer'):
            r = self.sensor.stream(sensor)
            (self.output / (phase + '-' + sensor + '.log')).write_text(r['stdout'] + r['stderr'])
            assert lifecycle.stream_proven(r), sensor + ': finite stream/clean disable missing'
            records[sensor] = dict(returncode=r['returncode'], finite_stream_and_disable=True)
        return records

    def network(self):
        state = self.run('network', ['nmcli', '-g', 'GENERAL.STATE,GENERAL.CONNECTION', 'device', 'show', 'wlan0'])
        assert state.splitlines()[0].startswith('100'), 'wlan0 not connected'
        assert Path('/sys/class/net/wlan0/carrier').read_text().strip() == '1'
        return state

    def gate(self):
        assert os.geteuid() == 0 and os.uname().release == self.release
        assert re.fullmatch(r'[0-9]{8}[a-z0-9]+', self.attempt)
        words = Path('/proc/cmdline').read_text().split()
        assert [w for w in words if w.startswith('spx_attempt=')] == ['spx_attempt=' + self.attempt]
        assert 'spx_boot=mainline-functional' in words and 'spx_sensors=1' in words
        blocked = {n for w in words if w.startswith('module_blacklist=') for n in w.split('=', 1)[1].split(',')}
        assert AUDIO <= blocked and not any((Path('/sys/module') / n).exists() for n in AUDIO)
        assert Path('/proc/self/cgroup').read_text().strip() == '0::/system.slice/spx-systemd-suspend.service', 'owned system.slice transient unit required'
        for name in ('functional', 'pmic-rtc/result'):
            data = json.loads((self.output.parent / (name + '.json')).read_text())
            assert data.get('complete') is True and data['boot_id'] == self.boot and data['release'] == self.release
        prepared = json.loads((self.output.parent / 'prepared.json').read_text())
        assert prepared['release'] == self.release and not prepared.get('audio') and prepared.get('pmic_rtc')
        self.ac()
        assert Path('/sys/power/mem_sleep').read_text().strip() == '[s2idle]'
        assert '[none]' in Path('/sys/power/pm_test').read_text().split()
        rtc = Path('/sys/class/rtc/rtc1/device')
        assert (rtc / 'power/wakeup').read_text().strip() == 'enabled'
        assert (rtc / 'of_node').resolve().as_posix().endswith(pmic_rtc.NODE)
        assert (rtc / 'driver').resolve().name == 'rtc-pm8xxx'
        assert self.run('return-active', ['systemctl', 'is-active', 'spx-trial-return@' + self.attempt + '.timer']) == 'active'
        raw = self.run('return-deadline', ['busctl', 'get-property', 'org.freedesktop.systemd1',
            '/org/freedesktop/systemd1/unit/spx_2dtrial_2dreturn_40' + self.attempt + '_2etimer',
            'org.freedesktop.systemd1.Timer', 'NextElapseUSecMonotonic']).split()
        assert raw[0] == 't' and int(raw[1]) / 1e6 - time.monotonic() >= 360, '360s return reserve required'
        jobs = self.run('jobs', ['systemctl', 'list-jobs', '--no-legend', '--no-pager'])
        assert not re.search(r'spx-trial-return@|(?:systemd-suspend|sleep|suspend)\.(?:service|target)', jobs), 'conflicting job'
        for unit in UNITS:
            assert not os.path.lexists(RUNTIME / unit), 'existing runtime shadow'
        self.masks()
        self.original_verified = True
        if self.sensor is None:
            self.sensor = lifecycle.Live(self.output / 'sensor-observations', self.attempt, self.release)
        return dict(services=self.services(), network=self.network(), streams=self.streams('before'))

    def direct(self):
        output = self.output.parent / 'pmic-rtc-suspend'
        r = json.loads((output / 'result.json').read_text()) if output.exists() else pmic_rtc.exercise(output, self.attempt, self.release, suspend=True)
        assert r.get('complete') is True and r['boot_id'] == self.boot and r['release'] == self.release
        assert r['requested_seconds'] == 15 and r['sleep_seconds'] >= 10
        return dict(complete=True, result=str(output / 'result.json'))

    def inhibit_idle(self):
        assert WHO not in self.run('initial-inhibitors', ['systemd-inhibit', '--list', '--no-pager'])
        self.idle = subprocess.Popen(['systemd-inhibit', '--what=idle', '--mode=block', '--who=' + WHO,
            '--why=bounded-normal-suspend-test', 'sleep', '180'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            assert self.idle.poll() is None, 'idle inhibitor exited'
            listing = self.run('idle-inhibitor', ['systemd-inhibit', '--list', '--no-pager'])
            if any(WHO in row and re.search(r'\bidle\b', row) and re.search(r'\bblock\b', row) for row in listing.splitlines()):
                return
            time.sleep(.1)
        raise RuntimeError('owned idle-only inhibitor not observed')

    def open_shadows(self):
        try:
            RUNTIME.mkdir(mode=0o755)
            self.runtime_created = True
        except FileExistsError:
            assert RUNTIME.is_dir() and not RUNTIME.is_symlink()
        assert RUNTIME.stat().st_uid == os.geteuid() and not RUNTIME.stat().st_mode & 0o022
        for unit in UNITS:
            source, target = STOCK / unit, RUNTIME / unit
            assert source.is_file() and not source.is_symlink()
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            try:
                self.owned[target] = os.fstat(fd).st_ino  # Own even a partial write.
                with os.fdopen(fd, 'wb', closefd=False) as stream:
                    stream.write(source.read_bytes())
                    stream.flush()
                    os.fsync(fd)
            finally:
                os.close(fd)
        self.run('load-shadows', ['systemctl', 'daemon-reload'], 15)
        for unit in UNITS:
            p = self.properties(unit, 'LoadState', 'FragmentPath', 'DropInPaths')
            assert p['LoadState'] == 'loaded' and p['FragmentPath'] == str(RUNTIME / unit) and not p['DropInPaths']
            assert (RUNTIME / unit).read_bytes() == (STOCK / unit).read_bytes()
        assert self.run('can-suspend', ['busctl', 'call', 'org.freedesktop.login1', '/org/freedesktop/login1',
            'org.freedesktop.login1.Manager', 'CanSuspend']) == 's "yes"'

    def sleep(self):
        self.ac()
        self.fd = os.open('/dev/rtc1', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        assert pmic_rtc.alarm(self.fd)[:2] == (0, 0), 'preexisting alarm left untouched'
        r = dict(requested_alarm_seconds=30, minimum_real_sleep_seconds=15, irq_before=pmic_rtc.irq_count())
        self.sleep_result = r
        cursor = re.search(r'-- cursor: (\S+)', self.run('cursor', ['journalctl', '-b', '--show-cursor', '-n', '0', '--no-pager']))[1]
        before = self.properties('systemd-suspend.service', 'ExecMainExitTimestampMonotonic', 'ActiveState')
        assert before['ActiveState'] == 'inactive', 'sleep service already running/failed'
        data = bytearray(36)
        fcntl.ioctl(self.fd, pmic_rtc.RTC_RD_TIME, data)
        t = struct.unpack('=9i', data)
        target = datetime.datetime(t[5] + 1900, t[4] + 1, t[3], t[2], t[1], t[0], tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=30)
        tm = (target.second, target.minute, target.hour, target.day, target.month - 1, target.year - 1900,
              (target.weekday() + 1) % 7, target.timetuple().tm_yday - 1, 0)
        self.armed = True
        fcntl.ioctl(self.fd, pmic_rtc.RTC_WKALM_SET, struct.pack('=BB2x9i', 1, 0, *tm))
        assert pmic_rtc.alarm(self.fd)[0] == 1
        self.save(dict(complete=False, phase='verified-shadows-alarm-armed-before-normal-suspend', sleep=r))
        boot, mono = time.clock_gettime(time.CLOCK_BOOTTIME), time.monotonic()
        self.run('normal-suspend', ['systemctl', '--check-inhibitors=yes', 'suspend'], 10)
        # The command queues asynchronously; only the service's fresh completion counts.
        end = time.clock_gettime(time.CLOCK_BOOTTIME) + 45
        completed = False
        while time.clock_gettime(time.CLOCK_BOOTTIME) < end:
            after = self.properties('systemd-suspend.service', 'ActiveState', 'SubState', 'Result', 'ExecMainStatus', 'ExecMainExitTimestampMonotonic')
            completed = service_completed(before, after)
            if completed:
                break
            time.sleep(.2)
        r['sleep_seconds'] = time.clock_gettime(time.CLOCK_BOOTTIME) - boot - (time.monotonic() - mono)
        r['service_completed'], r['service'] = completed, after
        assert select.select([self.fd], [], [], 3)[0], 'RTC event missing'
        r['event'] = struct.unpack('@L', os.read(self.fd, struct.calcsize('@L')))[0]
        r['irq_after'] = pmic_rtc.irq_count()
        fcntl.ioctl(self.fd, pmic_rtc.RTC_AIE_OFF)
        r['alarm_disabled'] = pmic_rtc.alarm(self.fd)[0] == 0
        self.armed = not r['alarm_disabled']
        log = self.run('sleep-kernel', ['journalctl', '-b', '-k', '--after-cursor=' + cursor, '--no-pager', '-o', 'short-monotonic'])
        (self.output / 'sleep-kernel.log').write_text(log)
        r['kernel_entered'] = 'PM: suspend entry (s2idle)' in log
        r['kernel_exited'] = 'PM: suspend exit' in log and log.find('PM: suspend exit') > log.find('PM: suspend entry (s2idle)')
        r['boot_unchanged'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == self.boot
        r['user_thawed'] = 'frozen 0' in Path('/sys/fs/cgroup/user.slice/cgroup.events').read_text().splitlines()
        return r

    def post(self, before):
        self.ac()
        after = dict(services=self.services())
        assert after['services'] == before['services'], 'sensor PID/state changed'
        end = time.monotonic() + 20
        while True:
            try:
                after['network'] = self.network()
                break
            except AssertionError:
                assert time.monotonic() < end, 'wlan0 did not reconnect within20s'
                time.sleep(.5)
        assert after['network'] == before['network'], 'network connection changed'
        count = self.run('wifi-transfer', ['curl', '--interface', 'wlan0', '-4', '--fail', '--silent', '--show-error',
            '--max-time', '15', '-o', '/dev/null', '-w', '%{size_download}', 'https://speed.cloudflare.com/__down?bytes=1000000'], 17)
        assert count == '1000000', '1MB transfer incomplete'
        after['download_bytes'] = int(count)
        after['streams'] = self.streams('after')
        with tempfile.NamedTemporaryFile(prefix='storage-', dir=self.output) as stream:
            data = os.urandom(65536)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            assert stream.read() == data
        after['fsync_readback_bytes'] = len(data)
        return after

    def cleanup(self):
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig in self.handlers:
            signal.signal(sig, signal.SIG_IGN)
        errors = []
        if self.fd is not None:
            try:
                if self.armed:
                    fcntl.ioctl(self.fd, pmic_rtc.RTC_AIE_OFF)
                    assert pmic_rtc.alarm(self.fd)[0] == 0
            except Exception as error:
                errors.append('alarm: ' + str(error))
            finally:
                os.close(self.fd)
                self.fd = None
        for path, inode in list(self.owned.items()):
            try:
                assert not path.is_symlink() and path.stat().st_ino == inode, 'shadow replaced; leave other owner untouched'
                path.unlink()
                del self.owned[path]
            except Exception as error:
                errors.append(str(error))
        if self.runtime_created and not self.owned:
            try:
                RUNTIME.rmdir()  # Never remove entries created by another owner.
            except OSError:
                pass  # An empty directory is not required for restoring the masks.
        try:
            if self.original_verified:
                subprocess.run(['systemctl', 'daemon-reload'], check=True, capture_output=True, timeout=15)
                for unit in UNITS:
                    mask = PERSISTENT / unit
                    assert mask.is_symlink() and os.readlink(mask) == '/dev/null' and not os.path.lexists(RUNTIME / unit)
                    values = dict(line.split('=', 1) for line in subprocess.check_output(
                        ['systemctl', 'show', unit, '-pLoadState', '-pFragmentPath'], text=True, timeout=5).splitlines())
                    assert values['LoadState'] == 'masked' and values['FragmentPath'] == str(mask)
        except Exception as error:
            errors.append('mask restoration: ' + str(error))
        finally:
            if self.idle is not None:
                if self.idle.poll() is None:
                    try:
                        os.killpg(self.idle.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    self.idle.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.idle.pid, signal.SIGKILL)
                    self.idle.communicate(timeout=3)
            for sig, handler in self.handlers.items():
                signal.signal(sig, handler)
        assert not errors, '; '.join(errors)
        return dict(masks_restored=self.original_verified, owned_files_removed=not self.owned,
                    idle_inhibitor_reaped=self.idle is None or self.idle.poll() is not None)
