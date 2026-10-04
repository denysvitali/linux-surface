#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Collect bounded GBM offscreen image validation and sustained GPU evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
BOOT_PATH = Path('/proc/sys/kernel/random/boot_id')
FAULTS = re.compile(r'^.*(?:\bOops:|Kernel panic|\bBUG:|Call trace:|'
                    r'(?:GPU|GMU|adreno|msm|IOMMU|arm-smmu).*'
                    r'\b(?:hangcheck|hang|hung|fault|timeout|timed out|reset|'
                    r'resetting|recover|recovering|recovery|crash|crashed|watchdog|lockup)\b|'
                    r'remoteproc.*crash).*$' , re.M | re.I)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_result(path, scenes, seconds, renderer, validation, api):
    root = ET.parse(path).getroot()
    assert root.tag == 'glmark2'
    info = {n.tag: n.text for n in root.find('info')}
    assert info['gl_renderer'] == renderer, info
    assert 'llvmpipe' not in str(info).lower() and 'softpipe' not in str(info).lower()
    assert ('OpenGL ES' in info['gl_version']) == ('es2' in api), info
    rows = [{n.tag: n.text for n in item} for item in root.findall('benchmark')]
    assert len(rows) == len(scenes), (len(rows), len(scenes))
    for row, scene in zip(rows, scenes):
        parts = scene.split(':')
        expected = dict(p.split('=', 1) for p in parts[1:])
        expected['duration'] = str(seconds)
        match = re.fullmatch(r'\[([^]]+)\] (.*)', row['name'])
        assert match and match[1] == parts[0], row
        actual = dict(p.split('=', 1) for p in match[2].split(':'))
        assert actual == expected, (actual, expected)
    assert all(row['status'] == 'Success' for row in rows), rows
    if not validation:
        assert all(float(row['fps']) > 0 and float(row['frame_time']) > 0 for row in rows)
    return {'info': info, 'benchmarks': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference-smoke', action='store_true')
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    plan = json.loads((HERE / 'plan.json').read_text())
    boot = BOOT_PATH.read_text().strip()
    cmdline = Path('/proc/cmdline').read_text().strip()
    if args.reference_smoke:
        assert os.uname().release == '6.18.3-1-surface+'
        assert 'spx_boot=known-good' in cmdline.split()
        scene_seconds, idle_seconds = 1, 1
    else:
        assert os.uname().release == plan['candidate_release']
        assert ('spx_attempt=' + plan['attempt']) in cmdline.split()
        scene_seconds, idle_seconds = plan['scene_seconds'], plan['idle_seconds']
        assert scene_seconds == 60 and idle_seconds == 30
    manifest = json.loads((args.fixture / 'sha256.json').read_text())
    for name, digest in manifest.items():
        assert sha(args.fixture / name) == digest, name
    args.output.mkdir(mode=0o700)
    user = pwd.getpwnam('dvitali')
    results = args.output / 'user-results'
    results.mkdir(mode=0o700)
    os.chown(results, user.pw_uid, user.pw_gid)
    # Permit traversing this result root only; no archived recovery data is exposed.
    args.output.chmod(0o711)
    metadata = {'boot_id': boot, 'release': os.uname().release, 'cmdline': cmdline,
                'reference_smoke': args.reference_smoke, 'plan_sha256': sha(HERE / 'plan.json'),
                'fixture_manifest_sha256': sha(args.fixture / 'sha256.json'),
                'collector_sha256': sha(Path(__file__)), 'started': time.time(),
                'expected_render_seconds': 30 * scene_seconds,
                'runs': [], 'observations': [], 'hardware_acceptance_closed': False}

    def gpu_power():
        root = Path('/sys/class/devfreq/2c00000.gpu/device/power')
        return {name: (root / name).read_text().strip() for name in
                ('runtime_status', 'runtime_active_time', 'runtime_suspended_time')
                if (root / name).is_file()}

    def save():
        (args.output / 'progress.json').write_text(json.dumps(metadata, indent=2) + '\n')

    def observe(label):
        assert BOOT_PATH.read_text().strip() == boot
        assert os.uname().release == metadata['release']
        observation = {'label': label, 'monotonic': time.monotonic(),
                       'taint': Path('/proc/sys/kernel/tainted').read_text().strip(),
                       'devfreq': {}, 'drm_connectors': {}, 'thermal': {},
                       'gpu_power': gpu_power(), 'desktop': []}
        pids = subprocess.check_output(['pgrep', '-u', str(user.pw_uid), '-x', 'gnome-shell'], text=True).split()
        assert len(pids) == 1, pids
        for pid in pids:
            proc = Path('/proc') / pid
            nodes = []
            for fd in (proc / 'fd').glob('*'):
                try:
                    target = os.readlink(fd)
                except FileNotFoundError:
                    continue
                if target.startswith('/dev/dri/'):
                    nodes.append(target)
            observation['desktop'].append({'pid': int(pid),
                'start_ticks': (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19],
                'cmdline': (proc / 'cmdline').read_bytes().decode().replace('\0', ' '),
                'drm_nodes': sorted(nodes)})
        if metadata['observations']:
            assert [(d['pid'], d['start_ticks']) for d in observation['desktop']] == [
                (d['pid'], d['start_ticks']) for d in metadata['observations'][0]['desktop']]
        for path in Path('/sys/class/devfreq').glob('*'):
            observation['devfreq'][path.name] = {
                n: (path / n).read_text().strip() for n in
                ('name', 'cur_freq', 'governor') if (path / n).is_file()}
        for path in Path('/sys/class/drm').glob('card*-*'):
            observation['drm_connectors'][path.name] = {
                n: (path / n).read_text().strip() for n in ('status', 'enabled', 'modes')
                if (path / n).is_file()}
        for path in Path('/sys/class/thermal').glob('thermal_zone*'):
            observation['thermal'][path.name] = {
                n: (path / n).read_text().strip() for n in ('type', 'temp')
                if (path / n).is_file()}
        metadata['observations'].append(observation)
        save()

    def demote():
        os.setgroups(os.getgrouplist(user.pw_name, user.pw_gid))
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)

    def run(api, label, scenes, validation=False):
        xml = results / (label + '.xml')
        command = [str(args.fixture / 'bin' / api), '--off-screen',
                   '--winsys-options=drm-device=' + plan['render_node'],
                   '--data-path', str(args.fixture / 'data'), '--size', plan['size'],
                   '--frame-end=finish', '--results=fps:cpu:shader',
                   '--results-file', str(xml)]
        if validation:
            command.append('--validate')
        for scene in scenes:
            command += ['--benchmark', scene + ':duration=' + str(scene_seconds)]
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                       'XDG_RUNTIME_DIR': '/run/user/' + str(user.pw_uid)}
        start = time.monotonic()
        record = {'api': api, 'label': label, 'validation': validation,
                  'command': command, 'scene_count': len(scenes), 'fd_samples': []}
        metadata['runs'].append(record)
        save()
        with (args.output / (label + '.log')).open('xb') as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                       env=environment, preexec_fn=demote,
                                       start_new_session=True)
            deadline = start + (120 if validation else len(scenes) * scene_seconds + 120)
            try:
                while process.poll() is None:
                    assert BOOT_PATH.read_text().strip() == boot
                    nodes = []
                    for fd in Path('/proc/' + str(process.pid) + '/fd').glob('*'):
                        try:
                            target = os.readlink(fd)
                        except FileNotFoundError:
                            continue
                        if target.startswith('/dev/dri/'):
                            nodes.append(target)
                    record['fd_samples'].append({'elapsed': time.monotonic() - start,
                                                 'nodes': sorted(nodes), 'gpu_power': gpu_power()})
                    save()
                    assert all(n == plan['render_node'] for n in nodes), nodes
                    assert time.monotonic() < deadline, 'benchmark timeout'
                    time.sleep(0.2 if args.reference_smoke else 5)
                record['returncode'] = process.returncode
                record['elapsed_seconds'] = time.monotonic() - start
                assert process.returncode == 0, label
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                save()
        assert any(plan['render_node'] in s['nodes'] for s in record['fd_samples']), label
        record['result'] = parse_result(xml, scenes, scene_seconds, plan['renderer'], validation, api)
        record['xml_sha256'] = sha(xml)
        record['log_sha256'] = sha(args.output / (label + '.log'))
        if not validation:
            assert record['elapsed_seconds'] >= len(scenes) * scene_seconds, label
        save()
        observe(label + '-complete')

    try:
        observe('before')
        initial_taint = metadata['observations'][0]['taint']
        if not args.reference_smoke:
            assert initial_taint == '0'
        before = subprocess.check_output(['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], text=True)
        (args.output / 'kernel-before.log').write_text(before)
        for api in plan['apis']:
            scenes = [scene for phase in plan['phases'] for scene in phase]
            run(api, api + '-validate-before', scenes, validation=True)
            for index, phase in enumerate(plan['phases']):
                run(api, api + '-phase-' + str(index), phase)
                observe(api + '-idle-' + str(index) + '-start')
                time.sleep(idle_seconds)
                observe(api + '-idle-' + str(index) + '-end')
            run(api, api + '-validate-after', scenes, validation=True)
        after = subprocess.check_output(['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], text=True)
        (args.output / 'kernel-after.log').write_text(after)
        metadata['kernel_faults'] = FAULTS.findall(after)
        assert not metadata['kernel_faults'], metadata['kernel_faults']
        assert all(o['taint'] == initial_taint for o in metadata['observations'])
        observe('after')
        metadata['scoped_passed'] = True
        metadata['finished'] = time.time()
        save()
    except BaseException as error:
        metadata['scoped_passed'] = False
        metadata['failure'] = repr(error)
        metadata['finished'] = time.time()
        try:
            after = subprocess.check_output(['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], text=True)
            if not (args.output / 'kernel-after.log').exists():
                (args.output / 'kernel-after.log').write_text(after)
            metadata['kernel_faults'] = FAULTS.findall(after)
        except BaseException as log_error:
            metadata['log_collection_failure'] = repr(log_error)
        save()
        raise
    finally:
        args.output.chmod(0o700)
        for path in results.rglob('*'):
            if path.is_file():
                os.chown(path, 0, 0)
        os.chown(results, 0, 0)
        hashes = {str(p.relative_to(args.output)): sha(p)
                  for p in sorted(args.output.rglob('*')) if p.is_file()}
        (args.output / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
        os.sync()


if __name__ == '__main__':
    main()
