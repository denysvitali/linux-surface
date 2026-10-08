#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded native BlueZ power/discovery trial; private peer data stays in RAM."""
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import time

ADAPTER = '/org/bluez/hci0'
INTERFACE = 'org.bluez.Adapter1'
POLICY = ('Alias', 'Pairable', 'Discoverable', 'PairableTimeout', 'DiscoverableTimeout')
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
MAC = r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})'
NEW = re.compile(r'\[NEW\]\s+Device\s+' + MAC + r'(?:\s|$)')
RSSI = re.compile(r'\[CHG\]\s+Device\s+' + MAC + r'\s+RSSI:\s+(?:-?\d+|0x[0-9a-fA-F]+)')


def unpack(value):
    if isinstance(value, dict):
        if set(value) == {'type', 'data'}:
            return unpack(value['data'])
        return {key: unpack(child) for key, child in value.items()}
    if isinstance(value, list):
        return [unpack(child) for child in value]
    return value


def idle(objects, discovering=False):
    assert [p for p, i in objects.items() if INTERFACE in i] == [ADAPTER], 'fitted hci0 required'
    adapter = objects[ADAPTER][INTERFACE]
    assert adapter['Discovering'] is discovering, 'unowned or missing discovery'
    assert adapter['Discoverable'] is False, 'discoverable user policy refused'
    assert objects[ADAPTER].get('org.bluez.LEAdvertisingManager1', {}).get('ActiveInstances', 0) == 0, 'advertising refused'
    for interfaces in objects.values():
        device = interfaces.get('org.bluez.Device1', {})
        assert not any(device.get(k, False) for k in ('Connected', 'Paired', 'Bonded', 'Trusted')), 'in-use or saved peripheral refused'
    return adapter


def policy(adapter):
    return {key: adapter[key] for key in POLICY + (('Connectable',) if 'Connectable' in adapter else ())}


class Discovery:
    """Start and stop discovery on the same persistent CLI D-Bus connection."""
    def __init__(self, live):
        self.live = live
        self.process = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env={**os.environ, 'LC_ALL': 'C', 'TERM': 'dumb'})
        os.set_blocking(self.process.stdout.fileno(), False)
        self.buffer = b''
        self.cached, self.new_peers, self.rssi_peers = set(), set(), set()
        self.new_count = self.rssi_count = 0
        self.started = self.stopped = False

    def send(self, command):
        assert self.process.poll() is None, 'owned discovery client exited'
        self.process.stdin.write((command + '\n').encode())
        self.process.stdin.flush()

    def line(self, value):
        value = ANSI.sub('', value)
        if 'Discovery started' in value:
            self.started = True
        if 'Discovery stopped' in value:
            self.stopped = True
        # Events after the start reply are tentative until Discovering=true is
        # confirmed by wait(). No counters are returned if confirmation fails.
        if not self.started or self.stopped:
            return
        match = NEW.search(value)
        if match and match[1].upper() not in self.cached:
            self.new_count += 1
            self.new_peers.add(match[1].upper())
        match = RSSI.search(value)
        if match:
            self.rssi_count += 1
            self.rssi_peers.add(match[1].upper())

    def pump(self, seconds=.1):
        assert self.process.poll() is None, 'owned discovery client exited'
        if select.select([self.process.stdout], [], [], seconds)[0]:
            chunk = os.read(self.process.stdout.fileno(), 16384)
            assert chunk, 'owned discovery client pipe closed'
            self.buffer += chunk
            assert len(self.buffer) <= 65536, 'discovery output framing overflow'
            parts = re.split(b'[\r\n]', self.buffer)
            self.buffer = parts.pop()
            for part in parts:
                self.line(part.decode('utf-8', errors='replace'))

    def wait(self, stopped=False, seconds=5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump()
            if (self.stopped if stopped else self.started) and self.live.discovering() is (not stopped):
                return
        raise RuntimeError('owned discovery start/stop not confirmed within5s')

    def start(self):
        end = time.monotonic() + .5
        while time.monotonic() < end:
            self.pump()
        objects = self.live.objects()
        idle(objects)
        self.cached = {i['org.bluez.Device1']['Address'].upper()
                       for i in objects.values() if 'org.bluez.Device1' in i}
        self.send('scan on')
        self.wait()

    def observe(self, seconds=5):
        assert seconds == 5 and self.started and not self.stopped
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(min(.1, end - time.monotonic()))
        idle(self.live.objects(), discovering=True)
        return dict(observation_seconds=seconds, discovery_start_confirmed=True,
                    discovery_active_confirmed=True, fresh_new_events=self.new_count,
                    fresh_rssi_events=self.rssi_count,
                    fresh_peer_count=len(self.new_peers | self.rssi_peers))

    def stop(self):
        if not self.stopped:
            self.send('scan off')
            self.wait(stopped=True)

    def run(self):
        self.start()
        result = self.observe()
        self.stop()
        result.pop('discovery_active_confirmed')
        result['discovery_stop_confirmed'] = True
        return result

    def identity(self):
        assert self.process.poll() is None, 'owned discovery client exited'
        proc = Path('/proc') / str(self.process.pid)
        ticks = int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[19])
        return dict(pid=self.process.pid, process_start_ticks=ticks,
                    child_pipes={str(fd): (proc / 'fd' / str(fd)).readlink().as_posix()
                                 for fd in (0, 1)},
                    parent_pipes={name: dict(fd=stream.fileno(), inode=os.fstat(stream.fileno()).st_ino)
                                  for name, stream in (('stdin', self.process.stdin), ('stdout', self.process.stdout))})

    def drain_after_thaw(self):
        """Discard queued deliveries, not a claim about radio transmission time."""
        end = time.monotonic() + 2
        discarded = 0

        def drain():
            nonlocal discarded
            while True:
                assert time.monotonic() < end, 'queued discovery drain exceeded2s'
                assert self.process.poll() is None, 'owned discovery client exited'
                try:
                    chunk = os.read(self.process.stdout.fileno(), 16384)
                except BlockingIOError:
                    return
                assert chunk, 'owned discovery client pipe closed'
                discarded += len(chunk)
                assert discarded <= 524288, 'queued discovery output exceeded bound'
        saved_deadline = self.live.deadline
        self.live.deadline = min(end, saved_deadline) if saved_deadline is not None else end
        try:
            drain()
            objects = self.live.objects()
            idle(objects, discovering=True)
            self.cached = {i['org.bluez.Device1']['Address'].upper()
                           for i in objects.values() if 'org.bluez.Device1' in i}
            drain()  # Also discard deliveries queued during the cache observation.
            self.buffer = b''
            self.new_peers.clear()
            self.rssi_peers.clear()
            self.new_count = self.rssi_count = 0
            assert self.started and not self.stopped, 'owned discovery lifecycle changed'
            return dict(queued_bytes_discarded=discarded, drain_reached_eagain=True,
                        partial_and_event_counters_cleared=True, cached_addresses_refreshed=True,
                        transmission_timestamps_proven=False)
        finally:
            self.live.deadline = saved_deadline

    def close(self):
        try:
            if self.process.poll() is None:
                try:
                    if not self.stopped:
                        self.send('scan off')
                        self.wait(stopped=True, seconds=2)
                    self.send('quit')
                except (AssertionError, RuntimeError, OSError, ValueError):
                    pass
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=1)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=1)
            self.process.stdin.close()
            self.process.stdout.close()
            self.buffer = b''
            self.cached.clear()
            self.new_peers.clear()
            self.rssi_peers.clear()
        self.live.wait_discovery_off()


class Live:
    def __init__(self, output, attempt, release):
        self.output, self.attempt, self.release = Path(output), attempt, release
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.client = None
        self.deadline = None

    def command(self, argv, timeout=3):
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            assert timeout > 0, 'Bluetooth test deadline expired'
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        assert proc.returncode == 0, 'bounded Bluetooth/network command failed'
        return proc.stdout.strip()

    def gate(self):
        assert os.geteuid() == 0 and os.uname().release == self.release
        assert re.fullmatch(r'[0-9]{8}[a-z0-9]+', self.attempt)
        words = Path('/proc/cmdline').read_text().split()
        assert 'spx_boot=mainline-functional' in words
        assert [w for w in words if w.startswith('spx_attempt=')] == ['spx_attempt=' + self.attempt]
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == self.boot
        assert Path('/proc/device-tree/model').read_bytes().startswith(b'Microsoft Surface Pro X')
        checked = json.loads((self.output.parent / 'functional.json').read_text())
        assert checked.get('complete') is True and checked['boot_id'] == self.boot
        assert checked['release'] == self.release, 'baseline kernel mismatch'
        prepared = json.loads((self.output.parent / 'prepared.json').read_text())
        assert prepared['attempt'] == self.attempt and prepared['release'] == self.release
        address = prepared['bluetooth_address']
        assert re.fullmatch(MAC, address), 'prepared Bluetooth address required'
        raw = bytes.fromhex(address.replace(':', ''))
        assert raw not in (b'\0' * 6, b'\xff' * 6) and not raw[0] & 1, 'invalid prepared public address'
        assert not (self.output.parent / 'return.json').exists(), 'return already requested'
        timer = 'spx-trial-return@' + self.attempt + '.timer'
        assert self.command(['systemctl', 'is-active', timer]) == 'active'
        timer_path = '/org/freedesktop/systemd1/unit/spx_2dtrial_2dreturn_40' + self.attempt + '_2etimer'
        value = self.command(['busctl', 'get-property', 'org.freedesktop.systemd1', timer_path,
                              'org.freedesktop.systemd1.Timer', 'NextElapseUSecMonotonic']).split()
        assert len(value) == 2 and value[0] == 't'
        assert int(value[1]) / 1e6 - time.monotonic() >= 120, '120s automatic return reserve required'
        jobs = self.command(['systemctl', 'list-jobs', '--no-legend', '--no-pager'])
        assert not re.search(r'spx-trial-return@|(?:systemd-suspend|sleep|suspend)\.(?:service|target)', jobs), 'conflicting job'
        return address.upper()

    def objects(self):
        reply = unpack(json.loads(self.command(['busctl', '--json=short', 'call', 'org.bluez', '/',
                                              'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects'])))
        assert isinstance(reply, list) and len(reply) == 1 and isinstance(reply[0], dict), 'invalid BlueZ object reply'
        return reply[0]

    def discovering(self):
        reply = unpack(json.loads(self.command(['busctl', '--json=short', 'get-property',
                                               'org.bluez', ADAPTER, INTERFACE, 'Discovering'])))
        assert type(reply) is bool, 'invalid Discovering property'
        return reply

    def rfkill(self):
        result = {entry.name: {k: (entry / k).read_text().strip() for k in ('name', 'type', 'soft', 'hard')}
                  for entry in Path('/sys/class/rfkill').glob('rfkill*')}
        fitted = [s for s in result.values() if s['name'] == 'hci0' and s['type'] == 'bluetooth']
        assert len(fitted) == 1 and fitted[0]['soft'] == fitted[0]['hard'] == '0', 'fitted radio blocked or absent'
        return result

    def network(self):
        state = self.command(['nmcli', '-g', 'GENERAL.STATE,GENERAL.CON-UUID', 'device', 'show', 'wlan0'])
        lines = state.splitlines()
        assert len(lines) == 2 and lines[0].startswith('100') and lines[1], 'wlan0 not connected'
        assert Path('/sys/class/net/wlan0/carrier').read_text().strip() == '1', 'wlan0 carrier absent'
        return state

    def snapshot(self, discovering=False, *, include_network=True):
        adapter = idle(self.objects(), discovering)
        assert adapter['Manufacturer'] == 29 and adapter['AddressType'] == 'public', 'fitted public QCA controller required'
        result = dict(address=adapter['Address'].upper(), policy=policy(adapter),
                      powered=adapter['Powered'], power_state=adapter['PowerState'],
                      rfkill=self.rfkill())
        if include_network:
            result['network'] = self.network()
        return result

    def set_power(self, powered):
        self.command(['busctl', 'set-property', 'org.bluez', ADAPTER, INTERFACE,
                      'Powered', 'b', 'true' if powered else 'false'])

    def settle(self, powered):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            adapter = idle(self.objects())
            if adapter['Powered'] is powered and adapter['PowerState'] == ('on' if powered else 'off'):
                return
            time.sleep(.1)
        raise RuntimeError('Powered/PowerState did not settle within5s')

    def wait_discovery_off(self):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if not self.discovering():
                return
            time.sleep(.1)
        raise RuntimeError('discovery active after owned client exit')

    def scan(self):
        self.client = Discovery(self)
        result = self.client.run()
        self.client.close()
        self.client = None
        return result

    def transfer(self):
        count = self.command(['curl', '--interface', 'wlan0', '-4', '--fail', '--silent', '--show-error',
                              '--max-time', '15', '-o', '/dev/null', '-w', '%{size_download}',
                              'https://speed.cloudflare.com/__down?bytes=1000000'], timeout=17)
        assert count == '1000000', 'WLAN1MB transfer incomplete'
        return 1000000


def unchanged(before, after, powered=True, *, include_network=True):
    keys = ('address', 'policy', 'rfkill') + (('network',) if include_network else ())
    for key in keys:
        assert before[key] == after[key], key + ' changed'
    assert after['powered'] is powered and after['power_state'] == ('on' if powered else 'off'), 'power preference not restored'


def error_text(error):
    # Subprocess exceptions may contain private replies: never serialize them.
    return str(error) if isinstance(error, (AssertionError, RuntimeError, InterruptedError)) else type(error).__name__


def exercise(live):
    result = dict(complete=False, boot_id=live.boot, release=live.release,
                  attempt=live.attempt, cycles=[], fixture_inconclusive=False,
                  pairing_reconnect_resume_acceptance=False)
    before, mutated, report_owned = None, False, False
    handlers = {}
    started = time.monotonic()

    def interrupted(signum, frame):
        raise InterruptedError('bounded Bluetooth trial interrupted')

    try:
        live.deadline = started + 70
        address = live.gate()
        assert not live.output.exists(), 'Bluetooth trial already consumed'
        before = live.snapshot()
        assert before['address'] == address, 'prepared controller address mismatch'
        assert before['powered'] is True and before['power_state'] == 'on', 'initial radio-off preference refused'
        live.output.mkdir(mode=0o700)
        report_owned = True
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
            handlers[signum] = signal.signal(signum, interrupted)
        signal.setitimer(signal.ITIMER_REAL, max(.01, live.deadline - time.monotonic()))
        for index in range(2):
            assert live.gate() == address
            unchanged(before, live.snapshot())
            mutated = True  # A failed D-Bus write may still have taken effect.
            live.set_power(False)
            live.settle(False)
            off = live.snapshot()
            assert off['address'] == address and off['rfkill'] == before['rfkill'], 'radio-off identity/rfkill changed'
            live.set_power(True)
            live.settle(True)
            unchanged(before, live.snapshot())
            cycle = dict(index=index + 1, powered_off_settled=True, powered_on_settled=True,
                         address_policy_rfkill_unchanged=True)
            result['cycles'].append(cycle)
            cycle.update(live.scan())
            unchanged(before, live.snapshot())
        result['fixture_inconclusive'] = any(c['fresh_peer_count'] == 0 for c in result['cycles'])
        if result['fixture_inconclusive']:
            raise RuntimeError('no fresh nearby reports in at least one cycle; fixture availability inconclusive')
        result['functional_cycles_passed'] = True
    except (Exception, KeyboardInterrupt) as error:
        result['error'] = error_text(error)
    finally:
        if handlers:
            signal.setitimer(signal.ITIMER_REAL, 0)
            for signum in handlers:
                signal.signal(signum, signal.SIG_IGN)
        live.deadline = started + 90
        if mutated:
            # A failed scan cleanup must not prevent restoring the initial power.
            try:
                if live.client is not None:
                    live.client.close()
                    live.client = None
                live.wait_discovery_off()
                result['owned_discovery_clients_reaped'] = True
            except (Exception, KeyboardInterrupt) as error:
                result['cleanup_error'] = error_text(error)
            try:
                live.set_power(before['powered'])
                live.settle(before['powered'])
                unchanged(before, live.snapshot(), before['powered'])
                result['original_power_policy_rfkill_address_restored'] = True
                result['wlan_same_connection'] = True
                result['wlan_download_bytes'] = live.transfer()
                assert live.network() == before['network'], 'WLAN connection changed during transfer'
            except (Exception, KeyboardInterrupt) as error:
                result['cleanup_error'] = error_text(error)
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        result['seconds'] = time.monotonic() - started
        result['complete'] = bool(result.get('functional_cycles_passed') and
                                  result.get('original_power_policy_rfkill_address_restored') and
                                  result.get('owned_discovery_clients_reaped') and
                                  result.get('wlan_download_bytes') == 1000000 and
                                  not result.get('error') and not result.get('cleanup_error'))
        if report_owned:
            (live.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
