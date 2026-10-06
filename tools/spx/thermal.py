#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""SPX Linux CPU passive policy staging and bounded real-temperature test."""
import ctypes
import json
import os
from pathlib import Path
import re
import pwd
import signal
import stat
import math
import tempfile
import shutil
import xml.etree.ElementTree as ET
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


GPU_SCENES = (
    'shading:shading=phong',
    'bump:bump-render=height',
    'desktop:windows=4:effect=blur:blur-radius=5:passes=1:separable=true',
)
RENDER_NODE = '/dev/dri/renderD128'
COMBINED_SECONDS = 300
RETURN_RESERVE = 480
FAULTS = re.compile(r'^.*(?:\bBUG:|\bOops:|Kernel panic|blocked for more than|'
                    r'(?:GPU|GMU|adreno|msm|IOMMU|arm-smmu).*'
                    r'\b(?:hangcheck|hung|fault|timeout|timed out|reset|watchdog|lockup)\b|'
                    r'remoteproc.*(?:crash|watchdog|timeout)).*$', re.I | re.M)


def gpu_rows(path):
    """Only completed XML rows are evidence; an interrupted row stays partial.

    The retained glmark2 flushes each field/row. A bounded TERM may leave the
    XML root and last row open, so parse only the completed prefix, preserving
    the original file untouched.
    """
    text = path.read_text()
    end = text.rfind('</benchmark>')
    if end < 0:
        return []
    root = ET.fromstring(text[:end + len('</benchmark>')] + '</glmark2>')
    assert root.tag == 'glmark2'
    assert root.findtext('info/gl_renderer') == 'FD680', 'GPU hardware renderer missing'
    assert 'OpenGL ES' in root.findtext('info/gl_version', '')
    rows = []
    for index, item in enumerate(root.findall('benchmark')):
        row = {n.tag: n.text for n in item}
        match = re.fullmatch(r'\[([^]]+)\] (.*)', row.get('name', ''))
        assert match, 'unrecognized GPU benchmark'
        scene = GPU_SCENES[index % len(GPU_SCENES)].split(':')
        expected = dict(p.split('=', 1) for p in scene[1:])
        expected['duration'] = '100'
        assert match[1] == scene[0] and dict(p.split('=', 1) for p in match[2].split(':')) == expected
        assert row.get('status') == 'Success', 'GPU scene failed or unsupported'
        for field in ('fps', 'frame_time'):
            value = float(row[field])
            assert math.isfinite(value) and value > 0, 'GPU frame evidence missing'
        rows.append(row)
    return rows


def overlap_proven(samples):
    """A common interval must contain progress on all CPU workers and GPU."""
    load = [s for s in samples if s['phase'] == 'load' and 'workload' in s]
    for first, last in zip(load, load[1:]):
        a, b = first['workload'], last['workload']
        if len(a['cpu_ticks']) != 8 or a['cpu_ticks'].keys() != b['cpu_ticks'].keys():
            continue
        if not all(b['cpu_ticks'][pid] > ticks for pid, ticks in a['cpu_ticks'].items()):
            continue
        for client, counters in a['gpu_clients'].items():
            after = b['gpu_clients'].get(client)
            if after and (after['nanoseconds'] > counters['nanoseconds'] or after['cycles'] > counters['cycles']):
                return True
    return False


def overlap_coverage(samples):
    """Require actual progress in every10s window after20s setup allowance."""
    load = [s for s in samples if s['phase'] == 'load' and 'workload' in s]
    bins = set()
    for first, last in zip(load, load[1:]):
        if last['workload']['load_seconds'] - first['workload']['load_seconds'] > 2.5:
            continue
        if overlap_proven([first, last]):
            bins.add(int(last['workload']['load_seconds'] // 10))
    return sorted(bins)


class CombinedLive(Live):
    """Opt-in AC workload; no frequency, thermal, display or battery writes."""
    def __init__(self, output, attempt, release, fixture):
        super().__init__(output, attempt, release)
        self.fixture = fixture.resolve()
        self.gpu = None
        self.gpu_log = None
        self.gpu_directory = None
        self.gpu_xml = None
        self.load_stopped = False
        self.result.update(scope='bounded AC CPU+GPU load and real CPU passive response',
                           combined_seconds=COMBINED_SECONDS,
                           gpu_automatic_response_proven=False,
                           full_thermal_acceptance=False,
                           limits='80C abort is below the existing85C GPU trip; full GPU automatic response, skin/enclosure and sustained envelope remain unverified.')

    def gate(self):
        cooling = [p for p in Path('/sys/class/thermal').glob('cooling_device*')
                   if (p / 'type').read_text().strip() == 'devfreq-2c00000.gpu']
        assert len(cooling) == 1, 'GPU cooling device missing'
        self.gpu_cooling = cooling[0]
        self.gpu_devfreq = Path('/sys/class/devfreq/2c00000.gpu')
        super().gate()
        assert self.result['before']['gpu']['state'] == 0, 'GPU baseline must be unthrottled'
        assert subprocess.check_output(['systemctl', 'is-active',
            'spx-trial-return@' + self.attempt + '.timer'], text=True, timeout=5).strip() == 'active'
        raw = subprocess.check_output(['busctl', 'get-property', 'org.freedesktop.systemd1',
            '/org/freedesktop/systemd1/unit/spx_2dtrial_2dreturn_40' + self.attempt + '_2etimer',
            'org.freedesktop.systemd1.Timer', 'NextElapseUSecMonotonic'], text=True, timeout=5).split()
        assert raw[0] == 't'
        self.return_deadline = int(raw[1]) / 1e6
        assert self.return_deadline - time.monotonic() >= RETURN_RESERVE, '480s automatic-return reserve required'
        assert stat.S_ISCHR(Path(RENDER_NODE).stat().st_mode)
        self.user = pwd.getpwuid(1000)
        groups = os.getgrouplist(self.user.pw_name, self.user.pw_gid)
        self.credentials = dict(user=1000, group=self.user.pw_gid, extra_groups=groups)
        self.binary = self.fixture / 'bin/glmark2-es2-gbm'
        assert self.binary.is_file() and (self.fixture / 'data').is_dir()
        # Actual UID1000 access, including ancestor traversal and any ACLs.
        subprocess.run(['/usr/bin/python3', '-c',
            'import os,sys; assert os.access(sys.argv[1], os.R_OK|os.X_OK); '
            'assert os.access(sys.argv[2], os.R_OK|os.X_OK); '
            'assert os.access(sys.argv[3], os.R_OK|os.W_OK)',
            str(self.binary), str(self.fixture / 'data'), RENDER_NODE],
            check=True, timeout=5, **self.credentials)
        self.prepare_gpu_output()
        self.result['fixture'] = str(self.fixture)
        self.save()

    def prepare_gpu_output(self):
        # Private root-owned result ancestors cannot be traversed by UID1000.
        # Keep GPU output in its own private temporary directory instead.
        self.gpu_directory = Path(tempfile.mkdtemp(prefix='spx-thermal-gpu-', dir='/var/tmp'))
        os.chown(self.gpu_directory, 1000, self.user.pw_gid)
        self.gpu_xml = self.gpu_directory / 'results.xml'
        subprocess.run(['/usr/bin/python3', '-c',
            'import pathlib,sys; p=pathlib.Path(sys.argv[1]); '
            'p.write_text("access preflight\\n"); p.unlink()',
            str(self.gpu_directory / 'access-check')],
            check=True, timeout=5, **self.credentials)

    def start_load(self):
        assert self.return_deadline - time.monotonic() >= RETURN_RESERVE, '480s reserve required at launch'
        journal = subprocess.check_output(['journalctl', '-b', '-k', '-n', '0',
            '--no-pager', '--show-cursor'], text=True, timeout=5)
        match = re.search(r'-- cursor: (\S+)', journal)
        assert match, 'kernel journal cursor required before load'
        self.result['kernel_cursor'] = match[1]
        for c in self.clusters.values():
            for cpu in c['cpus']:
                code = 'import os; os.sched_setaffinity(0, {' + str(cpu) + '}); x=1\nwhile True: x=(x*1664525+1013904223)&0xffffffff'
                self.workers.append(subprocess.Popen(['/usr/bin/python3', '-c', code],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert len(self.workers) == 8
        self.result['worker_pids'] = [p.pid for p in self.workers]
        command = [str(self.binary), '--off-screen', '--winsys-options=drm-device=' + RENDER_NODE,
            '--data-path', str(self.fixture / 'data'), '--size', '800x600', '--frame-end=finish',
            '--results=fps:cpu:shader', '--results-file', str(self.gpu_xml), '--run-forever']
        for scene in GPU_SCENES:
            command += ['--benchmark', scene + ':duration=100']
        self.result['gpu_command'] = command
        self.gpu_log = (self.output / 'gpu.log').open('xb')
        self.gpu = subprocess.Popen(command, stdin=subprocess.DEVNULL,
            stdout=self.gpu_log, stderr=subprocess.STDOUT, start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'XDG_RUNTIME_DIR': '/run/user/1000'},
            **self.credentials)
        self.result['gpu_pid'] = self.gpu.pid
        self.save()

    def sample(self, phase):
        record = super().sample(phase)
        record['gpu'] = dict(state=int((self.gpu_cooling / 'cur_state').read_text()),
                             maximum=int((self.gpu_devfreq / 'max_freq').read_text()),
                             minimum=int((self.gpu_devfreq / 'min_freq').read_text()),
                             frequency=int((self.gpu_devfreq / 'cur_freq').read_text()),
                             governor=(self.gpu_devfreq / 'governor').read_text().strip())
        assert record['gpu']['maximum'] > 0 and record['gpu']['minimum'] >= 0
        self.save()
        return record

    def workload(self):
        ticks = {}
        for worker in self.workers:
            fields = (Path('/proc') / str(worker.pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            ticks[str(worker.pid)] = int(fields[11]) + int(fields[12])
        assert self.gpu.poll() is None, 'GPU exited before the scheduled load stop'
        clients = {}
        nodes = set()
        for fd in (Path('/proc') / str(self.gpu.pid) / 'fd').iterdir():
            try:
                node = os.readlink(fd)
            except FileNotFoundError:
                continue
            if not node.startswith('/dev/dri/'):
                continue
            nodes.add(node)
            assert node == RENDER_NODE, 'GPU opened a display/modesetting DRM node'
            info = (fd.parent.parent / 'fdinfo' / fd.name).read_text()
            values = dict(line.split(':', 1) for line in info.splitlines() if ':' in line)
            assert values.get('drm-driver', '').strip() == 'msm'
            client = values['drm-client-id'].strip()
            clients[client] = dict(nanoseconds=int(values['drm-engine-gpu'].split()[0]),
                                   cycles=int(values['drm-cycles-gpu'].split()[0]))
        return dict(cpu_ticks=ticks, gpu_clients=clients, drm_nodes=sorted(nodes))

    def stop(self):
        if getattr(self, 'load_stopped', False):
            return
        # Signal every workload first, then use one common deadline for wait.
        gpu = getattr(self, 'gpu', None)
        if gpu:
            try:
                os.killpg(gpu.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for worker in self.workers:
            if worker.poll() is None:
                worker.terminate()
        deadline = time.monotonic() + 3
        processes = self.workers + ([gpu] if gpu else [])
        for process in processes:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        if gpu:
            try:
                os.killpg(gpu.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for worker in self.workers:
            if worker.poll() is None:
                worker.kill()
        deadline = time.monotonic() + 3
        for process in processes:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        self.result['workers_stopped'] = all(w.poll() is not None for w in self.workers)
        self.result['gpu_stopped'] = gpu is None or gpu.poll() is not None
        if gpu:
            self.result['gpu_returncode'] = gpu.returncode
            try:
                os.killpg(gpu.pid, 0)
            except ProcessLookupError:
                self.result['gpu_group_stopped'] = True
            else:
                self.result['gpu_group_stopped'] = False
        else:
            self.result['gpu_group_stopped'] = True
        if getattr(self, 'gpu_log', None):
            self.gpu_log.close()
        self.load_stopped = (self.result['workers_stopped'] and self.result['gpu_stopped']
                             and self.result['gpu_group_stopped'])

    def recover(self):
        recovered = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            assert self.ac(), 'AC disconnected during recovery'
            sample = self.sample('recovery')
            assert sample['maximum'] < CEILING, '80C ceiling during recovery'
            recovered = all(c['temperature'] < PASSIVE - HYSTERESIS and c['state'] == 0
                            and c['limit'] == self.result['before']['clusters'][i]['limit']
                            for i, c in sample['clusters'].items())
            gpu = sample['gpu']
            before = self.result['before']['gpu']
            recovered = recovered and gpu['state'] == 0 and all(
                gpu[key] == before[key] for key in ('maximum', 'minimum', 'governor'))
            if recovered:
                break
            time.sleep(1)
        self.result['recovered'] = recovered
        return recovered

    def exercise(self):
        try:
            self.gate()
            self.start_load()
            started = time.monotonic()
            deadline = started + COMBINED_SECONDS
            while time.monotonic() < deadline:
                assert self.ac(), 'AC disconnected; stop workload'
                assert time.monotonic() < self.return_deadline - 180, 'automatic-return recovery reserve exhausted'
                assert all(w.poll() is None for w in self.workers), 'CPU worker exited unexpectedly'
                sample = self.sample('load')
                if sample['maximum'] >= CEILING:
                    self.result['stop_reason'] = '80C ceiling'
                    break
                sample['workload'] = self.workload()
                sample['workload']['load_seconds'] = round(time.monotonic() - started, 3)
                # Flushed completed rows reject software/failing scenes live.
                if self.gpu_xml.exists():
                    self.result['gpu_completed_rows'] = gpu_rows(self.gpu_xml)
                self.save()
                time.sleep(min(1, max(0, deadline - time.monotonic())))
            else:
                self.result['stop_reason'] = '300s combined workload bound'
            self.result['load_seconds'] = round(time.monotonic() - started, 3)
            self.stop()
            assert self.result['workers_stopped'] and self.result['gpu_stopped'] and self.result['gpu_group_stopped'], 'workload cleanup incomplete'
            self.result['gpu_completed_rows'] = gpu_rows(self.gpu_xml)
            self.result['gpu_xml_interrupted'] = not self.gpu_xml.read_text().rstrip().endswith('</glmark2>')
            self.result['overlap_10s_windows'] = overlap_coverage(self.result['samples'])
            self.result['combined_load_witnessed'] = (set(range(2, 30)) <= set(self.result['overlap_10s_windows'])
                                                     and bool(self.result['gpu_completed_rows']))
            recovered = self.recover()
            self.result['responses'] = {str(i): response_proven(self.result['samples'], self.result['before'], i) for i in (0, 1)}
            self.result['automatic_cpu_response_proven'] = all(self.result['responses'].values()) and recovered
            # A bounded combined run can pass without reaching the CPU trip.
            self.result['complete'] = (self.result['stop_reason'] == '300s combined workload bound'
                                       and self.result['combined_load_witnessed'] and recovered
                                       and len(self.result['gpu_completed_rows']) >= 2)
        except Exception as error:
            self.result['error'] = str(error)
        finally:
            try:
                self.stop()
            except Exception as error:
                self.result['cleanup_error'] = str(error)
                self.result['complete'] = False
            if 'before' in self.result and 'recovered' not in self.result:
                try:
                    self.recover()
                except Exception as error:
                    self.result['recovery_error'] = str(error)
            if self.result.get('kernel_cursor'):
                try:
                    new_kernel = subprocess.check_output(['journalctl', '-b', '-k', '--no-pager',
                        '-o', 'cat', '--after-cursor', self.result['kernel_cursor']], text=True, timeout=10)
                    (self.output / 'kernel-workload.log').write_text(new_kernel)
                    self.result['kernel_faults'] = FAULTS.findall(new_kernel)
                    if self.result['kernel_faults']:
                        self.result['complete'] = False
                except Exception as error:
                    self.result['kernel_window_error'] = str(error)
                    self.result['complete'] = False
            if self.gpu_directory:
                try:
                    if self.gpu_xml.is_file():
                        assert not self.gpu_xml.is_symlink()
                        retained = self.output / 'gpu-results.xml'
                        shutil.copyfile(self.gpu_xml, retained)
                        retained.chmod(0o600)
                        self.result['gpu_results_file'] = str(retained)
                    shutil.rmtree(self.gpu_directory)
                except Exception as error:
                    self.result['gpu_output_error'] = str(error)
                    self.result['complete'] = False
            for name, args in [('kernel.log', ['-k']), ('journal.log', [])]:
                temporary = self.output / (name + '.tmp')
                try:
                    with temporary.open('wb') as stream:
                        subprocess.run(['journalctl', '-b', '--no-pager', '-o', 'short-monotonic', *args],
                                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=10)
                    os.replace(temporary, self.output / name)
                except Exception as error:
                    self.result['capture_error'] = str(error)
                    self.result['complete'] = False
            self.save()
        return self.result
