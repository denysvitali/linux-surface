#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline checks for retained DTB staging and thermal workload cleanup."""
import importlib.util
from pathlib import Path
import subprocess
import copy
import os
import pwd
import shutil
import signal
import xml.etree.ElementTree as ET
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


class CombinedThermal(unittest.TestCase):
    def xml(self, renderer='FD680', fps='12', status='Success'):
        root = ET.Element('glmark2')
        info = ET.SubElement(root, 'info')
        ET.SubElement(info, 'gl_renderer').text = renderer
        ET.SubElement(info, 'gl_version').text = 'OpenGL ES 3.2 Mesa'
        row = ET.SubElement(root, 'benchmark')
        for key, value in dict(name='[shading] duration=100:shading=phong', status=status,
                               fps=fps, frame_time='83.333').items():
            ET.SubElement(row, key).text = value
        return ET.tostring(root, encoding='unicode')

    def test_completed_gpu_rows_survive_bounded_stop_but_reject_false_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'results.xml'
            # Real fixture flushes each row; planned TERM leaves a partial tail.
            path.write_text(self.xml().replace('</glmark2>', '<benchmark><name>[bump]'))
            self.assertEqual(len(thermal.gpu_rows(path)), 1)
            for bad in (self.xml(renderer='llvmpipe'), self.xml(fps='0'),
                        self.xml(fps='NaN'), self.xml(status='Unsupported'),
                        self.xml().replace('shading=phong', 'shading=gouraud')):
                path.write_text(bad)
                with self.assertRaises(AssertionError):
                    thermal.gpu_rows(path)
            path.write_text('<glmark2><info/><benchmark>')
            self.assertEqual(thermal.gpu_rows(path), [])

    def samples(self):
        return [dict(phase='load', workload=dict(load_seconds=second,
                cpu_ticks={str(pid): second * 10 for pid in range(8)},
                gpu_clients={'42': dict(nanoseconds=second * 10000, cycles=second * 100)}))
                for second in range(1, 300)]

    def test_coverage_requires_cpu_and_gpu_progress_through_final_window(self):
        samples = self.samples()
        self.assertTrue(set(range(2, 30)) <= set(thermal.overlap_coverage(samples)))
        stalled = copy.deepcopy(samples)
        for sample in stalled[199:]:
            sample['workload']['gpu_clients']['42'] = dict(nanoseconds=1990000, cycles=19900)
        self.assertNotIn(29, thermal.overlap_coverage(stalled))
        missing_cpu = copy.deepcopy(samples)
        for sample in missing_cpu:
            sample['workload']['cpu_ticks']['3'] = 0
        self.assertEqual(thermal.overlap_coverage(missing_cpu), [])
        # A new DRM context can reset its counters; never compare different clients.
        reset = copy.deepcopy(samples)
        for index, sample in enumerate(reset):
            sample['workload']['gpu_clients'] = {str(index): dict(nanoseconds=index, cycles=index)}
        self.assertEqual(thermal.overlap_coverage(reset), [])
        self.assertFalse(thermal.overlap_proven(samples[:1]))

    def test_failure_after_launch_stops_real_cpu_and_gpu_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            live = thermal.CombinedLive.__new__(thermal.CombinedLive)
            live.output = Path(directory)
            live.result = dict(complete=False, samples=[], before={'clusters': {}})
            live.workers = []
            live.gpu = None
            live.gpu_log = None
            live.gpu_directory = None
            live.load_stopped = False
            live.return_deadline = float('inf')
            live.gate = Mock()
            live.ac = Mock(return_value=True)
            live.sample = Mock(side_effect=RuntimeError('temperature read failed'))
            def start():
                live.workers = [subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(60)'])
                                for unused in range(8)]
                live.gpu = subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(60)'],
                                            start_new_session=True)
            live.start_load = start
            live.recover = Mock(return_value=False)
            with patch.object(thermal.subprocess, 'run'):
                result = live.exercise()
            self.assertFalse(result['complete'])
            self.assertEqual(result['error'], 'temperature read failed')
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['gpu_stopped'])
            self.assertTrue(result['gpu_group_stopped'])
            self.assertTrue(all(p.poll() is not None for p in live.workers))
            live.recover.assert_called_once()
            # A repeated finally cleanup must not signal a possibly reused PGID.
            with patch.object(thermal.os, 'killpg') as killpg:
                live.stop()
                killpg.assert_not_called()

    @unittest.skipUnless(os.geteuid() == 0, 'actual privilege drop requires root')
    def test_uid1000_gpu_output_works_with_private_root_result_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            live = thermal.CombinedLive.__new__(thermal.CombinedLive)
            live.output = Path(directory) / 'private-results'
            live.output.mkdir(mode=0o700)
            live.user = pwd.getpwuid(1000)
            live.credentials = dict(user=1000, group=live.user.pw_gid,
                extra_groups=os.getgrouplist(live.user.pw_name, live.user.pw_gid))
            live.gpu_directory = None
            try:
                live.prepare_gpu_output()
                self.assertEqual(live.gpu_directory.stat().st_uid, 1000)
                self.assertEqual(live.gpu_directory.stat().st_mode & 0o777, 0o700)
                self.assertEqual(live.output.stat().st_mode & 0o777, 0o700)
                subprocess.run(['/usr/bin/python3', '-c',
                    'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("GPU result")',
                    str(live.gpu_xml)], check=True, **live.credentials)
                self.assertEqual(live.gpu_xml.read_text(), 'GPU result')
                self.assertNotEqual(live.gpu_directory.parent, live.output)
            finally:
                if live.gpu_directory:
                    shutil.rmtree(live.gpu_directory)

    def test_failed_preflight_launches_no_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            live = thermal.CombinedLive.__new__(thermal.CombinedLive)
            live.output = Path(directory)
            live.result = dict(complete=False, samples=[])
            live.workers, live.gpu, live.gpu_log, live.gpu_directory = [], None, None, None
            live.load_stopped = False
            live.gate = Mock(side_effect=AssertionError('480s reserve required'))
            live.start_load = Mock()
            with patch.object(thermal.subprocess, 'run'):
                result = live.exercise()
            live.start_load.assert_not_called()
            self.assertFalse(result['complete'])
            self.assertIn('reserve', result['error'])

    def test_fault_window_recognizes_new_failure_not_ordinary_probe_text(self):
        self.assertFalse(thermal.FAULTS.findall('venus: probe failed -110'))
        self.assertFalse(thermal.FAULTS.findall('iommu: Default domain type: Translated'))
        for message in ('msm: GPU hangcheck timeout', 'arm-smmu: Unhandled context fault',
                        'INFO: task mkinitcpio blocked for more than 122 seconds',
                        'qcom_q6v5_pas 8300000.remoteproc: watchdog received',
                        'BUG: bad page state', 'Oops: 96000004'):
            self.assertTrue(thermal.FAULTS.findall(message), message)


class NativeFP(unittest.TestCase):
    SUCCESS = ('stress-ng: info: [42] passed: 1: fp (1)\n'
               'stress-ng: info: [42] failed: 0\n'
               'stress-ng: info: [42] skipped: 0\n'
               'stress-ng: info: [42] successful run completed in 300s\n')

    def test_native_summary_rejects_nonzero_skip_and_arithmetic_failure(self):
        self.assertTrue(thermal.native_fp_passed(0, self.SUCCESS))
        for rc, text in ((1, self.SUCCESS), (-9, self.SUCCESS), (0, ''),
                (0, self.SUCCESS.replace('passed: 1: fp (1)', 'passed: 0')),
                (0, self.SUCCESS.replace('failed: 0', 'failed: 1: fp (1)')),
                (0, self.SUCCESS.replace('skipped: 0', 'skipped: 1: fp (1)')),
                (0, self.SUCCESS + 'stress-ng: fail: [43] fp: doublemul verification failed\n')):
            self.assertFalse(thermal.native_fp_passed(rc, text))

    def test_proc_group_evidence_includes_descendant_identity_and_affinity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, group, name, ticks in ((42, 42, 'stress-ng', 900),
                                           (43, 42, 'stress-ng-fp', 12),
                                           (44, 44, 'unrelated', 1000)):
                member = root / str(pid)
                member.mkdir()
                fields = ['0'] * 20
                fields[0], fields[2], fields[11], fields[12], fields[19] = 'R', str(group), str(ticks), '1', '123'
                (member / 'stat').write_text(f'{pid} ({name}) ' + ' '.join(fields))
                (member / 'status').write_text('Cpus_allowed_list:\t3\n')
            members = thermal.native_group_members(42, root)
            self.assertEqual(set(members), {'42', '43'})
            self.assertEqual(members['43'], dict(name='stress-ng-fp', state='R', ticks=13,
                                                start_ticks=123, affinity='3'))

    def test_only_actual_stressor_ticks_count_and_affinity_restart_are_rejected(self):
        live = thermal.CombinedLive.__new__(thermal.CombinedLive)
        live.cpu_stress_ng = Path('/private/stress-ng')
        worker = Mock(pid=42)
        live.workers = [worker]
        live.gpu = Mock(pid=99)
        live.gpu.poll.return_value = None
        live.native_workers = {42: dict(cpu=3, child_identity=None)}
        members = {'42': dict(name='stress-ng', state='S', ticks=900, start_ticks=10, affinity='3'),
                   '43': dict(name='stress-ng-fp', state='R', ticks=13, start_ticks=11, affinity='3')}
        with patch.object(thermal, 'native_group_members', return_value=members), \
             patch.object(Path, 'iterdir', return_value=iter([])):
            result = live.workload()
        self.assertEqual(result['cpu_ticks'], {'42': 13})
        self.assertEqual(result['cpu_groups']['42']['stressor_pids'], ['43'])
        for changed in ({'42': members['42']},
                        dict(members, **{'43': dict(members['43'], affinity='3-4')}),
                        dict(members, **{'43': dict(members['43'], start_ticks=99)})):
            with patch.object(thermal, 'native_group_members', return_value=changed):
                with self.assertRaises(AssertionError):
                    live.workload()

    def test_native_cleanup_stops_supervisor_and_its_real_child_after_partial_launch(self):
        # Sleeping processes exercise group cleanup without stressing hardware.
        script = ('import os,signal,time\n'
                  'pid=os.fork()\n'
                  'if pid==0:\n signal.signal(signal.SIGTERM, lambda *a: os._exit(0)); time.sleep(60)\n'
                  'else:\n'
                  ' def stop(*a):\n  os.waitpid(pid,0); raise SystemExit(0)\n'
                  ' signal.signal(signal.SIGTERM,stop); print(pid,flush=True); time.sleep(60)\n')
        with tempfile.TemporaryDirectory() as directory:
            live = thermal.CombinedLive.__new__(thermal.CombinedLive)
            live.output = Path(directory)
            live.result = dict(complete=False)
            live.cpu_stress_ng = Path('/private/stress-ng')
            live.workers, live.native_workers = [], {}
            live.gpu, live.gpu_log, live.load_stopped = None, None, False
            child_pids = []
            try:
                for cpu in range(2):
                    log = (live.output / f'cpu{cpu}-fp.log').open('wb')
                    worker = subprocess.Popen(['/usr/bin/python3', '-c', script],
                        start_new_session=True, stdout=subprocess.PIPE, text=True)
                    live.workers.append(worker)
                    live.native_workers[worker.pid] = dict(cpu=cpu, command=[], log=log, child_identity=None)
                    child_pids.append(int(worker.stdout.readline()))
                live.stop()
                self.assertTrue(live.result['workers_stopped'])
                self.assertFalse(live.result['native_arithmetic_passed'])
                self.assertTrue(all(r['group_stopped'] for r in live.result['native_cpu_results'].values()))
                self.assertTrue(all(not Path(f'/proc/{pid}').exists() for pid in child_pids))
                with patch.object(thermal.os, 'killpg') as killpg:
                    live.stop()
                    killpg.assert_not_called()
            finally:
                for worker in live.workers:
                    if worker.poll() is None:
                        os.killpg(worker.pid, signal.SIGKILL)
                        worker.wait(timeout=3)
                    worker.stdout.close()

    def test_forced_kill_rejects_even_a_successful_looking_log(self):
        with tempfile.TemporaryDirectory() as directory:
            live = thermal.CombinedLive.__new__(thermal.CombinedLive)
            live.output = Path(directory)
            live.result = dict(complete=False)
            live.cpu_stress_ng = Path('/private/stress-ng')
            log = (live.output / 'cpu0-fp.log').open('w')
            log.write(self.SUCCESS)
            log.flush()
            worker = Mock(pid=42, returncode=0)
            worker.poll.return_value = 0
            worker.wait.side_effect = [subprocess.TimeoutExpired('native worker', 3), 0]
            live.workers = [worker]
            live.native_workers = {42: dict(cpu=0, command=[], log=log, child_identity=None)}
            live.gpu, live.gpu_log, live.load_stopped = None, None, False
            with patch.object(thermal.os, 'killpg') as killpg, \
                 patch.object(thermal, 'native_group_members', side_effect=[{'43': {}}, {}]):
                live.stop()
            killpg.assert_any_call(42, signal.SIGTERM)
            killpg.assert_any_call(42, signal.SIGKILL)
            result = live.result['native_cpu_results']['0']
            self.assertTrue(result['forced_kill'])
            self.assertTrue(result['group_stopped'])
            self.assertFalse(result['arithmetic_passed'])


if __name__ == '__main__':
    unittest.main()
