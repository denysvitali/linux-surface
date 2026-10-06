#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Effect-order, eligibility, repeat refusal and owned-client cleanup tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).parent))
import recovery
import lifecycle
import crash_test
import supervise

LOG = 'channel remove users=0 pending=0\nSDSP heap restored to HLOS owners=0x8; final context drained\n'
SHARED = 'SDSP heap region shared owners=0x28\n'


class Fake:
    def __init__(self, log=LOG, repeated=False):
        self.log, self.repeated, self.effects = log, repeated, []
        self.record = {}
    def gate(self):
        return dict(host_pid=10, proxy_pid=20)
    def reserve(self):
        self.effects.append('reserve')
        if self.repeated:
            raise FileExistsError('once-per-boot marker already exists')
    def save(self, record):
        self.record = dict(record)
    def cursor(self):
        return 'cursor'
    def stop_services(self):
        self.effects.append('stop-services')
    def stop_slpi(self):
        self.effects.append('stop-slpi')
    def kernel_since(self, cursor, name):
        self.effects.append('read-' + name)
        return self.log if name.startswith('teardown') else SHARED
    def start_slpi(self):
        assert lifecycle.teardown_proven(self.log)
        self.effects.append('start-slpi')
    def start_services(self):
        self.effects.append('start-services')
    def backend(self):
        return dict(host_pid=11)
    def proxy_pid(self):
        return 21


class Recovery(unittest.TestCase):
    def test_missing_proof_never_restarts_and_keeps_stopped(self):
        for log in ('', 'channel remove users=0 pending=1\n' + LOG.split('\n')[1],
                    'SDSP heap restored to HLOS owners=0x8; final context drained\n'):
            ops = Fake(log)
            result = recovery.recover(ops)
            self.assertFalse(result['complete'])
            self.assertNotIn('start-slpi', ops.effects)
            self.assertTrue(result['failure_backend_stopped'])
    def test_positive_proof_before_restart_and_new_host_proxy(self):
        ops = Fake()
        self.assertTrue(recovery.recover(ops)['complete'])
        self.assertLess(ops.effects.index('reserve'), ops.effects.index('stop-services'))
        self.assertLess(ops.effects.index('read-teardown-kernel.log'), ops.effects.index('start-slpi'))
    def test_repeated_attempt_no_hardware_effect(self):
        ops = Fake(repeated=True)
        self.assertFalse(recovery.recover(ops)['complete'])
        self.assertEqual(ops.effects, ['reserve'])
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'once'
            recovery.claim_once(marker, {'boot_id':'boot'})
            with self.assertRaises(FileExistsError):
                recovery.claim_once(marker, {'boot_id':'boot'})
    def test_identity_and_boot_eligibility(self):
        good = dict(ready=True, eligible=True, unexpected_exit=True, boot_id='boot', attempt='attempt', release='release', host_pid=42, host_start_ticks=50)
        self.assertTrue(recovery.eligible(good, 'boot', 'attempt', 'release'))
        for key, bad in [('ready',False),('unexpected_exit',False),('eligible',False),('boot_id','old'),('host_start_ticks',0),('host_pid',1)]:
            self.assertFalse(recovery.eligible(dict(good, **{key:bad}), 'boot', 'attempt', 'release'))
    def test_failed_new_host_cleanup(self):
        ops = Fake(); ops.backend = lambda: dict(host_pid=10)
        result = recovery.recover(ops)
        self.assertFalse(result['complete'])
        self.assertTrue(result['failure_backend_stopped'])
    def test_native_delivery_rejects_metadata_nan_and_insufficient_updates(self):
        accel = 'Has accelerometer (orientation: bottom-up, tilt: tilted-up)'
        self.assertFalse(crash_test.desktop_proven(accel, 'Has compass'))
        self.assertFalse(crash_test.desktop_proven(accel, 'Compass heading changed: 7\n'))
        self.assertFalse(crash_test.desktop_proven(accel, 'Compass heading changed: nan\n' * 3))
        self.assertTrue(crash_test.desktop_proven(accel, 'Compass heading changed: 7.3\n' * 3))
    def test_owned_client_cleanup_on_validation_failure(self):
        ops = Mock(); ops.gate.return_value={}; ops.cursor.return_value='cursor'
        client = Mock(); client.stop.return_value=True
        ops.clients.return_value=[client]
        ops.require_delivery.side_effect=RuntimeError('no delivery')
        self.assertFalse(crash_test.exercise(ops)['complete'])
        client.stop.assert_called_once()
        ops.kill_host.assert_not_called()
    def test_no_observer_uses_retained_owned_proxy_identity(self):
        live = recovery.Live.__new__(recovery.Live)
        live.record = dict(ready=True, eligible=True, unexpected_exit=True, boot_id='boot', attempt='a',
                           release='r', host_pid=42, host_start_ticks=7, provider_pid=41)
        live.boot_id, live.attempt, live.release, live.owner, live.private = 'boot', 'a', 'r', 'sensor-crash-a', True
        live.checked = Mock(side_effect=['failed', '55'])
        prepared = dict(sensors_crash_recovery=True, sensors_private_ssc=True, release='r', attempt='a')
        def fake_path(path):
            name=str(path)
            mock = Mock(); mock.__truediv__ = Mock(return_value=mock); mock.read_text.return_value=('spx_sensors_recovery=1' if name == '/proc/cmdline' else json.dumps(prepared)); mock.exists.return_value=False
            return mock
        base = Mock(); base.__truediv__ = Mock(return_value=base); base.read_text.return_value=json.dumps(prepared)
        with patch.object(recovery, 'BASE', base), patch.object(recovery, 'Path', side_effect=fake_path), patch.object(recovery, 'RUNTIME', Path('/nonexistent-runtime')), \
             patch.object(recovery, 'timer_budget'), patch.object(lifecycle.Live, 'gate', return_value={}) as gate:
            live.gate()
        self.assertEqual(gate.call_args.kwargs['before']['proxy_pid'],55)
        self.assertTrue(gate.call_args.kwargs['allow_native'])

    def test_stale_observer_never_hands_off(self):
        record=dict(host_pid=10,host_start_ticks=11)
        self.assertIsNone(recovery.observer_proxy(None,record,'b','a','owner'))
        with self.assertRaises(lifecycle.Refused):
            recovery.observer_proxy(dict(boot_id='old',proxy_pid=20),record,'b','a','owner')

    def test_unrelated_secure_owner_rejected_by_live_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'proc/99/fd').mkdir(parents=True)
            (root/'proc/99/cmdline').write_bytes(b'foreign-client\0')
            (root/'proc/99/fd/3').symlink_to('/dev/fastrpc-sdsp-secure')
            (root/'proc/cmdline').write_text('spx_attempt=a spx_boot=mainline-functional spx_sensors=1')
            (root/'proc/iomem').write_text('FastRPC SDSP DMA ownership')
            remote=root/'sys/class/remoteproc/remoteproc0';remote.mkdir(parents=True)
            for name,value in [('name','slpi'),('firmware','qcom/microsoft/spx/qcslpi8180.mbn'),('state','running')]:
                (remote/name).write_text(value)
            def mapped(path):
                return root/str(path).lstrip('/')
            live=lifecycle.Live.__new__(lifecycle.Live)
            live.attempt,live.release,live.output='a','r',root
            live.checked=Mock(return_value=SHARED)
            with patch.object(lifecycle,'Path',side_effect=mapped), patch.object(lifecycle.os,'geteuid',return_value=0), \
                 patch.object(lifecycle.os,'uname',return_value=SimpleNamespace(release='r')):
                with self.assertRaisesRegex(lifecycle.Refused,'external secure FastRPC client PID 99'):
                    live.gate(before=dict(host_pid=42),allow_native=True)
            self.assertEqual(live.checked.call_count,1)

    def test_cleanup_attempts_all_owned_clients_after_one_error(self):
        first,second=Mock(),Mock()
        first.stop.side_effect=ProcessLookupError('gone')
        second.stop.return_value=True
        errors=[]
        self.assertFalse(crash_test.stop_clients([first,second],errors))
        second.stop.assert_called_once()
        self.assertEqual(len(errors),1)

    def test_intentional_stop_witness_clears_eligibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            witness = supervise.Witness.__new__(supervise.Witness)
            witness.enabled=True; witness.directory=Path(tmp); witness.record=None
            marker=witness.directory/'crash.json'; marker.write_text('{}')
            witness('intentional-stop', Mock())
            self.assertFalse(marker.exists())
    def test_initial_failure_witness_never_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            witness = supervise.Witness.__new__(supervise.Witness)
            witness.enabled=True; witness.directory=Path(tmp); witness.record=None
            witness('crash', Mock())
            self.assertFalse((witness.directory/'crash.json').exists())


if __name__ == '__main__':
    unittest.main()
