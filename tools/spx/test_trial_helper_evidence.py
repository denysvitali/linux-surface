#!/usr/bin/env python3
"""Offline fake tests for current-boot helper admission and thermal policy."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


thermal = module('thermal')
sleep = module('systemd_sleep')


class HelperEvidenceTests(unittest.TestCase):
    def test_completed_queued_reopen_admits_parked_suspend_only_same_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'audio-started-boots').mkdir()
            (root / 'audio-started-boots/boot.json').write_text('{}')
            (root / 'audio').mkdir()
            status = root / 'status'; status.write_text('closed')
            ops = sleep.ParkedAudio(root, 'boot', 'user')
            ops.audio = SimpleNamespace(assert_desktop_paused=Mock(), read_text=lambda p: p.read_text())
            fake_proc = SimpleNamespace(glob=lambda pattern: [status])
            actual_path = Path
            def paths(value): return fake_proc if value == '/proc/asound' else actual_path(value)
            for change, allowed in [({}, True), ({'boot_id':'old'},False),
                                    ({'success':False},False), ({'parked':False},False),
                                    ({'cleanup_errors':['park failed']},False)]:
                evidence = dict(boot_id='boot', success=True, parked=True, **{})
                evidence.update(change)
                (root / 'audio/reopen-result.json').write_text(json.dumps(evidence))
                with patch.object(sleep, 'Path', side_effect=paths):
                    if allowed: self.assertTrue(ops.idle())
                    else:
                        with self.assertRaises(AssertionError): ops.idle()
            (root / 'audio-request.json').write_text('{}')
            with patch.object(sleep, 'Path', side_effect=paths), self.assertRaises(AssertionError): ops.idle()

    def test_50c_admission_requires_natural_start_below_45c(self):
        # Reuse the existing entirely synthetic sysfs/procfs gate fixture.
        fixture_module = module('test_thermal')
        fixture = fixture_module.Thermal()
        gate_module = fixture_module.thermal
        for temperature, allowed in [(44999, True), (45000,False), (49000,False)]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                live, mapped = fixture.fake_live(root, actual_trip=50000, expected_trip=50000)
                for zone in live.zones[:2]: (zone / 'temp').write_text(str(temperature))
                with patch.object(gate_module, 'Path', side_effect=mapped), \
                     patch.object(gate_module.os, 'geteuid', return_value=0), \
                     patch.object(gate_module.os, 'uname', return_value=SimpleNamespace(release='test-kernel')):
                    if allowed: live.gate()
                    else:
                        with self.assertRaises(AssertionError): live.gate()
                self.assertEqual(live.ceiling, 75000)

    def test_50c_combined_stops_on_response_and_requires_real_overlap(self):
        for overlap in (False, True):
            with self.subTest(overlap=overlap), tempfile.TemporaryDirectory() as directory:
                live = thermal.CombinedLive.__new__(thermal.CombinedLive)
                live.output = Path(directory)
                live.passive_trip, live.return_deadline = 50000, float('inf')
                live.clusters = {'0':dict(trip=50000), '1':dict(trip=50000)}
                base = {key:dict(temperature=44000,state=0,limit=2000) for key in ('0','1')}
                samples = []
                if overlap:
                    samples.append(dict(phase='load',seconds=0,clusters=base,
                        workload=dict(load_seconds=0,cpu_ticks={str(i):1 for i in range(8)},
                                      gpu_clients={'42':dict(nanoseconds=1,cycles=1)})))
                live.result = dict(complete=False,samples=samples,before=dict(clusters=base))
                live.workers = [SimpleNamespace(poll=lambda: None) for _ in range(8)]
                live.cpu_stress_ng = Path('/fake/stress-ng')
                live.gpu_directory = None
                live.gpu_xml = live.output / 'fake.xml'; live.gpu_xml.write_text('</glmark2>')
                live.gate, live.start_load = Mock(), Mock()
                live.ac = lambda: True
                live.save = Mock()
                live.workload = lambda: dict(cpu_ticks={str(i):2 for i in range(8)},
                                             gpu_clients={'42':dict(nanoseconds=2,cycles=2)})
                def sample(phase):
                    record = dict(phase=phase,seconds=1,maximum=50001,
                        clusters={key:dict(temperature=50001,state=1,limit=1800) for key in ('0','1')})
                    live.result['samples'].append(record)
                    return record
                live.sample = Mock(side_effect=sample)
                def stop():
                    live.result.update(workers_stopped=True,gpu_stopped=True,
                                       gpu_group_stopped=True,native_arithmetic_passed=True)
                live.stop = Mock(side_effect=stop)
                def recover():
                    live.result['samples'].append(dict(phase='recovery',seconds=2,clusters=base))
                    live.result['recovered'] = True
                    return True
                live.recover = Mock(side_effect=recover)
                with patch.object(thermal.time,'monotonic',return_value=0), \
                     patch.object(thermal.time,'sleep') as delay, \
                     patch.object(thermal,'gpu_rows',return_value=[]), \
                     patch.object(thermal.subprocess,'run'):
                    result = live.exercise()
                self.assertEqual(result['stop_reason'],'both clusters responded')
                live.sample.assert_called_once_with('load')
                delay.assert_not_called()
                self.assertTrue(result['automatic_cpu_response_proven'])
                self.assertEqual(result['complete'],overlap)
                live.recover.assert_called_once()

    def test_50c_real_response_and_hysteresis_recovery(self):
        before = dict(clusters={'0':dict(limit=2000)})
        samples = [dict(phase=phase, seconds=second, clusters={'0':dict(temperature=temp, state=state, limit=limit)})
                   for phase, second, temp, state, limit in [('load',1,50001,0,2000),
                       ('load',2,49500,1,1800),('recovery',3,45000,0,2000),
                       ('recovery',4,44999,0,2000)]]
        evidence = thermal.response_evidence(samples,before,0,50000)
        self.assertTrue(evidence['complete'])
        self.assertEqual(evidence['recovery']['seconds'],4)
        self.assertFalse(thermal.response_evidence(samples[:-1],before,0,50000)['complete'])


if __name__ == '__main__': unittest.main()
