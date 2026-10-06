#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline checks for retained DTB staging and thermal workload cleanup."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('thermal', Path(__file__).with_name('thermal.py'))
thermal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thermal)


class Thermal(unittest.TestCase):
    def test_policy_preserves_existing_board_and_critical_properties(self):
        with tempfile.TemporaryDirectory() as directory:
            dtb = Path(directory) / 'board.dtb'
            dts = '''/dts-v1/; / {
                unrelated { phandle = <999>; value = <0xdeadbeef>; };
                cpus {
                    cpu@0 { phandle = <25>; #cooling-cells = <2>; qcom,freq-domain = <99 0>; };
                    cpu@400 { phandle = <29>; #cooling-cells = <2>; qcom,freq-domain = <99 1>; };
                };
                thermal-zones {
                    cluster0-thermal { polling-delay-passive = <250>; thermal-sensors = <77 5>;
                        trips { cluster-crit { temperature = <110000>; type = "critical"; }; }; };
                    cluster1-thermal { polling-delay-passive = <250>; thermal-sensors = <77 6>;
                        trips { cluster-crit { temperature = <110000>; type = "critical"; }; }; };
                };
            };'''
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(dtb), '-'],
                           input=dts, text=True, capture_output=True, check=True)
            thermal.stage_policy(dtb)
            def get(node, prop):
                return subprocess.check_output(['fdtget', '-t', 'u', str(dtb), node, prop], text=True).strip()
            self.assertEqual(get('/unrelated', 'value'), '3735928559')
            for index, cpu_phandle in enumerate((25, 29)):
                zone = f'/thermal-zones/cluster{index}-thermal'
                self.assertEqual(get(zone + '/trips/cluster-crit', 'temperature'), '110000')
                self.assertEqual(get(zone, 'thermal-sensors'), f'77 {index + 5}')
                self.assertEqual(get(zone + '/trips/cluster-passive', 'temperature'), '75000')
                self.assertEqual(get(zone + '/trips/cluster-passive', 'hysteresis'), '5000')
                self.assertEqual(get(zone + '/cooling-maps/map0', 'trip'), str(1000 + index))
                self.assertEqual(get(zone + '/cooling-maps/map0', 'cooling-device'), f'{cpu_phandle} 4294967295 4294967295')

    def test_response_requires_real_crossing_and_limit_change(self):
        before = {'clusters': {'0': {'limit': 1700000}}}
        def sample(temp, state, limit, phase='load'):
            return {'phase': phase, 'clusters': {'0': {'temperature': temp, 'state': state, 'limit': limit}}}
        self.assertFalse(thermal.response_proven([sample(40000, 13, 300000)], before, 0))
        self.assertFalse(thermal.response_proven([sample(76000, 0, 1700000)], before, 0))
        self.assertFalse(thermal.response_proven([sample(76000, 1, 1700000)], before, 0))
        self.assertFalse(thermal.response_proven([sample(76000, 1, 300000, 'recovery')], before, 0))
        self.assertTrue(thermal.response_proven([sample(76000, 1, 300000)], before, 0))
        self.assertTrue(thermal.response_proven([sample(76000, 0, 1700000), sample(74000, 1, 300000)], before, 0))
        self.assertFalse(thermal.response_proven([sample(74000, 1, 300000), sample(76000, 0, 1700000)], before, 0))

    def test_temperature_read_failure_stops_all_workers(self):
        class Worker:
            def __init__(self):
                self.exited = False
                self.pid = 42
            def poll(self):
                return -15 if self.exited else None
            def terminate(self):
                self.exited = True
            def wait(self, timeout):
                assert self.exited
                return -15
        with tempfile.TemporaryDirectory() as directory:
            live = thermal.Live.__new__(thermal.Live)
            live.output = Path(directory)
            live.workers = []
            live.clusters = {'0': {'cpus': [0]}, '1': {'cpus': [4]}}
            live.result = {'complete': False, 'samples': []}
            live.gate = Mock()
            live.ac = Mock(return_value=True)
            live.sample = Mock(side_effect=RuntimeError('temperature read failed'))
            with patch.object(thermal.subprocess, 'Popen', side_effect=lambda *a, **kw: Worker()), \
                 patch.object(thermal.subprocess, 'run'):
                result = live.exercise()
            self.assertFalse(result['complete'])
            self.assertEqual(result['error'], 'temperature read failed')
            self.assertTrue(result['workers_stopped'])
            self.assertEqual(len(live.workers), 2)
            self.assertTrue(all(worker.exited for worker in live.workers))


if __name__ == '__main__':
    unittest.main()
