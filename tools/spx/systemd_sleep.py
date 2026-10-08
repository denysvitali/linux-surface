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
import traceback

import pmic_rtc
from sensors import lifecycle

UNITS = ('sleep.target', 'suspend.target')
AUDIO = {'wcd934x', 'soundwire_qcom', 'snd_soc_wsa881x', 'snd_soc_wcd934x'}
WHO = 'spx-systemd-suspend'
RUNTIME = Path('/run/systemd/system.control')
PERSISTENT = Path('/etc/systemd/system')
STOCK = Path('/usr/lib/systemd/system')
RETAIN_ENTRY = 'SPX: WIP s2idle retention: keeping powered PIO core'
RETAIN_EXIT = 'SPX: WIP s2idle retention: ownership preserved'
FAULTS = re.compile(r'BUG:|Oops:|Call trace:|Kernel panic|blocked for more than|'
                   r'SMMU.*fault|watchdog received|fatal error received|crash detected in|'
                   r'firmware crashed|timeout waiting for shutdown response|'
                   r's2idle retention refused|s2idle retention lost controller invariants', re.I)


def audio_mode_gate(parked_audio, prepared, words, loaded, retention):
    """The default remains audio-blocked; retention requires explicit preparation."""
    assert type(parked_audio) is bool
    blocked = {n for w in words if w.startswith('module_blacklist=')
               for n in w.split('=', 1)[1].split(',')}
    if not parked_audio:
        assert AUDIO <= blocked and not AUDIO & loaded
        assert prepared.get('audio_mode') == 'blocked'
        return
    assert prepared.get('audio_mode') == 'parked'
    assert prepared.get('slim_s2idle_retain') is True and prepared.get('pmic_rtc') is True
    assert 'spx_audio=parked' in words
    assert 'slim_qcom_ngd_ctrl.spx_s2idle_retain=1' in words
    assert AUDIO <= loaded and not AUDIO & blocked
    assert retention == 'Y', 'readonly NGD powered-retention option not enabled'


def retention_proven(log):
    entries = [m.start() for m in re.finditer(re.escape(RETAIN_ENTRY), log)]
    exits = [m.start() for m in re.finditer(re.escape(RETAIN_EXIT), log)]
    faults = [line for line in log.splitlines() if FAULTS.search(line)]
    assert not faults, 'fresh kernel faults: ' + '; '.join(faults)
    assert entries and len(entries) == len(exits), 'fresh NGD retention callbacks missing'
    assert all(a < b and (i + 1 == len(entries) or b < entries[i + 1])
               for i, (a, b) in enumerate(zip(entries, exits))), 'NGD retention callback ordering'
    return dict(complete=True, powered_retention=True, energy_saving_claim=False,
                entry_count=len(entries), ownership_preserved_count=len(exits), new_kernel_faults=[])


def playback_resume_proven(log):
    """Require one successful, ordered playback PAUSE/ACK/RUN in a PM cycle."""
    patterns = (
        r'PM: suspend entry \(s2idle\)',
        r'SPX: retained ASM pause sent direction=0 pending-writes=\d+ error=0(?:\n|$)',
        r'SPX: retained ASM pause acknowledged direction=0(?:\n|$)',
        r'SPX: retained ASM resumed direction=0 pending-writes=\d+ deferred-reads=\d+ error=0(?:\n|$)',
        r'PM: suspend exit',
    )
    positions = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, log))
        assert len(matches) == 1, 'one normal playback resume marker required: ' + pattern
        positions.append(matches[0].start())
    assert positions == sorted(positions), 'playback pause/ack/resume/PM ordering'
    return dict(complete=True, direction=0, marker_positions=positions)


class ParkedAudio:
    """Own an active SWR PM hold and only the safe auxiliary GPIO park write."""
    def __init__(self, output, boot, desktop_user):
        import audio
        self.audio, self.output, self.boot = audio, output, boot
        self.desktop_user = desktop_user
        self.control = self.writer = self.master = self.saved_control = None
        self.report = dict(powered_retention=True, energy_saving_claim=False,
                           playback_or_capture_opened=False,
                           firmware_sessions_proven_absent=False, restored=False)

    def idle(self):
        for name in ('audio-request.json', 'audio-started.json', 'desktop-audio.json'):
            assert not (self.output / name).exists(), 'audio request/start/persistent policy present'
        assert not (self.output / 'audio-started-boots' / (self.boot + '.json')).exists()
        self.audio.assert_desktop_paused(self.desktop_user)
        statuses = {str(p): self.audio.read_text(p)
                    for p in Path('/proc/asound').glob('card*/pcm*/sub*/status')}
        assert statuses and all(v == 'closed' for v in statuses.values()), 'playback/capture PCM open'
        return statuses

    @staticmethod
    def parked(snapshot, auxiliary_required=True):
        assert snapshot['GPIO_DIR'] & 0x1e == 0x1e, 'GPIO direction changed'
        assert snapshot['GPIO_VAL'] & 0x06 == 0, 'speaker amplifier enabled'
        assert snapshot['SLV_STATUS'] == 0, 'physical SoundWire slave attached'
        assert snapshot['FIFO_STATUS'] & 0x1f1f00 == 0, 'SoundWire command FIFO nonempty'
        assert all(snapshot[f'DP{p}_B{b}'] & 0xff000000 == 0
                   for p in (1, 4) for b in (0, 1)), 'SoundWire port enabled'
        if auxiliary_required:
            assert snapshot['GPIO_VAL'] & 0x1e == 0x18, 'auxiliary GPIO park lost'

    def check(self):
        statuses = self.idle()
        assert self.audio.read_text(self.control) == 'on'
        assert self.audio.read_text(self.master / 'power/runtime_status') == 'active'
        sample = self.audio.inventory(self.master)
        assert len(sample['internal_cards']) == 1
        assert len(sample['devices']) == 2 and {d['unit'] for d in sample['devices']} == {3, 4}
        assert all(d['status'] == 'UNATTACHED' and d['driver'] == 'wsa881x-codec'
                   for d in sample['devices']), 'native WSA codecs not unattached'
        self.parked(sample['state'], auxiliary_required=False)
        sample['pcm_statuses'] = statuses
        return sample

    def establish(self):
        self.idle()
        for name, expected in (('spx_wsa_gpio_mask', 0x1e), ('spx_wsa_gpio_dir', 0x1e),
                               ('spx_wsa_gpio_val', 0x18), ('spx_wsa_en_pin', -1)):
            assert int(self.audio.parameter('wcd934x', name), 0) == expected
        for name in ('spx_force_attach', 'spx_blind_attach', 'spx_core_enum', 'spx_watchdog'):
            assert self.audio.parameter('soundwire_qcom', name) == '0'
        for module, name, expected in (
                ('soundwire_qcom', 'spx_exact_windows_init', 'N'),
                ('soundwire_qcom', 'spx_broadcast_audio', 'N'),
                ('snd_soc_wsa881x', 'spx_enumerated_mode', 'Y'),
                ('snd_soc_wsa881x', 'spx_write_only', 'N'),
                ('slim_qcom_ngd_ctrl', 'spx_pio_mode', 'Y')):
            assert self.audio.parameter(module, name) == expected
        self.writer, self.master = self.audio.codec_paths()
        assert self.writer.exists(), 'page-safe WCD GPIO writer missing'
        self.control = self.master / 'power/control'
        self.saved_control = self.audio.read_text(self.control)
        assert self.saved_control in ('auto', 'on')
        self.report.update(master=str(self.master), saved_control=self.saved_control)
        self.control.write_text('on\n')
        end = time.monotonic() + 2
        while self.audio.read_text(self.master / 'power/runtime_status') != 'active':
            assert time.monotonic() < end, 'SWR master failed to resume'
            time.sleep(.05)
        before = self.check()
        self.report['before'] = before
        # Exactly audio.initialize's cold-start repair: outputs 3/4 high while
        # amp enables 1/2 stay low; preserve every unrelated GPIO bit.
        value = before['state']['GPIO_VAL'] | 0x18
        self.report['auxiliary_park_write_owned'] = value != before['state']['GPIO_VAL']
        if self.report['auxiliary_park_write_owned']:
            self.writer.write_text(f'43 {value:02x}\n')
        after = self.check()
        self.parked(after['state'])
        assert after['state']['GPIO_VAL'] == value, 'auxiliary park readback mismatch'
        self.report['held'] = after
        return after

    def retained(self, before):
        after = self.check()
        self.parked(after['state'])
        assert after['state']['GPIO_VAL'] == before['state']['GPIO_VAL']
        assert after['internal_cards'] == before['internal_cards']
        assert after['devices'] == before['devices'], 'native codec ownership/status changed'
        assert after['pcm_statuses'] == before['pcm_statuses']
        return after

    def cleanup(self):
        try:
            if 'held' in self.report:
                self.report['after'] = self.retained(self.report['held'])
            elif 'auxiliary_park_write_owned' in self.report:
                self.report['after'] = self.check()
                self.parked(self.report['after']['state'])
        finally:
            if self.saved_control in ('auto', 'on'):
                self.control.write_text(self.saved_control + '\n')
                assert self.audio.read_text(self.control) == self.saved_control
                self.report['restored'] = True
        return self.report


def sleep_proven(r):
    return bool(r['boot_unchanged'] and 15 <= r['sleep_seconds'] <= 45 and
                r['kernel_entered'] and r['kernel_exited'] and r['service_completed'] and
                r['irq_after'] > r['irq_before'] and r['event'] & 0x20 and r['event'] & 0x80 and
                r['alarm_disabled'] and r['user_thawed'])


def journal_completed(records):
    starts = [r for r in records if r.get('UNIT') == 'systemd-suspend.service' and r.get('MESSAGE_ID') == '7d4958e842da4a758f6c1cdc7b36dcc5' and r.get('JOB_TYPE') == 'start']
    finishes = [r for r in records if r.get('UNIT') == 'systemd-suspend.service' and r.get('MESSAGE_ID') == '39f53479d3a045ac8e11786248231fbf' and r.get('JOB_TYPE') == 'start' and r.get('JOB_RESULT') == 'done']
    for start in starts:
        for finish in finishes:
            between = [r for r in records if int(start['__MONOTONIC_TIMESTAMP']) <= int(r['__MONOTONIC_TIMESTAMP']) <= int(finish['__MONOTONIC_TIMESTAMP']) and r.get('_SYSTEMD_UNIT') == 'systemd-suspend.service']
            wanted = ["Successfully froze unit 'user.slice'.", "Performing sleep operation 'suspend'...", "System returned from sleep operation 'suspend'.", "Successfully thawed unit 'user.slice'."]
            position, invocation = 0, None
            for r in between:
                if r.get('MESSAGE') == wanted[position] and r.get('_SYSTEMD_INVOCATION_ID'):
                    invocation = invocation or r['_SYSTEMD_INVOCATION_ID']
                    if r['_SYSTEMD_INVOCATION_ID'] == invocation:
                        position += 1
                        if position == len(wanted):
                            return True
    return False


def service_completed(before, after, fresh_journal=False):
    return (after['ActiveState'] == 'inactive' and after['SubState'] == 'dead' and
            after['Result'] == 'success' and after['ExecMainStatus'] == '0' and
            (fresh_journal or int(after['ExecMainExitTimestampMonotonic']) > int(before['ExecMainExitTimestampMonotonic'])))


def exercise(ops):
    result = dict(complete=False, scope='normal30s systemd s2idle on AC; retained network/sensors and disposable storage',
                  full_suspend_acceptance=False, audio_tested=False,
                  audio_mode='parked-retention' if getattr(ops, 'parked_audio', False) else 'blocked')
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
        result['error'] = type(error).__name__ + ': ' + str(error)
        result['traceback'] = traceback.format_exc()
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


def verify_returned(ops, original):
    """Verify an already returned sleep independently, preserving its failed report."""
    result = dict(complete=False, scope='independent same-boot normal-suspend recovery verification',
                  full_suspend_acceptance=False, audio_tested=False,
                  audio_mode='parked-retention' if getattr(ops, 'parked_audio', False) else 'blocked',
                  source_result=str(ops.output.parent / 'systemd-suspend/result.json'))
    try:
        ops.gate()
        assert original['boot_id'] == ops.boot and original['release'] == ops.release
        assert original.get('audio_mode', 'blocked') == result['audio_mode'], 'sleep audio mode mismatch'
        assert original['attempt'] == ops.attempt and original['direct_prerequisite']['complete']
        assert all(original['cleanup'][k] for k in ('masks_restored', 'owned_files_removed', 'idle_inhibitor_reaped'))
        assert any(x['name'] == 'normal-suspend' and x['returncode'] == 0 for x in original['steps'])
        cursor = next(x['stdout'].split('-- cursor: ')[1].strip() for x in original['steps'] if x['name'] == 'cursor')
        proof = ops.service_evidence(cursor)
        result['fresh_service_journal_completed'] = proof
        r = dict(original['sleep'])
        r['service_completed'] = proof
        assert sleep_proven(r), 'original sleep plus fresh normal-service journal incomplete'
        fd = os.open('/dev/rtc1', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            assert pmic_rtc.alarm(fd)[:2] == (0, 0), 'alarm not disabled'
        finally:
            os.close(fd)
        result['verified_sleep'] = r
        if getattr(ops, 'parked_audio', False):
            result['audio_retention'] = ops.retention_evidence(cursor, 'verified-sleep-kernel')
            assert original['direct_prerequisite']['audio_retention']['complete'] is True
        result['after'] = ops.post(original['before'])
        result['functional_pass'] = True
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        result['traceback'] = traceback.format_exc()
    finally:
        try:
            result['cleanup'] = ops.cleanup()
        except Exception as error:
            result['cleanup_error'] = str(error)
        result['complete'] = bool(result.get('functional_pass') and result.get('cleanup', {}).get('masks_restored'))
        ops.save(result)
    return result


class Live:
    def __init__(self, output, attempt, release, *, parked_audio=False, desktop_user='dvitali', default_mic_resume=False, native_mic_resume=False):
        assert type(parked_audio) is bool and type(default_mic_resume) is bool and type(native_mic_resume) is bool
        assert not (default_mic_resume and native_mic_resume), 'microphone resume modes exclude each other'
        assert not native_mic_resume or parked_audio, 'native microphone work budget requires audio retention'
        assert not default_mic_resume or parked_audio, 'extended work budget requires default microphone retention'
        self.active_budget = 220 if native_mic_resume else 140 if default_mic_resume else 100
        self.budget = dict(active_work_seconds=self.active_budget,
                           command_window_seconds=self.active_budget - 5,
                           extension_scope=('bounded pre/post native verification and post-teardown infrastructure work'
                                            if native_mic_resume else 'post-teardown infrastructure work'
                                            if default_mic_resume else 'none'))
        self.output, self.attempt, self.release = output, attempt, release
        self.parked_audio, self.desktop_user, self.audio = parked_audio, desktop_user, None
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
        # Recording caps remain independent: legacy live capture120s wall,
        # or native oracle90s plus separate pre/post60s BOOTTIME phases.
        # The native source is idle (capture closed) throughout normal sleep.
        signal.setitimer(signal.ITIMER_REAL, self.active_budget)

    def run(self, name, argv, timeout=5):
        remaining = self.active_budget - 5 - (time.monotonic() - self.started)
        assert remaining > 0, 'helper deadline'
        p = subprocess.run(argv, text=True, capture_output=True, timeout=min(timeout, remaining))
        self.steps.append(dict(name=name, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr))
        assert p.returncode == 0, name + ': ' + p.stderr.strip()
        return p.stdout.strip()

    def properties(self, unit, *names):
        text = self.run(unit, ['systemctl', 'show', unit, *['-p' + name for name in names]])
        return dict(line.split('=', 1) for line in text.splitlines())

    def save(self, result):
        result.update(attempt=self.attempt, release=self.release, boot_id=self.boot, steps=self.steps, helper_budget=self.budget)
        if self.audio is not None:
            result['parked_audio'] = self.audio.report
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
        assert Path('/sys/class/net/wlan0/carrier').read_text().strip() == '1', 'wlan0 carrier absent'
        return state

    def connected_network(self):
        end = time.monotonic() + 20
        while True:
            try:
                return self.network()
            except AssertionError:
                if time.monotonic() >= end:
                    raise
                time.sleep(.5)

    def gate(self):
        assert os.geteuid() == 0 and os.uname().release == self.release
        assert re.fullmatch(r'[0-9]{8}[a-z0-9]+', self.attempt)
        words = Path('/proc/cmdline').read_text().split()
        assert [w for w in words if w.startswith('spx_attempt=')] == ['spx_attempt=' + self.attempt]
        assert 'spx_boot=mainline-functional' in words and 'spx_sensors=1' in words
        parked_audio = getattr(self, 'parked_audio', False)
        if not parked_audio:
            blocked = {n for w in words if w.startswith('module_blacklist=') for n in w.split('=', 1)[1].split(',')}
            assert AUDIO <= blocked and not any((Path('/sys/module') / n).exists() for n in AUDIO)
        assert Path('/proc/self/cgroup').read_text().strip() == '0::/system.slice/spx-systemd-suspend.service', 'owned system.slice transient unit required'
        for name in ('functional', 'pmic-rtc/result'):
            data = json.loads((self.output.parent / (name + '.json')).read_text())
            assert data.get('complete') is True and data['boot_id'] == self.boot and data['release'] == self.release
        prepared = json.loads((self.output.parent / 'prepared.json').read_text())
        assert prepared['release'] == self.release and prepared.get('pmic_rtc') is True
        loaded = {n for n in AUDIO if (Path('/sys/module') / n).exists()}
        retention = Path('/sys/module/slim_qcom_ngd_ctrl/parameters/spx_s2idle_retain').read_text().strip() if parked_audio else None
        audio_mode_gate(parked_audio, prepared, words, loaded, retention)
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
        audio_before = None
        if parked_audio:
            if self.audio is None:
                self.audio = ParkedAudio(self.output.parent, self.boot, self.desktop_user)
                audio_before = self.audio.establish()
            else:
                audio_before = self.audio.retained(self.audio.report['held'])
        if self.sensor is None:
            self.sensor = lifecycle.Live(self.output / 'sensor-observations', self.attempt, self.release)
        before = dict(services=self.services(), network=self.connected_network(), streams=self.streams('before'))
        if audio_before is not None:
            before['parked_audio'] = audio_before
        return before

    def journal_cursor(self, name):
        return re.search(r'-- cursor: (\S+)', self.run(name, ['journalctl', '-b', '--show-cursor', '-n', '0', '--no-pager']))[1]

    def retention_evidence(self, cursor, name):
        log = self.run(name, ['journalctl', '-b', '-k', '--after-cursor=' + cursor, '--no-pager', '-o', 'short-monotonic'])
        (self.output / (name + '.log')).write_text(log)
        evidence = retention_proven(log)
        assert 'PM: suspend entry (s2idle)' in log and 'PM: suspend exit' in log
        evidence['journal_cursor'] = cursor
        hook = getattr(self.audio, 'accept_normal_resume', None)
        if hook is not None and name == 'normal-retention-kernel':
            assert sleep_proven(self.sleep_result), 'normal sleep proof required before playback timestamp refresh'
            evidence['playback_resume'] = playback_resume_proven(log)
            hook(dict(normal_sleep_proven=True, ngd_retention_proven=evidence['complete'],
                      journal_cursor=cursor, playback_resume=evidence['playback_resume']))
        evidence['after'] = self.audio.retained(self.audio.report['held'])
        return evidence

    def direct(self):
        output = self.output.parent / 'pmic-rtc-suspend'
        if output.exists():
            r = json.loads((output / 'result.json').read_text())
            assert r.get('complete') is True and r['boot_id'] == self.boot and r['release'] == self.release
            if self.parked_audio:
                proof = r.get('audio_retention', {})
                assert proof.get('complete') is True, 'same-boot parked-audio direct prerequisite missing'
                r['audio_retention'] = self.retention_evidence(proof['journal_cursor'], 'direct-kernel')
        else:
            cursor = self.journal_cursor('direct-cursor') if self.parked_audio else None
            r = pmic_rtc.exercise(output, self.attempt, self.release, suspend=True)
            if self.parked_audio and r.get('complete') is True:
                r['audio_retention'] = self.retention_evidence(cursor, 'direct-kernel')
                (output / 'result.json').write_text(json.dumps(r, indent=2) + '\n')
        assert r.get('complete') is True and r['boot_id'] == self.boot and r['release'] == self.release
        assert r['requested_seconds'] == 15 and r['sleep_seconds'] >= 10
        result = dict(complete=True, result=str(output / 'result.json'))
        if self.parked_audio:
            result['audio_retention'] = r['audio_retention']
        return result

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

    def service_evidence(self, cursor):
        log = self.run('sleep-service-journal', ['journalctl', '-b', '-u', 'systemd-suspend.service',
            '--after-cursor=' + cursor, '--no-pager', '-o', 'json'])
        (self.output / 'sleep-service-journal.jsonl').write_text(log + '\n')
        return journal_completed([json.loads(line) for line in log.splitlines()])

    def sleep(self):
        self.ac()
        self.fd = os.open('/dev/rtc1', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        assert pmic_rtc.alarm(self.fd)[:2] == (0, 0), 'preexisting alarm left untouched'
        r = dict(requested_alarm_seconds=30, minimum_real_sleep_seconds=15, irq_before=pmic_rtc.irq_count())
        self.sleep_result = r
        cursor = self.journal_cursor('cursor')
        r['journal_cursor'] = cursor
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
        # login1 avoids systemctl's separate logged-in-user veto. Flag1
        # honours block and block-weak inhibitors; delay locks remain active.
        self.run('normal-suspend', ['busctl', 'call', 'org.freedesktop.login1',
            '/org/freedesktop/login1', 'org.freedesktop.login1.Manager',
            'SuspendWithFlags', 't', '1'], 10)
        # The command queues asynchronously; only the service's fresh completion counts.
        end = time.clock_gettime(time.CLOCK_BOOTTIME) + 45
        completed = False
        while time.clock_gettime(time.CLOCK_BOOTTIME) < end:
            after = self.properties('systemd-suspend.service', 'ActiveState', 'SubState', 'Result', 'ExecMainStatus', 'ExecMainExitTimestampMonotonic')
            completed = service_completed(before, after, self.service_evidence(cursor) if after['ActiveState'] == 'inactive' else False)
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
        if self.parked_audio:
            r['audio_retention'] = self.retention_evidence(cursor, 'normal-retention-kernel')
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
        if self.parked_audio:
            after['parked_audio'] = self.audio.retained(before['parked_audio'])
        return after

    def cleanup(self):
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig in self.handlers:
            signal.signal(sig, signal.SIG_IGN)
        errors = []
        audio_cleanup = None
        if getattr(self, 'audio', None) is not None:
            try:
                audio_cleanup = self.audio.cleanup()
            except Exception as error:
                errors.append('audio PM restoration/park: ' + str(error))
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
        result = dict(masks_restored=self.original_verified, owned_files_removed=not self.owned,
                      idle_inhibitor_reaped=self.idle is None or self.idle.poll() is not None)
        if audio_cleanup is not None:
            result['parked_audio'] = audio_cleanup
        return result
