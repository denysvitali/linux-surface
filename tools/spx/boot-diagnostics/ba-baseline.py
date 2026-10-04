#!/usr/bin/python3
"""Archive BA right command-history diagnostic without playback."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from ba_camera_core import decode, complete_trial_findings
from pathlib import Path

os.umask(0o077)
ATTEMPT = '20261004ba'
RELEASE = '7.3.0-rc2-spx-mainline-20261004ba+'
BASE = Path('/var/lib/spx-boot-diagnostics')
RUN = BASE / 'attempts' / ATTEMPT
BOOT = Path('/proc/sys/kernel/random/boot_id')


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90)


def command_history_summary(kernel, params):
    lines = [line.split('SPX cmd diag ', 1)[1] for line in kernel.splitlines()
             if 'qcom-soundwire' in line and 'SPX cmd diag ' in line]
    dumps, malformed = [], []
    header = re.compile(r'history count=(\d+) submission-only')
    record = re.compile(r'seq=(\d+) submitted_ns=(\d+) op=([RW]) packed=([0-9a-f]{8}) bridge_rc=(-?\d+)')
    for line in lines:
        h, r = header.fullmatch(line), record.fullmatch(line)
        if h:
            dumps.append({'declared_count': int(h[1]), 'records': []})
        elif r and dumps:
            packed = int(r[4], 16)
            dumps[-1]['records'].append({'sequence': int(r[1]), 'submitted_ns': int(r[2]),
                'op': r[3], 'packed': r[4], 'bridge_rc': int(r[5]),
                'address': packed & 0xffff, 'command_id': (packed >> 16) & 15,
                'device_number': (packed >> 20) & 15, 'data_or_length': packed >> 24})
        else:
            malformed.append(line)
    good = not malformed and len(dumps) <= 2 and len(lines) <= 34
    for d in dumps:
        rs = d['records']
        good = good and 1 <= d['declared_count'] <= 16 and len(rs) == d['declared_count']
        good = good and all(b['sequence'] == a['sequence'] + 1 and
                            b['submitted_ns'] >= a['submitted_ns'] for a, b in zip(rs, rs[1:]))
    return {'enabled': params.get('spx_cmd_diag') == 'Y', 'well_formed': bool(good),
            'line_count': len(lines), 'dumps': dumps, 'malformed_lines': malformed,
            'maximum_lines': 34, 'hardware_acknowledgment_verified': False}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def manifest(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def readable_parameters(root):
    # Some diagnostic triggers, including spx_rearm_init, are write-only.
    # Root still cannot read those sysfs files; do not abort result collection.
    return {p.name: p.read_text().strip() for p in root.iterdir()
            if p.stat().st_mode & 0o444} if root.is_dir() else {}


def main():
    assert os.geteuid() == 0
    bid = BOOT.read_text().strip()
    assert command('uname', '-r').strip() == RELEASE
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    assert 600 <= uptime < 900, uptime
    assert not (RUN / 'final-result').exists()
    a = json.loads((RUN / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == ATTEMPT and a['release'] == RELEASE
    cmdline = Path('/proc/cmdline').read_text().split()
    assert cmdline == ['BOOT_IMAGE=/spx-trial-20261004ba/vmlinuz'] + a['cmdline'].split()
    selectors = ['spx_attempt=20261004ba', 'spx_diag_window=600',
                 'slim_qcom_ngd_ctrl.spx_probe_stage=8',
                 'slim_qcom_ngd_ctrl.spx_stage8_step=2',
                 'slim_qcom_ngd_ctrl.spx_allow_full=1',
                 'soundwire_qcom.spx_force_attach=0',
                 'snd_soc_wsa881x.spx_enumerated_mode=1',
                 'slim_qcom_ngd_ctrl.spx_pio_mode=1',
                 'slim_qcom_ngd_ctrl.spx_pio_cap_retries=0',
                 'slim_qcom_ngd_ctrl.spx_pin_after_qmi=1',
                 'wcd934x.spx_wsa_en_pin=2',
                 'soundwire_qcom.spx_enum_diag=1', 'soundwire_qcom.spx_cmd_diag=1', 'spi_hid.startup_diag=1']
    assert all(cmdline.count(token) == 1 for token in selectors)
    taint = Path('/proc/sys/kernel/tainted').read_text().strip()
    env = command('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert not any(line.startswith('next_entry=') and line != 'next_entry='
                   for line in env.splitlines())
    assert 'BootNext:' not in command('efibootmgr')
    assert command('systemctl', 'is-active', 'spx-ba-fallback.timer').strip() == 'active'
    assert command('systemctl', 'show', 'spx-diag-long-return.timer',
                   '-p', 'ActiveState', '--value').strip() != 'active'
    assert command('systemctl', 'show', 'spx-diag-return.timer',
                   '-p', 'ActiveState', '--value').strip() != 'active'
    for name, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
        assert sha(Path(name)) == digest, name
    for name, digest in json.loads((RUN / 'build/dtb-build/sha256.json').read_text()).items():
        assert sha(RUN / 'build/dtb-build' / name) == digest, name
    build_manifest = json.loads((RUN / 'build-sha256.json').read_text())
    assert build_manifest
    assert set(build_manifest) == set(manifest(RUN / 'build'))
    for name, digest in build_manifest.items():
        assert sha(RUN / 'build' / name) == digest, name
    module_manifest = json.loads((RUN / 'build/module-sha256.json').read_text())
    module_root = Path('/usr/lib/modules') / RELEASE
    assert len(module_manifest) == 217
    assert set(module_manifest) == set(manifest(module_root))
    for name, digest in module_manifest.items():
        assert sha(module_root / name) == digest, name

    kernel = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
    journal = command('journalctl', '-b', '-o', 'short-monotonic', '--no-pager')
    required = ['SPX: child probe entry stage=8 stage7=0 stage8=2',
                'SPX: stage 8 runtime resume begin step=2 state=',
                'SPX: QMI power-on acked by ADSP',
                'SPX: PIO poll thread started',
                'SPX: stage 8 runtime resume done step=2 ret=0 state=0 active=1',
                'SLIM controller Registered',
                'SPX: child probe: enable done']
    markers = {item: kernel.count(item) for item in required}
    retained = kernel.count('SPX: power up retained logical address status=')
    setup = kernel.count('SPX: power up needs capability setup status=')
    done = kernel.count('SPX: capability exchange DONE')
    failed = kernel.count('SPX: stage 8 runtime resume failed')
    registered = kernel.count('SLIM controller Registered')
    force_start = kernel.count('SPX enum work enter core_enum=0 force=1')
    force_done = kernel.count('SPX FORCE-ATTACH: stable attachment')
    force_slaves = kernel.count('SPX FORCE-ATTACH: sdw:')
    timed_out = kernel.count('SPX: PIO capability exchange timed out') + kernel.count('capability exchange timed-out')
    bad = re.findall(r'^.*(?:\bOops:|Kernel panic|\bBUG:|Call trace:|GPU.*hangcheck|'
                     r'GMU.*(?:fault|watchdog)|PIO TX.*(?:NACKed|error|timed out)|'
                     r'PIO RX disabled|unexpected IRQ|remoteproc.*crash).*$'
                     , kernel, re.M | re.I)
    graph = 'OpenGL ES profile renderer: FD680' in journal
    network = command('nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status')
    wifi = 'wlan0:wifi:connected' in network.splitlines()
    touch_path = Path('/sys/bus/spi/devices/spi0.0/ready')
    touch = touch_path.is_file() and touch_path.read_text().strip() == 'ready'
    cards = Path('/proc/asound/cards').read_text()
    no_cards = cards.strip() == '--- no soundcards ---'
    slim_bus = Path('/sys/bus/slimbus/devices')
    slim_devices = sorted(p.name for p in slim_bus.iterdir()) if slim_bus.is_dir() else []
    slim_drivers = {p.name: (p / 'driver').resolve().name if (p / 'driver').is_symlink()
                    else None for p in slim_bus.iterdir()} if slim_bus.is_dir() else {}
    sdw_bus = Path('/sys/bus/soundwire/devices')
    sdw_slaves = {p.name: {
        'status': (p / 'status').read_text().strip(),
        'device_number': (p / 'device_number').read_text().strip(),
        'driver': (p / 'driver').resolve().name if (p / 'driver').is_symlink() else None,
        'of_node': str((p / 'of_node').resolve()) if (p / 'of_node').is_symlink() else None}
        for p in sorted(sdw_bus.glob('sdw:*'))} if sdw_bus.is_dir() else {}
    attached = sum(v['status'].casefold() == 'attached' and v['device_number'] == '1'
                   for v in sdw_slaves.values())
    wsa_mode_path = Path('/sys/module/snd_soc_wsa881x/parameters/spx_enumerated_mode')
    wsa_mode = wsa_mode_path.read_text().strip() if wsa_mode_path.is_file() else None
    wsa_init = kernel.count('SPX: initializing amplifier at SoundWire device 1')
    wsa_init_fail = kernel.count('Slave 1 initialization failed')
    wsa_status_fail = kernel.count('Update Slave status failed')
    wsa_write_overflows = kernel.count('swrm_wait_for_wr_fifo_avail err write overflow')
    wsa_read_underflows = kernel.count('swrm_wait_for_rd_fifo_avail err read underflow')
    codec_log = [line for line in kernel.splitlines() if any(
        item in line.lower() for item in ('wcd934', 'wsa881x', 'soundwire', 'failed to get logical address',
                                          'slim: tx timed out', 'slim:'))]
    power_path = ('retained-address' if retained == 1 and setup == 0 else
                  'capability-setup' if setup == 1 and retained == 0 else 'inconclusive')
    power_path_passed = (power_path == 'retained-address' or
                         (power_path == 'capability-setup' and done == 1))
    healthy = (all(value == 1 for value in markers.values()) and not bad and
               failed == 0 and registered == 1 and timed_out == 0)
    wcd_dir = Path('/sys/module/wcd934x/parameters')
    wcd_params = readable_parameters(wcd_dir)
    wsa_params_dir = Path('/sys/module/snd_soc_wsa881x/parameters')
    wsa_params = readable_parameters(wsa_params_dir)
    gpio = Path('/sys/kernel/debug/gpio').read_text()
    register_view = {}
    register_path = Path('/sys/kernel/debug/regmap/217:250:1:0/registers')
    if register_path.is_file():
        with register_path.open() as stream:
            for line in stream:
                match = re.fullmatch(r'([0-9a-f]+): ([0-9a-f]+)\n', line)
                if not match:
                    continue
                reg = int(match[1], 16)
                if reg > 0x43:
                    break
                if reg in (0x42, 0x43):
                    register_view[match[1]] = int(match[2], 16)
    direction = register_view.get('0042')
    value = register_view.get('0043')
    pin_state_passed = (wcd_params.get('spx_wsa_en_pin') == '2' and
                       wcd_params.get('spx_wsa_gpio_dir') == '-1' and
                       wcd_params.get('spx_wsa_gpio_val') == '-1' and
                       wsa_params.get('spx_swap_dac_master_ports') == 'N' and
                       direction == 0x04 and value == 0x1c and
                       kernel.count('SPX: forced wcd-gpio pin 2 output-high') == 1)
    swr_params = readable_parameters(Path('/sys/module/soundwire_qcom/parameters'))
    raw_trace = [line for line in kernel.splitlines() if 'SPX enum diag slot=' in line and ' words=' in line]
    decoded_trace = [line for line in kernel.splitlines() if 'SPX enum diag slot=' in line and ' decoded=' in line]
    declared_names = {'sdw:0:0:0217:2110:00:3', 'sdw:0:0:0217:2110:00:4'}
    extra_slaves = sorted(set(sdw_slaves) - declared_names)
    allowed_extra = set()
    identity_diag_passed = (swr_params.get('spx_enum_diag') == 'Y' and
                           1 <= len(raw_trace) <= 8 and
                           1 <= len(decoded_trace) <= len(raw_trace) and
                           any('rc=0/0' in line for line in raw_trace) and
                           any('slot=1 decoded=0217:2110 unique=4' in line for line in decoded_trace))
    topology_preserved = (declared_names <= set(sdw_slaves) and
                          set(extra_slaves) <= allowed_extra and
                          all(sdw_slaves[name]['driver'] == 'wsa881x-codec' and sdw_slaves[name]['of_node'] for name in declared_names) and
                          all(sdw_slaves[name]['driver'] is None and
                              sdw_slaves[name]['status'] == 'UNATTACHED' and
                              sdw_slaves[name]['device_number'] == 'N/A' for name in extra_slaves))
    right = sdw_slaves.get('sdw:0:0:0217:2110:00:4', {})
    firmware_identity_match = (right.get('status', '').casefold() == 'attached' and
                               right.get('device_number') == '1' and
                               (right.get('of_node') or '').endswith('/speaker@0,4'))
    native_bus_errors = re.findall(r'^.*qcom-soundwire.*(?:FIFO.*(?:underflow|overflow)|SWR CMD error|bus clsh|Port collision|link failed to connect|clock stop failed|bus failed to exit clock stop|unknown interrupt).*$', kernel, re.M | re.I)
    native_path_passed = (swr_params.get('spx_force_attach') == '0' and
                          swr_params.get('spx_core_enum') == '0' and
                          swr_params.get('spx_watchdog') == '0' and
                          swr_params.get('spx_exact_windows_init') == 'N' and
                          kernel.count('SPX enum work enter') == 0 and
                          force_done == 0 and force_slaves == 0 and
                          all('force_pending=0 forced=0' in line for line in raw_trace) and
                          not native_bus_errors)
    pm_snapshot = {}
    pm_paths = set()
    for p in sdw_bus.glob('sdw:*'):
        q = p.resolve()
        pm_paths.add(q)
        pm_paths.update(list(q.parents)[:3])
    for p in sorted(pm_paths):
        if not (p / 'power').is_dir():
            continue
        pm_snapshot[str(p)] = {}
        for name in ('control', 'runtime_status', 'runtime_active_time', 'runtime_suspended_time', 'autosuspend_delay_ms'):
            field = p / 'power' / name
            if field.is_file():
                try:
                    pm_snapshot[str(p)][name] = field.read_text().strip()
                except OSError as error:
                    pm_snapshot[str(p)][name] = {'read_errno': error.errno}
    # Existing bounded SPI-HID logger: no additional device transfers here.
    touch_params = readable_parameters(Path('/sys/module/spi_hid/parameters'))
    touch_state = {}
    for name in ('ready', 'bus_error_count', 'logic_error_count',
                 'regulator_error_count', 'device_initiated_reset_count'):
        field = touch_path.parent / name
        try:
            touch_state[name] = field.read_text().strip()
        except OSError as error:
            touch_state[name] = {'read_errno': error.errno}
    touch_diag = [line for line in kernel.splitlines()
                  if 'spi_hid spi0.0:' in line and 'startup-diag:' in line]
    touch_windows = {}
    for line in touch_diag:
        m = re.search(r'startup-diag: window=(\d+) event=([a-z-]+)', line)
        if m:
            touch_windows.setdefault(m.group(1), []).append(m.group(2))
    touch_diag_passed = (touch_params.get('startup_diag') == 'Y' and
                         1 <= len(touch_diag) <= 384 and
                         sum(map(len, touch_windows.values())) == len(touch_diag) and
                         1 <= len(touch_windows) <= 8 and
                         all(1 <= int(w) <= 8 and len(events) <= 48 and
                             events[0] == 'begin' and events.count('begin') == 1
                             for w, events in touch_windows.items()))
    cmd_history = command_history_summary(kernel, swr_params)
    cmd_diag_passed = cmd_history['enabled'] and cmd_history['well_formed']
    right_init = kernel.count('wsa881x-codec sdw:0:0:0217:2110:00:4: SPX: initializing amplifier at SoundWire device 1')
    passed = (cmd_diag_passed and right_init >= 1 and touch_diag_passed and native_path_passed and firmware_identity_match and identity_diag_passed and topology_preserved and pin_state_passed and power_path_passed and healthy and len(slim_devices) == 2 and
              not no_cards and
              force_start == 0 and force_done == 0 and force_slaves == 0 and
              attached >= 1 and
              wsa_mode == 'Y' and wsa_init >= 1 and
              wsa_init_fail == 0 and wsa_status_fail == 0 and
              wsa_write_overflows == 0 and wsa_read_underflows == 0 and
              graph and wifi and touch and taint == '0')

    # A separate finding does not waive AE functional criteria or control fallback.
    paired = re.compile(r'SPX enum diag slot=(\d+).*?rc=0/0 words=[0-9a-f]{8}/[0-9a-f]{8}\n.*?SPX enum diag slot=\1 decoded=0217:(?:2010|2110) unique=[34] version=[0-9a-f]+ class=[0-9a-f]+')
    pin2_diagnostic = (pin_state_passed and native_path_passed and
                       swr_params.get('spx_enum_diag') == 'Y' and
                       1 <= len(raw_trace) <= 8 and 1 <= len(decoded_trace) <= len(raw_trace) and
                       bool(paired.search('\n'.join(line for line in kernel.splitlines() if 'SPX enum diag slot=' in line))) and
                       power_path_passed and healthy and touch_diag_passed and
                       graph and wifi and touch and taint == '0')

    subprocess.run(['/usr/local/lib/spx-boot-diagnostics/ba-camera-control.py', '--final'], check=False, timeout=90)
    camera_findings = {'camera_control_initial_passed': False, 'camera_control_final_passed': False,
                       'camera_observations_ordered': False, 'camera_control_passed': False,
                       'camera_provider_idle_passed': False, 'camera_trial_passed': False}
    camera_evidence = {}
    for name in ('camera-control-result', 'camera-control-final-result', 'camera-provider-result'):
        root = RUN / name
        if (root / 'sha256.json').is_file():
            expected = json.loads((root / 'sha256.json').read_text())
            assert manifest(root) == expected | {'sha256.json': sha(root / 'sha256.json')}
            camera_evidence[name] = json.loads((root / 'report.json').read_text())
    if len(camera_evidence) == 3:
        control = camera_evidence['camera-control-result']
        final_control = camera_evidence['camera-control-final-result']
        providers = camera_evidence['camera-provider-result']
        for label in ('camera-control-result', 'camera-control-final-result'):
            for name in ('ba-camera-control.py', 'ba_camera_core.py'):
                assert sha(RUN / label / name) == a['runtime_sha256'][
                    '/usr/local/lib/spx-boot-diagnostics/' + name]
        assert sha(RUN / 'camera-provider-result/ba-camera-provider.py') == a['runtime_sha256'][
            '/usr/local/lib/spx-boot-diagnostics/ba-camera-provider.py']
        reference_root = BASE / 'attempts/20261002ap/camera-pmic-metadata-20261003'
        assert sha(reference_root / 'sha256.json') == '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
        for name, digest in json.loads((reference_root / 'sha256.json').read_text()).items():
            assert sha(reference_root / name) == digest
        reference = decode(json.loads((reference_root / 'result.json').read_text())['reads'])
        camera_findings = complete_trial_findings(control, final_control, providers, reference, {
            'boot_id': bid, 'release': RELEASE, 'taint': taint,
            'cmdline': Path('/proc/cmdline').read_text().strip()})
    passed_trial = bool(passed and camera_findings['camera_trial_passed'])

    # Refresh then copy one consistent collector snapshot under its lock.
    subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'], check=True,
                   timeout=90)
    assert BOOT.read_text().strip() == bid
    out = RUN / ('final-result.partial.' + bid)
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / 'finalize.py')
    for name in camera_evidence:
        shutil.copytree(RUN / name, out / name)
    (out / 'kernel.log').write_text(kernel)
    (out / 'dmesg-raw.log').write_text(command('dmesg', '--raw'))
    (out / 'journal.log').write_text(journal)
    with (out / 'journal.export').open('wb') as stream:
        subprocess.run(['journalctl', '-b', '-o', 'export', '--no-pager'],
                       stdout=stream, check=True, timeout=90)
    collector = BASE / 'boots' / bid
    with (collector / 'collect.lock').open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        shutil.copytree(collector, out / 'collector', symlinks=True,
                        ignore=shutil.ignore_patterns('collect.lock'))
    initrd = Path('/boot/spx-diagnostics') / bid
    if initrd.is_dir():
        shutil.copytree(initrd, out / 'initrd', symlinks=True)
    else:
        (out / 'initrd-missing').write_text('No per-boot initramfs log directory\n')
    (out / 'grubenv').write_text(env)
    (out / 'network').write_text(network)
    (out / 'interrupts').write_text(Path('/proc/interrupts').read_text())
    (out / 'cmdline').write_text(' '.join(cmdline) + '\n')
    params_dir = Path('/sys/module/slim_qcom_ngd_ctrl/parameters')
    params = ({p.name: p.read_text().strip() for p in params_dir.iterdir()}
              if params_dir.is_dir() else {})
    (out / 'audio-params.json').write_text(json.dumps(params, indent=2) + '\n')
    (out / 'slim-devices.json').write_text(json.dumps(slim_drivers, indent=2) + '\n')
    (out / 'soundwire-slaves.json').write_text(json.dumps(sdw_slaves, indent=2) + '\n')
    (out / 'codec-lines.log').write_text('\n'.join(codec_log) + '\n')
    (out / 'asound-cards').write_text(cards)
    (out / 'gpio').write_text(gpio)
    (out / 'touch-state.json').write_text(json.dumps(touch_state, indent=2) + '\n')
    (out / 'touch-params.json').write_text(json.dumps(touch_params, indent=2) + '\n')
    (out / 'touch-startup.log').write_text('\n'.join(touch_diag) + '\n')
    (out / 'input-devices').write_text(Path('/proc/bus/input/devices').read_text())
    (out / 'iptsd-state').write_text(command('systemctl', 'show', 'iptsd@*.service', '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts'))
    (out / 'runtime-pm.json').write_text(json.dumps(pm_snapshot, indent=2) + '\n')
    (out / 'swr-params.json').write_text(json.dumps(swr_params, indent=2) + '\n')
    (out / 'enumeration-trace.log').write_text('\n'.join(raw_trace + decoded_trace) + '\n')
    (out / 'wcd-params.json').write_text(json.dumps(wcd_params, indent=2) + '\n')
    (out / 'wsa-params.json').write_text(json.dumps(wsa_params, indent=2) + '\n')
    (out / 'wcd-gpio-registers.json').write_text(json.dumps(register_view, indent=2) + '\n')
    result = {'attempt': ATTEMPT, 'boot_id': bid, 'release': RELEASE,
              'uptime_seconds': uptime, 'power_path': power_path,
              'required_markers': markers, 'retained_path_markers': retained,
              'capability_setup_path_markers': setup,
              'capability_done_markers': done, 'capability_timeout_markers': timed_out,
              'runtime_resume_failure_markers': failed,
              'controller_registration_markers': registered, 'kernel_fault_lines': bad,
              'force_attach_worker_entries': force_start,
              'force_attach_done_markers': force_done,
              'force_attach_slave_markers': force_slaves,
              'soundwire_slaves': sdw_slaves, 'attached_slave_count': attached,
              'wsa_enumerated_mode': wsa_mode,
              'wsa_cold_init_markers': wsa_init,
              'right_wsa_cold_init_markers': right_init,
              'command_diagnostic_passed': cmd_diag_passed,
              'command_history': cmd_history,
              'wsa_slave_init_failures': wsa_init_fail,
              'wsa_status_update_failures': wsa_status_fail,
              'wsa_write_overflows': wsa_write_overflows,
              'wsa_read_underflows': wsa_read_underflows,
              'gpio_software_state_passed': pin_state_passed,
              'pin2_enumeration_diagnostic_passed': pin2_diagnostic,
              'pin2_diagnostic_controls_fallback': False,
              'identity_diagnostic_passed': identity_diag_passed,
              'native_force_off_path_passed': native_path_passed,
              'native_bus_error_lines': native_bus_errors,
              'runtime_pm_snapshot_paths': len(pm_snapshot),
              'firmware_identity_match_passed': firmware_identity_match,
              'declared_topology_preserved': topology_preserved,
              'extra_soundwire_devices': extra_slaves,
              'enumeration_raw_log_count': len(raw_trace),
              'enumeration_decoded_log_count': len(decoded_trace),
              'slim_devices': slim_devices, 'slim_drivers': slim_drivers,
              'codec_log_lines': codec_log,
              'fd680_renderer': graph, 'wifi_connected': wifi, 'spi_hid_ready': touch,
              'soundcards_present': not no_cards, 'asound_cards': cards,
              'kernel_taint': taint,
              'passed_scoped_baseline': passed, 'passed_trial': passed_trial, **camera_findings,
              'touch_startup_diagnostic_passed': touch_diag_passed,
              'touch_startup_diagnostic_lines': len(touch_diag),
              'touch_startup_windows': touch_windows,
              'touch_state': touch_state,
              'touch_startup_open_timeouts': kernel.count('spi_hid_ll_open: firmware did not become ready'),
              'touch_startup_invalid_headers': kernel.count('Invalid input report sync constant'),
              'touch_startup_clean': not any(x in kernel for x in ('spi_hid_ll_open: firmware did not become ready', 'Invalid input report sync constant', 'startup response polling timed out')),
              'touch_diagnostic_limit_windows': 8,
              'touch_diagnostic_limit_events_per_window': 48,
              'recovery_return_performed_at_snapshot': False,
              'fallback_action': 'leave 900-second fallback armed for the startup trial',
              'sustained_gpu_pending': False, 'hardware_acceptance_closed': False,
              'limits': ['No playback or PCM probe was run; acoustic output remains unverified.',
                         'The forced path is disabled; native status and submitted writes do not prove physical readback, idle resume or acoustic output.',
                         'Nonvolatile GPIO register views may be cached and do not measure physical pad voltage.',
                         'No live parameter change or device rebind was attempted.']}
    (out / 'command-history.json').write_text(json.dumps(cmd_history, indent=2) + '\n')
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    hashes = manifest(out)
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    assert set(hashes) == set(manifest(out)) - {'sha256.json'}
    for name, digest in hashes.items():
        assert sha(out / name) == digest, name
    assert BOOT.read_text().strip() == bid
    assert command('systemctl', 'is-active', 'spx-ba-fallback.timer').strip() == 'active'
    os.sync()
    out.rename(RUN / 'final-result')
    action = {'boot_id': bid, 'result_sha256': sha(RUN / 'final-result/result.json'),
              'manifest_sha256': sha(RUN / 'final-result/sha256.json'),
              'files_verified': len(hashes), 'fallback_stopped': False}
    # BA baseline never cancels recovery before the startup result and guarded return.
    (RUN / 'finalizer-action.json').write_text(json.dumps(action, indent=2) + '\n')
    os.sync()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
