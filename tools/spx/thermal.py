#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""SPX Linux CPU passive policy staging and bounded real-temperature test."""
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import time

PASSIVE = 75000
HYSTERESIS = 5000
CEILING = 80000


def stage_policy(dtb):
    """Apply only the board policy to the retained diagnostic DTB."""
    def get(node, prop, kind='u'):
        return subprocess.check_output(['fdtget', '-t', kind, str(dtb), node, prop], text=True).strip()

    def put(node, prop, values, kind='i'):
        subprocess.run(['fdtput', '-p', '-t', kind, str(dtb), node, prop, *map(str, values)], check=True)

    blob = ctypes.create_string_buffer(dtb.read_bytes())
    lib = ctypes.CDLL('libfdt.so.1')
    lib.fdt_find_max_phandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    lib.fdt_find_max_phandle.restype = ctypes.c_int
    maximum = ctypes.c_uint32()
    assert lib.fdt_find_max_phandle(blob, ctypes.byref(maximum)) == 0
    assert maximum.value < 0xfffffffd
    for index, cpu in enumerate((0, 4)):
        zone = f'/thermal-zones/cluster{index}-thermal'
        cpu_node = '/cpus/cpu@' + ('0' if cpu == 0 else '400')
        assert get(zone + '/trips/cluster-crit', 'temperature') == '110000'
        assert get(zone, 'polling-delay-passive') == '250'
        assert int(get(zone, 'thermal-sensors').split()[-1]) == index + 5
        assert get(cpu_node, '#cooling-cells') == '2'
        assert int(get(cpu_node, 'qcom,freq-domain').split()[-1]) == index
        cpu_phandle = int(get(cpu_node, 'phandle'))
        trip = zone + '/trips/cluster-passive'
        phandle = maximum.value + index + 1
        put(trip, 'temperature', [PASSIVE])
        put(trip, 'hysteresis', [HYSTERESIS])
        put(trip, 'type', ['passive'], 's')
        put(trip, 'phandle', [phandle])
        put(zone + '/cooling-maps/map0', 'trip', [phandle])
        put(zone + '/cooling-maps/map0', 'cooling-device',
            [cpu_phandle, 0xffffffff, 0xffffffff])


def response_proven(samples, before, index):
    key = str(index)
    crossed = False
    for sample in samples:
        if sample['phase'] != 'load':
            continue
        cluster = sample['clusters'][key]
        crossed |= cluster['temperature'] >= PASSIVE
        if crossed and cluster['state'] > 0 and cluster['limit'] < before['clusters'][key]['limit']:
            return True
    return False


class Live:
    def __init__(self, output, attempt, release):
        self.output, self.attempt, self.release = output, attempt, release
        output.mkdir(mode=0o700)
        self.workers = []
        self.clusters = {}
        self.zones = list(Path('/sys/class/thermal').glob('thermal_zone*'))
        self.mains = [p for p in Path('/sys/class/power_supply').glob('*')
                      if (p / 'type').read_text().strip() == 'Mains']
        self.started = time.monotonic()
        self.result = dict(complete=False, attempt=attempt, release=release,
                           boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                           policy='Linux75C passive/5C hysteresis; real temperatures only',
                           samples=[])

    def save(self):
        temporary = self.output / 'result.json.tmp'
        temporary.write_text(json.dumps(self.result, indent=2) + '\n')
        os.replace(temporary, self.output / 'result.json')

    def ac(self):
        return any((p / 'online').read_text().strip() == '1' for p in self.mains)

    def gate(self):
        words = Path('/proc/cmdline').read_text().split()
        assert os.geteuid() == 0 and os.uname().release == self.release
        assert 'spx_attempt=' + self.attempt in words and 'spx_boot=mainline-functional' in words
        assert self.ac(), 'AC is required; no battery workload'
        for index, cpu in enumerate((0, 4)):
            matches = [z for z in self.zones if (z / 'type').read_text().strip() == f'cluster{index}-thermal']
            assert len(matches) == 1
            zone = matches[0]
            assert (zone / 'policy').read_text().strip() == 'step_wise'
            assert (zone / 'mode').read_text().strip() == 'enabled'
            trips = [p for p in zone.glob('trip_point_*_type') if p.read_text().strip() == 'passive']
            assert len(trips) == 1, 'new passive CPU policy is not loaded; no workload permitted'
            prefix = str(trips[0])[:-4]
            assert int(Path(prefix + 'temp').read_text()) == PASSIVE
            assert int(Path(prefix + 'hyst').read_text()) == HYSTERESIS
            trip_index = int(re.search(r'trip_point_(\d+)_type$', str(trips[0]))[1])
            bindings = [p for p in zone.glob('cdev*') if re.fullmatch(r'cdev\d+', p.name)
                        and p.is_symlink() and (p / 'type').read_text().strip() == f'cpufreq-cpu{cpu}']
            assert len(bindings) == 1, 'passive CPU cooling binding missing'
            assert int((zone / (bindings[0].name + '_trip_point')).read_text()) == trip_index
            policy = Path(f'/sys/devices/system/cpu/cpufreq/policy{cpu}')
            assert (policy / 'scaling_driver').read_text().strip() == 'qcom-cpufreq-hw'
            cpus = [int(v) for v in (policy / 'related_cpus').read_text().split()]
            assert cpus == list(range(cpu, cpu + 4))
            self.clusters[str(index)] = dict(zone=zone, cooling=bindings[0], policy=policy, cpus=cpus)
        before = self.sample('baseline')
        assert before['maximum'] < PASSIVE - HYSTERESIS
        assert all(c['state'] == 0 for c in before['clusters'].values()), 'baseline must be naturally unthrottled'
        self.result['before'] = before
        self.save()

    def sample(self, phase):
        temperatures = {z.name + ':' + (z / 'type').read_text().strip(): int((z / 'temp').read_text())
                        for z in self.zones}
        assert all(-40000 <= value <= 125000 for value in temperatures.values()), 'implausible sensor reading'
        record = dict(seconds=round(time.monotonic() - self.started, 3), phase=phase,
                      maximum=max(temperatures.values()), temperatures=temperatures, clusters={})
        for index, c in self.clusters.items():
            record['clusters'][index] = dict(temperature=int((c['zone'] / 'temp').read_text()),
                                            state=int((c['cooling'] / 'cur_state').read_text()),
                                            limit=int((c['policy'] / 'scaling_max_freq').read_text()),
                                            frequency=int((c['policy'] / 'scaling_cur_freq').read_text()))
        self.result['samples'].append(record)
        self.save()
        return record

    def stop(self):
        for p in self.workers:
            if p.poll() is None:
                p.terminate()
        for p in self.workers:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        self.result['workers_stopped'] = all(p.poll() is not None for p in self.workers)

    def exercise(self):
        try:
            self.gate()
            for c in self.clusters.values():
                for cpu in c['cpus']:
                    code = 'import os; os.sched_setaffinity(0, {' + str(cpu) + '}); x=1\nwhile True: x=(x*1664525+1013904223)&0xffffffff'
                    self.workers.append(subprocess.Popen(['/usr/bin/python3', '-c', code],
                                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            self.result['worker_pids'] = [p.pid for p in self.workers]
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                assert self.ac(), 'AC disconnected; stop workload'
                assert all(p.poll() is None for p in self.workers), 'CPU worker exited unexpectedly'
                sample = self.sample('load')
                if sample['maximum'] >= CEILING:
                    self.result['stop_reason'] = '80C ceiling'
                    break
                if all(response_proven(self.result['samples'], self.result['before'], i) for i in (0, 1)):
                    self.result['stop_reason'] = 'both clusters responded'
                    break
                time.sleep(1)
            else:
                self.result['stop_reason'] = '180s workload bound'
            self.stop()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                sample = self.sample('recovery')
                recovered = all(c['temperature'] < PASSIVE - HYSTERESIS and c['state'] == 0
                                and c['limit'] == self.result['before']['clusters'][i]['limit']
                                for i, c in sample['clusters'].items())
                if recovered:
                    break
                time.sleep(1)
            self.result['responses'] = {str(i): response_proven(self.result['samples'], self.result['before'], i) for i in (0, 1)}
            self.result['recovered'] = recovered
            self.result['complete'] = all(self.result['responses'].values()) and recovered
            self.result['limits'] = 'CPU passive policy only; GPU response, skin temperature and sustained combined envelope remain open.'
        except Exception as error:
            self.result['error'] = str(error)
        finally:
            self.stop()
            for name, args in [('kernel.log', ['-k']), ('journal.log', [])]:
                temporary = self.output / (name + '.tmp')
                try:
                    with temporary.open('wb') as stream:
                        subprocess.run(['journalctl', '-b', '--no-pager', '-o', 'short-monotonic', *args],
                                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=30)
                    os.replace(temporary, self.output / name)
                except Exception as error:
                    self.result['capture_error'] = str(error)
                    self.result['complete'] = False
            self.save()
        return self.result
