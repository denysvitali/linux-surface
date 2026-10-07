#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fresh native discovery across one normal AC sleep, without radio power writes."""
from pathlib import Path
import signal
import subprocess
import time

import bluetooth_power as power
import systemd_sleep as sleep


class CommandFailure(RuntimeError):
    def __init__(self, stage, returncode=None, timed_out=False):
        self.status = dict(stage=stage, returncode=returncode, timed_out=timed_out)
        detail = 'timed out' if timed_out else 'failed with exit ' + str(returncode)
        super().__init__('Bluetooth ' + stage + ' ' + detail)


def command_stage(argv):
    if argv[:2] == ['busctl', 'set-property']:
        return 'fixture power request'
    if argv[0] == 'busctl':
        return 'native property observation'
    if argv[0] == 'nmcli':
        return 'WLAN observation'
    if argv[:2] == ['systemctl', 'show']:
        return 'BlueZ service identity observation'
    return 'native gate observation'


class Radio(power.Live):
    def command(self, argv, timeout=3):
        # This observer must never repair the radio to make its result pass.
        if 'set-property' in argv:
            assert getattr(self, 'fixture_window', False), 'Bluetooth property mutation refused outside fixture window'
            assert argv[:6] == ['busctl', 'set-property', 'org.bluez', power.ADAPTER, power.INTERFACE, 'Powered']
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            assert timeout > 0, 'Bluetooth test deadline expired'
        stage = command_stage(argv)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise CommandFailure(stage, timed_out=True) from None
        if proc.returncode != 0:
            raise CommandFailure(stage, returncode=proc.returncode)
        return proc.stdout.strip()

    def identity(self):
        values = dict(line.split('=', 1) for line in self.command([
            'systemctl', 'show', 'bluetooth.service', '-pActiveState', '-pSubState',
            '-pMainPID', '-pExecMainStartTimestampMonotonic']).splitlines())
        assert values['ActiveState'] == 'active' and values['SubState'] == 'running', 'native BlueZ service not running'
        pid = int(values['MainPID'])
        started = int(values['ExecMainStartTimestampMonotonic'])
        assert pid > 0 and started > 0, 'native BlueZ service identity missing'
        stat = (Path('/proc') / str(pid) / 'stat').read_text()
        # comm may contain spaces or parentheses; fields after its last ')' start
        # at field3. Field22 is the process start time in clock ticks.
        ticks = int(stat.rsplit(')', 1)[1].split()[19])
        assert ticks > 0, 'native BlueZ process start time missing'
        return dict(pid=pid, process_start_ticks=ticks, service_start_monotonic_us=started)


    def original(self):
        adapter = power.idle(self.objects())
        assert adapter['Manufacturer'] == 29 and adapter['AddressType'] == 'public', 'fitted public QCA controller required'
        states = {}
        for entry in Path('/sys/class/rfkill').glob('rfkill*'):
            state = {k: (entry / k).read_text().strip() for k in ('name', 'type', 'soft', 'hard')}
            key = state['type'] + ':' + state['name']
            assert key not in states, 'duplicate named rfkill device'
            states[key] = state
        assert 'bluetooth:hci0' in states and states['bluetooth:hci0']['hard'] == '0', 'fitted radio hardblocked or absent'
        assert states['bluetooth:hci0']['soft'] in ('0', '1')
        return dict(address=adapter['Address'].upper(), policy=power.policy(adapter),
                    powered=adapter['Powered'], power_state=adapter['PowerState'],
                    rfkill=states, network=self.network())

    def write_soft(self, value):
        assert self.fixture_window, 'rfkill write refused outside fixture window'
        entries = [p for p in Path('/sys/class/rfkill').glob('rfkill*')
                   if (p / 'name').read_text().strip() == 'hci0' and
                   (p / 'type').read_text().strip() == 'bluetooth']
        assert len(entries) == 1 and (entries[0] / 'hard').read_text().strip() == '0'
        (entries[0] / 'soft').write_text(value + '\n')
        assert (entries[0] / 'soft').read_text().strip() == value

    def fixture_needs_power_request(self, unblocked):
        # rfkill unblock can itself start BlueZ/QCA setup. Observe its native
        # transition first; a redundant Powered=true request can return InProgress.
        end = time.monotonic() + 5
        off_since = None
        while time.monotonic() < end:
            adapter = power.idle(self.objects())
            if adapter['Powered'] is True and adapter['PowerState'] == 'on':
                return False
            if adapter['Powered'] is False and adapter['PowerState'] == 'off':
                if off_since is None:
                    off_since = time.monotonic()
                if not unblocked or time.monotonic() - off_since >= 1:
                    return True
            else:
                off_since = None
            time.sleep(.1)
        raise RuntimeError('native fixture power transition did not settle within5s')

    def prepare_fixture(self, original, allow_radio_on):
        assert allow_radio_on is True, 'explicit radio-on fixture authorization required'
        self.fixture_window = True
        try:
            unblocked = original['rfkill']['bluetooth:hci0']['soft'] == '1'
            if unblocked:
                self.write_soft('0')
            if self.fixture_needs_power_request(unblocked):
                self.set_power(True)
                self.settle(True)
            current = self.original()
            for key in ('address', 'policy', 'network'):
                assert current[key] == original[key], 'radio fixture changed ' + key
            expected = {k: dict(v) for k, v in original['rfkill'].items()}
            expected['bluetooth:hci0']['soft'] = '0'
            assert current['rfkill'] == expected, 'unrelated rfkill state changed'
        finally:
            self.fixture_window = False

    def restore_fixture(self, original):
        self.fixture_window = True
        try:
            current = power.idle(self.objects())
            if current['Powered'] is not original['powered']:
                self.set_power(original['powered'])
            self.write_soft(original['rfkill']['bluetooth:hci0']['soft'])
        finally:
            self.fixture_window = False
        end = time.monotonic() + 5
        while True:
            current = self.original()
            if current == original:
                return
            assert time.monotonic() < end, 'original radio power/policy/rfkill/network not restored'
            time.sleep(.1)


def scan_proven(result):
    return bool(result.get('observation_seconds') == 5 and
                result.get('discovery_start_confirmed') is True and
                result.get('discovery_stop_confirmed') is True and
                result.get('fresh_peer_count', 0) > 0 and
                result.get('fresh_new_events', 0) + result.get('fresh_rssi_events', 0) > 0)


def require_same(radio, before, identity):
    power.unchanged(before, radio.snapshot())
    assert radio.identity() == identity, 'native BlueZ PID/start time changed'


def exercise(ops, radio=None, *, allow_radio_on=False):
    result = dict(complete=False, scope='fresh Bluetooth discovery before/after one normal30s AC s2idle',
                  audio_tested=False, audio_mode='parked-retention',
                  full_suspend_acceptance=False, pairing_reconnect_acceptance=False,
                  fixture_inconclusive=False, scans={}, resume_radio_power_written=False,
                  radio_fixture=dict(authorized=allow_radio_on, changed=False, restored=False))
    radio = radio or Radio(ops.output, ops.attempt, ops.release)
    before = identity = original = None
    fixture_changed = False
    started = time.clock_gettime(time.CLOCK_BOOTTIME)
    try:
        assert ops.parked_audio is True, 'loaded parked-audio sleep contract required'
        result['before'] = ops.gate()
        radio.deadline = ops.started + 95
        assert radio.boot == ops.boot, 'Bluetooth/sleep boot mismatch'
        address = radio.gate()
        original = radio.original()
        assert original['address'] == address, 'prepared controller address mismatch'
        identity = radio.identity()
        soft = original['rfkill']['bluetooth:hci0']['soft']
        ready = original['powered'] is True and original['power_state'] == 'on' and soft == '0'
        if not ready:
            assert original['powered'] is False and original['power_state'] in ('off', 'off-blocked'), 'unsupported initial power state'
            assert allow_radio_on is True, 'initial radio-off preference requires explicit --allow-radio-on fixture authorization'
            fixture_changed = True  # A failed first write may still take effect.
            result['radio_fixture']['changed'] = True
            radio.prepare_fixture(original, allow_radio_on)
        before = radio.snapshot()
        require_same(radio, before, identity)
        result['phase'] = 'admitted-native-radio-and-parked-audio'
        ops.save(result)
        result['direct_prerequisite'] = ops.direct()
        ops.gate()  # Original native sleep gates and 360s return reserve.
        assert radio.gate() == address, 'prepared controller address changed'
        require_same(radio, before, identity)
        result['scans']['before'] = radio.scan()
        if not scan_proven(result['scans']['before']):
            result['fixture_inconclusive'] = result['scans']['before'].get('fresh_peer_count', 0) == 0
            raise RuntimeError('fresh pre-sleep discovery proof missing')
        require_same(radio, before, identity)
        result['phase'] = 'fresh-discovery-before-normal-suspend'
        ops.save(result)
        ops.inhibit_idle()
        ops.open_shadows()
        result['sleep'] = ops.sleep()
        assert sleep.sleep_proven(result['sleep']), 'normal-service/RTC/kernel/thaw proof incomplete'
        result['after'] = ops.post(result['before'])
        require_same(radio, before, identity)
        result['scans']['after'] = radio.scan()
        if not scan_proven(result['scans']['after']):
            result['fixture_inconclusive'] = result['scans']['after'].get('fresh_peer_count', 0) == 0
            raise RuntimeError('fresh post-sleep discovery proof missing')
        require_same(radio, before, identity)
        result['same_controller_policy_rfkill_network'] = True
        result['same_native_bluez_process'] = True
        result['functional_pass'] = True
    except (Exception, KeyboardInterrupt) as error:
        # Bluetooth command failures deliberately omit their private replies.
        result['error'] = type(error).__name__ + ': ' + power.error_text(error)
        if isinstance(error, CommandFailure):
            result['command_failure'] = error.status
        if hasattr(ops, 'sleep_result'):
            result['sleep'] = ops.sleep_result
    finally:
        # Reap the persistent discovery connection before touching sleep masks,
        # alarm or PM leases. A failed scanner cleanup cannot skip sleep cleanup.
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig in ops.handlers:
            signal.signal(sig, signal.SIG_IGN)
        radio.deadline = time.monotonic() + 30
        try:
            if radio.client is not None:
                radio.client.close()
                radio.client = None
            if before is not None:
                radio.wait_discovery_off()
                require_same(radio, before, identity)
            result['owned_discovery_clients_reaped'] = True
        except (Exception, KeyboardInterrupt) as error:
            result['scanner_cleanup_error'] = power.error_text(error)
        try:
            if fixture_changed:
                radio.restore_fixture(original)
            if original is not None:
                assert radio.original() == original, 'original radio state changed'
                assert radio.identity() == identity, 'native BlueZ identity changed during fixture cleanup'
            result['radio_fixture']['restored'] = True
        except (Exception, KeyboardInterrupt) as error:
            result['fixture_cleanup_error'] = power.error_text(error)
        try:
            result['cleanup'] = ops.cleanup()
        except (Exception, KeyboardInterrupt) as error:
            result['cleanup_error'] = power.error_text(error)
        cleanup = result.get('cleanup', {})
        result['complete'] = bool(result.get('functional_pass') and
                                  result.get('owned_discovery_clients_reaped') and
                                  result['radio_fixture']['restored'] is True and
                                  all(cleanup.get(k) for k in ('masks_restored', 'owned_files_removed', 'idle_inhibitor_reaped')) and
                                  cleanup.get('parked_audio', {}).get('restored') is True and
                                  not any(k in result for k in ('error', 'scanner_cleanup_error', 'fixture_cleanup_error', 'cleanup_error')))
        result['wall_seconds'] = time.clock_gettime(time.CLOCK_BOOTTIME) - started
        ops.save(result)
    return result
