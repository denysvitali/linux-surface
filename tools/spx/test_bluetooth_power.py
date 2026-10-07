#!/usr/bin/python3
"""Offline admission, restoration, private-event and owned-discovery checks."""
import copy
import io
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch

import bluetooth_power as power

ADDRESS = 'C0:01:02:03:04:05'
CACHED = '10:20:30:40:50:60'
FRESH = '20:30:40:50:60:70'


def objects():
    return {power.ADAPTER: {power.INTERFACE: dict(Address=ADDRESS, AddressType='public',
            Manufacturer=29, Alias='PRIVATE-ALIAS', Pairable=True, Discoverable=False,
            PairableTimeout=0, DiscoverableTimeout=180, Connectable=False,
            Powered=True, PowerState='on', Discovering=False),
            'org.bluez.LEAdvertisingManager1': dict(ActiveInstances=0)},
            power.ADAPTER + '/dev_cached': {'org.bluez.Device1': dict(Address=CACHED)}}


class Fake(power.Live):
    def __init__(self, output):
        self.output, self.attempt, self.release = Path(output), '20261007test', 'test-kernel'
        self.boot, self.client, self.deadline = 'test-boot', None, None
        self.data = objects()
        self.writes, self.scans = [], 0
        self.failure = None

    def gate(self):
        return ADDRESS

    def objects(self):
        return copy.deepcopy(self.data)

    def rfkill(self):
        return {'fitted': dict(name='hci0', type='bluetooth', soft='0', hard='0')}

    def network(self):
        return '100 (connected)\nPRIVATE-NETWORK-UUID'

    def set_power(self, value):
        self.writes.append(value)
        self.data[power.ADAPTER][power.INTERFACE].update(Powered=value, PowerState='on' if value else 'off')
        if len(self.writes) == 1 and self.failure == 'write':
            raise RuntimeError('write completion uncertain')
        if len(self.writes) == 1 and self.failure == 'signal':
            signal.raise_signal(signal.SIGTERM)

    def wait_discovery_off(self):
        if self.failure == 'stop':
            raise RuntimeError('owned scan cleanup failed')

    def scan(self):
        self.scans += 1
        if self.failure == 'scan':
            self.client = Mock()
            raise RuntimeError('scan failed')
        if self.failure == 'later-connected':
            self.data[power.ADAPTER + '/dev_cached']['org.bluez.Device1']['Connected'] = True
        return dict(fresh_peer_count=0 if self.failure == 'no-peer' else 1,
                    fresh_new_events=0, fresh_rssi_events=1,
                    discovery_start_confirmed=True, discovery_stop_confirmed=True)

    def transfer(self):
        return 1000000


class PowerTests(unittest.TestCase):
    def test_refuses_user_or_peripheral_state_before_power_writes(self):
        for kind in ('off', 'connected', 'paired', 'bonded', 'trusted', 'discovering', 'discoverable', 'advertising', 'manufacturer', 'address'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                live = Fake(Path(directory) / 'run')
                adapter = live.data[power.ADAPTER][power.INTERFACE]
                if kind == 'off': adapter.update(Powered=False, PowerState='off')
                elif kind in ('connected', 'paired', 'bonded', 'trusted'):
                    live.data[power.ADAPTER + '/dev_cached']['org.bluez.Device1'][kind.capitalize()] = True
                elif kind in ('discovering', 'discoverable'): adapter[kind.capitalize()] = True
                elif kind == 'advertising': live.data[power.ADAPTER]['org.bluez.LEAdvertisingManager1']['ActiveInstances'] = 1
                elif kind == 'manufacturer': adapter['Manufacturer'] = 42
                else: adapter['Address'] = FRESH
                result = power.exercise(live)
                self.assertFalse(result['complete'])
                self.assertEqual(live.writes, [])
                self.assertFalse(live.output.exists())

    def test_nonroot_gate_never_contacts_bluez(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Fake(Path(directory) / 'run')
            live.gate = lambda: power.Live.gate(live)
            with patch.object(power.os, 'geteuid', return_value=1000), patch.object(power.subprocess, 'run') as run:
                result = power.exercise(live)
            self.assertFalse(result['complete'])
            run.assert_not_called()
            self.assertEqual(live.writes, [])

    def test_two_cycles_require_fresh_reports_and_omit_private_values(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Fake(Path(directory) / 'run')
            result = power.exercise(live)
            self.assertTrue(result['complete'])
            self.assertEqual(live.writes, [False, True, False, True, True])
            self.assertEqual(live.scans, 2)
            text = (live.output / 'result.json').read_text()
            self.assertEqual(json.loads(text), result)
            for private in (ADDRESS, CACHED, FRESH, 'PRIVATE-ALIAS', 'PRIVATE-NETWORK-UUID'):
                self.assertNotIn(private, text)

    def test_failures_and_signal_restore_even_uncertain_first_write(self):
        for failure in ('write', 'scan', 'signal', 'stop', 'later-connected', 'no-peer'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                live = Fake(Path(directory) / 'run')
                live.failure = failure
                result = power.exercise(live)
                self.assertFalse(result['complete'])
                self.assertIs(live.writes[-1], True)
                self.assertIs(live.data[power.ADAPTER][power.INTERFACE]['Powered'], True)
                if failure == 'stop': self.assertIn('cleanup_error', result)
                if failure == 'no-peer': self.assertTrue(result['fixture_inconclusive'])
                if failure == 'later-connected': self.assertEqual(live.scans, 1)

    def test_cached_startup_events_are_excluded_but_live_rssi_is_fresh(self):
        client = power.Discovery.__new__(power.Discovery)
        client.cached, client.new_peers, client.rssi_peers = {CACHED}, set(), set()
        client.new_count = client.rssi_count = 0
        client.started = client.stopped = False
        client.line('[NEW] Device ' + FRESH + ' PRIVATE-NAME')
        client.line('[CHG] Device ' + CACHED + ' RSSI: -40')
        self.assertEqual(client.new_count + client.rssi_count, 0)
        client.line('Discovery started')
        client.line('\x1b[0;92m[NEW]\x1b[0m Device ' + CACHED + ' PRIVATE-NAME')
        client.line('[NEW] Device ' + FRESH + ' PRIVATE-NAME')
        client.line('[CHG] Device ' + CACHED + ' RSSI: 0xffffffbc (-68)')
        self.assertEqual((client.new_count, client.rssi_count), (1, 1))
        client.line('Discovery stopped')
        client.line('[CHG] Device ' + FRESH + ' RSSI: -42')
        self.assertEqual(client.rssi_count, 1)

    def test_start_requires_ack_and_live_property_and_same_client_commands(self):
        client = power.Discovery.__new__(power.Discovery)
        client.process = Mock()
        client.process.poll.return_value = None
        client.process.stdin = io.BytesIO()
        client.started, client.stopped = False, False
        client.live = Mock()
        client.live.discovering.return_value = False
        client.pump = Mock(side_effect=lambda *a: setattr(client, 'started', True))
        with patch.object(power.time, 'monotonic', side_effect=[0, 0, 6]):
            with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                client.wait()
        client.live.discovering.return_value = True
        client.wait()
        client.send('scan on')
        client.send('scan off')
        self.assertEqual(client.process.stdin.getvalue(), b'scan on\nscan off\n')

    def test_busctl_variant_schema(self):
        reply = {'type': 'a{oa{sa{sv}}}', 'data': [{power.ADAPTER: {power.INTERFACE: {
                 'Powered': {'type': 'b', 'data': True}, 'Address': {'type': 's', 'data': ADDRESS}}}}]}
        self.assertIs(power.unpack(reply)[0][power.ADAPTER][power.INTERFACE]['Powered'], True)


if __name__ == '__main__':
    unittest.main()
