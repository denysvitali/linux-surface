#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One reusable SPX functional trial: fixed kernel build, prepare/install/boot/return."""
import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import gzip
import json
import os
from pathlib import Path
import pwd
import re
import select
import shutil
import signal
import socket
import stat
import statistics
import struct
import subprocess
import time

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
HERE = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def recovery(pending=''):
    r = json.loads(RECOVERY.read_text())
    for path, digest in r['payload_sha256'].items():
        assert sha(path) == digest, path
    cfg = Path('/boot/grub/grub.cfg').read_text()
    assert r['entry'] in cfg and 'set default="spx-known-good"' in cfg
    env = dict(line.split('=', 1) for line in subprocess.check_output(
        ['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines())
    assert env['saved_entry'] == 'spx-known-good' and env.get('next_entry', '') == pending
    assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
    return r


def require_source_boot():
    """Permit preparing the next trial without a detour through recovery."""
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    if os.uname().release == '6.18.3-1-surface+':
        return
    words = Path('/proc/cmdline').read_text().split()
    assert os.uname().release == RELEASE and 'spx_boot=mainline-functional' in words
    attempts = [word.split('=', 1)[1] for word in words if word.startswith('spx_attempt=')]
    assert len(attempts) == 1 and re.fullmatch(r'[0-9]{8}[a-z0-9]+', attempts[0])
    current = json.loads((OUT.parent / attempts[0] / 'functional.json').read_text())
    assert current.get('complete') and current['boot_id'] == BOOT_ID


SENSORS_ROOT = Path('/usr/share/qcom/sc8180x/Microsoft/spx')
SENSORS_LIBEXEC = Path('/usr/local/libexec/spx-sensors')


def stage_sensors(args, out, here=HERE):
    """Stage only prebuilt userspace and the already validated board config."""
    source = args.sensors_config
    expected = dict(soc_id='340', hw_platform='CLS', revision='3.1',
                    platform_version='65536', platform_subtype_id='0',
                    platform_subtype='Unknown')
    for name, value in expected.items():
        assert (source / 'socinfo' / name).read_text().strip() == value, name
    assert (source / 'sensors/config/8180_cls_lsm6dso_display.json').is_file()
    assert not any(path.is_symlink() for path in source.rglob('*')), 'config must contain regular files'
    stage = out / 'sensors'
    stage.mkdir()
    shutil.copytree(source, stage / 'config')
    for name, path in [('hexagonrpcd', args.sensors_daemon),
                       ('libhexagonrpc.so.0.5', args.sensors_library),
                       ('ready', args.sensors_ready)]:
        assert path.is_file(), str(path)
        if name != 'libhexagonrpc.so.0.5':
            assert os.access(path, os.X_OK), str(path)
        shutil.copy2(path, stage / name)
    if args.sensors_ssc_library:
        assert args.sensors_ssc_library.is_file()
        shutil.copy2(args.sensors_ssc_library, stage / 'libssc.so.2')
    for name in ('supervise.py', 'spx-sensors.service', 'generator.py', '81-spx-sensors.rules', 'recovery.py', 'crash_test.py', 'lifecycle.py', 'spx-sensors-recovery.service'):
        shutil.copy2(here / 'sensors' / name, stage / name)


def install_sensors(stage, root=Path('/')):
    """Install fixed feature assets; do not attach on the current boot."""
    def replace_asset(source, target, mode):
        # Retained daemon executables and mapped libraries must keep their inode.
        temporary = target.with_name(target.name + '.trial-new')
        shutil.copy2(source, temporary)
        temporary.chmod(mode)
        os.replace(temporary, target)

    config = root / SENSORS_ROOT.relative_to('/')
    private = root / SENSORS_LIBEXEC.relative_to('/')
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(stage / 'config', config, dirs_exist_ok=True)
    for path in config.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    config.chmod(0o755)
    for relative, source, mode in (
            ('hexagonrpcd/hexagonrpcd', 'hexagonrpcd', 0o755),
            ('libhexagonrpc/libhexagonrpc.so.0.5', 'libhexagonrpc.so.0.5', 0o644),
            ('ready', 'ready', 0o755), ('supervise.py', 'supervise.py', 0o644),
            ('recovery.py', 'recovery.py', 0o644), ('crash_test.py', 'crash_test.py', 0o644),
            ('lifecycle.py', 'lifecycle.py', 0o644)):
        target = private / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o755)
        replace_asset(stage / source, target, mode)
    if (stage / 'libssc.so.2').is_file():
        target = private / 'libssc/libssc.so.2'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o755)
        replace_asset(stage / 'libssc.so.2', target, 0o644)
    target = root / 'etc/systemd/system/spx-sensors.service'
    target.parent.mkdir(parents=True, exist_ok=True)
    replace_asset(stage / 'spx-sensors.service', target, 0o644)
    replace_asset(stage / 'spx-sensors-recovery.service', root / 'etc/systemd/system/spx-sensors-recovery.service', 0o644)
    replace_asset(HERE / 'spx-lock', private / 'spx-lock', 0o755)
    generator = root / 'usr/lib/systemd/system-generators/spx-sensors'
    generator.parent.mkdir(parents=True, exist_ok=True)
    replace_asset(stage / 'generator.py', generator, 0o755)
    rule = root / 'etc/udev/rules.d/81-spx-sensors.rules'
    rule.parent.mkdir(parents=True, exist_ok=True)
    replace_asset(stage / '81-spx-sensors.rules', rule, 0o644)


def require_sensor_dtb(dtb):
    """Reject the old baseline before spending a boot on a missing SLPI."""
    slpi = '/remoteproc-slpi'
    rpc = slpi + '/glink-edge/fastrpc'
    for node, prop, expected in ((slpi, 'compatible', 'qcom,sc8180x-slpi-pas'),
                                 (slpi, 'firmware-name', 'qcom/microsoft/spx/qcslpi8180.mbn'),
                                 (rpc, 'compatible', 'qcom,fastrpc'), (rpc, 'label', 'sdsp')):
        found = subprocess.run(['fdtget', '-t', 's', str(dtb), node, prop],
                               capture_output=True, text=True, check=False)
        assert found.returncode == 0 and found.stdout.strip() == expected, 'sensor DTB missing ' + node + ':' + prop
        status = subprocess.check_output(['fdtget', '-t', 's', '-d', 'okay', str(dtb), node, 'status'], text=True).strip()
        assert status in ('okay', 'ok'), 'sensor DTB node disabled: ' + node
    subprocess.run(['fdtget', '-t', 'x', str(dtb), rpc, 'memory-region'], capture_output=True, check=True)


def stage_cpu_policy(args, dtb):
    """Record the actual DTB trip, including an inherited policy."""
    from thermal import PASSIVE, policy_trip, stage_policy
    if args.cpu_passive_cooling:
        stage_policy(dtb, args.cpu_passive_trip or PASSIVE)
    return policy_trip(dtb)


def prepare(args):
    os.umask(63)
    require_source_boot()
    recovery()
    if args.sensors:
        require_sensor_dtb(args.dtb)
    assert (BUILD / 'arch/arm64/boot/Image').is_file() and (BUILD / 'Module.symvers').is_file()
    OUT.mkdir(parents=True, mode=448)
    assert not (OUT / 'prepared.json').exists()
    shutil.copy2(__file__, OUT / Path(__file__).name)
    commands = []

    def run(label, args, cwd=REPO):
        with (OUT / (label + '.log')).open('xb') as stream:
            r = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        commands.append(dict(label=label, argv=args, exit_code=r.returncode))
        (OUT / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        print(json.dumps(commands[-1]), flush=True)
        assert r.returncode == 0, label
    module_root = OUT / 'module-root'
    make = ['make', '-C', str((BUILD / 'source').resolve()), 'O=' + str(BUILD), 'ARCH=arm64', 'LOCALVERSION=+']
    root = module_root / 'lib/modules' / RELEASE
    if args.reuse_installed_modules:
        # A DT/command-line-only trial must use the same modules in initramfs
        # and real root, even if the build directory has newer experiments.
        assert not args.replace_module, 'module replacement requires a fresh build staging set'
        installed = Path('/usr/lib/modules') / RELEASE
        assert installed.is_dir()
        root.parent.mkdir(parents=True)
        shutil.copytree(installed, root, symlinks=True)
    else:
        run('modules-install', make + ['-j4', 'INSTALL_MOD_PATH=' + str(module_root), 'DEPMOD=true', 'modules_install'])
    shutil.copy2(BUILD / 'arch/arm64/boot/Image', root / 'vmlinuz')
    with (OUT / 'vmlinuz').open('xb') as stream:
        with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as compressed:
            with (BUILD / 'arch/arm64/boot/Image').open('rb') as image:
                shutil.copyfileobj(image, compressed)
    shutil.copy2(BUILD / '.config', OUT / 'kernel.config')
    run('depmod', ['depmod', '-b', str(module_root), '-ae', '-F', str(BUILD / 'System.map'), RELEASE])
    assert not (OUT / 'depmod.log').read_text().strip()
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / name, OUT / name, symlinks=True)
    shutil.copy2(PARENT / 'mkinitcpio.conf', OUT / 'mkinitcpio.conf')
    for path in (OUT / 'initcpio/install/spx_diagnostics', OUT / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace(str(PARENT), str(OUT)).replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT)))
    config = OUT / 'mkinitcpio.conf'
    text = config.read_text()
    # SSAM already starts in the initramfs. Load its RTC there too so the
    # clock is initialized before root userspace, without waiting for NTP.
    assert 'MODULES=(' in text
    text = text.replace('MODULES=(', 'MODULES=(rtc_surface ', 1)
    if args.usbc:
        # Exercise deferred SSAM/DRM startup during the existing early load.
        text = text.replace('MODULES=(', 'MODULES=(surface_aggregator_usbc ', 1)
    for module in ('wcd934x', 'soundwire_qcom', 'snd_soc_wsa881x', 'snd_soc_wcd934x'):
        text = re.sub(r'\b' + module + r'\b', '', text)
    if args.sensors:
        text = text.replace('MODULES=(', 'MODULES=(fastrpc ', 1)
        stage_sensors(args, OUT)
    config.write_text(text)
    run('initramfs', ['mkinitcpio', '-k', RELEASE, '-r', str(module_root), '-c', str(OUT / 'mkinitcpio.conf'), '-D', str(OUT / 'initcpio'), '-D', '/etc/initcpio', '-D', '/usr/lib/initcpio', '-g', str(OUT / 'initramfs.img'), '--nopost'])
    run('bluetooth-address', ['/usr/bin/python3', '-B', str(REPO / 'tools/spx/bluetooth-address.py'), str(args.dtb), str(OUT / 'spx.dtb'), '--address', args.address])
    if args.pmic_rtc:
        from pmic_rtc import stage
        stage(OUT / 'spx.dtb')
    actual_cpu_trip = stage_cpu_policy(args, OUT / 'spx.dtb')
    if args.cdsp:
        from cdsp.capabilities import stage
        stage(OUT / 'spx.dtb')
    previous = json.loads((OLD / 'attempt.json').read_text())
    cmdline = []
    for word in previous['cmdline'].split():
        if word.startswith(('spx_diag=', 'spx_gpu_profile=', 'spx_diag_window=', 'qcom_scm.spx_pas_diag=', 'qcom_scm.spx_pas_area_diag=', 'venus_core.spx_hfi_startup_diag=')):
            continue
        cmdline.append(word.replace('spx_attempt=20261004bf', 'spx_attempt={ATTEMPT}'.format(ATTEMPT=ATTEMPT)).replace('spx_boot=mainline-trial', 'spx_boot=mainline-functional'))
    assert not any(('spx_uc_shared_alloc' in word for word in cmdline))
    if args.audio:
        # Both amplifier SD_N pins stay low. Power-up needs a separately
        # requested action, including a consumed-once acoustic feedback request.
        cmdline = [word for word in cmdline if not word.startswith((
            'wcd934x.spx_wsa_en_pin=', 'wcd934x.spx_wsa_gpio_',
            'soundwire_qcom.spx_force_attach=', 'snd_soc_wsa881x.spx_enumerated_mode=',
            'snd_soc_wsa881x.spx_write_only=', 'snd_soc_wcd934x.spx_persist_stream=',
            'q6asm_dai.spx_force_timer_pacing='))]
        cmdline += ['spx_audio=parked', 'wcd934x.spx_wsa_en_pin=-1',
                    'wcd934x.spx_wsa_gpio_mask=0x1e', 'wcd934x.spx_wsa_gpio_dir=0x1e',
                    'wcd934x.spx_wsa_gpio_val=0x18', 'soundwire_qcom.spx_force_attach=0',
                    'snd_soc_wsa881x.spx_enumerated_mode=1', 'snd_soc_wsa881x.spx_write_only=0',
                    'snd_soc_wcd934x.spx_persist_stream=1',
                    'q6asm_dai.spx_force_timer_pacing=0']
    else:
        cmdline.append('module_blacklist=wcd934x,soundwire_qcom,snd_soc_wsa881x,snd_soc_wcd934x')
    cmdline = [word for word in cmdline if not word.startswith('hci_uart.spx_qca_setup_trace=')]
    if args.qca_setup_trace:
        cmdline.append('hci_uart.spx_qca_setup_trace=1')
    if args.slim_s2idle_retain:
        cmdline.append('slim_qcom_ngd_ctrl.spx_s2idle_retain=1')
    if args.usbc_phy_orientation:
        assert args.usbc, '--usbc-phy-orientation requires --usbc'
        cmdline.append('surface_aggregator_usbc.phy_orientation=1')
    cmdline = [word for word in cmdline if not word.startswith(('spx_sensors=', 'spx_sensors_libssc=', 'spx_sensors_recovery=', 'spx_sensors_close_debug='))]
    if args.sensors:
        cmdline.append('spx_sensors=1')
        if args.sensors_ssc_library:
            cmdline.append('spx_sensors_libssc=private')
        if args.sensors_crash_recovery:
            cmdline.append('spx_sensors_recovery=1')
        if args.sensors_close_debug:
            cmdline.append('spx_sensors_close_debug=1')
    cmdline = [word for word in cmdline if not word.startswith('spx_cdsp=')]
    if args.cdsp:
        cmdline.append('spx_cdsp=1')
    cmdline = ' '.join(cmdline)
    entry = (OLD / 'entry.cfg').read_text().replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT))
    entry = entry.replace(previous['cmdline'].replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT)), cmdline)
    title = 'Audio startup with amplifiers parked' if args.audio else 'Bluetooth address and functional hardware tests'
    if args.cdsp:
        title = 'Surface CDSP capability-only transport'
    entry = entry.replace('bounded Venus core startup and Iris1 startup trial', title)
    (OUT / 'entry.cfg').write_text(entry)
    run('grub-syntax', ['grub-script-check', str(OUT / 'entry.cfg')])
    prepared = dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=BOOT_ID, release=RELEASE, attempt=ATTEMPT, entry='spx-trial-' + ATTEMPT, cmdline=cmdline, source_commit=subprocess.check_output(['git', '-c', 'safe.directory=' + str(REPO), 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), build_directory=str(BUILD), private_config=str(OUT / 'kernel.config'), bluetooth_address=args.address, address_is_per_installation=True, venus_trial=False, speaker_drivers_blocked=True, hardware_acceptance_closed=False, installed=False, boot_selected=False, boot_payloads=dict(vmlinuz=sha(OUT / 'vmlinuz'), initramfs=sha(OUT / 'initramfs.img'), dtb=sha(OUT / 'spx.dtb')))
    prepared.update(desktop_controls=getattr(args, 'desktop_controls', False), sensors_close_debug=args.sensors_close_debug, sensors_crash_recovery=args.sensors_crash_recovery, sensors_startup=args.sensors, sensors_private_ssc=bool(args.sensors_ssc_library), audio_mode='parked' if args.audio else 'blocked',
                    pmic_rtc=args.pmic_rtc, slim_s2idle_retain=args.slim_s2idle_retain,
                    qca_setup_trace=args.qca_setup_trace,
                    live_audio_resume=getattr(args, 'live_audio_resume', False),
                    default_mic_resume=getattr(args, 'default_mic_resume', False),
                    native_mic_resume=getattr(args, 'native_mic_resume', False),
                    cpu_passive_cooling=args.cpu_passive_cooling, cpu_passive_trip_mc=actual_cpu_trip,
                    thermal_combined=args.thermal_combined,
                    thermal_gpu_fixture=str(args.thermal_gpu_fixture),
                    thermal_cpu_stress_ng=str(args.thermal_cpu_stress_ng.resolve()) if args.thermal_cpu_stress_ng else None,
                    tpm_sign=args.tpm_sign, tpm_tools=str(args.tpm_tools.resolve()),
                    cdsp_capabilities=args.cdsp,
                    usbc_early_load=args.usbc,
                    usbc_phy_orientation=args.usbc_phy_orientation,
                    speaker_drivers_blocked=not args.audio,
                    reuse_installed_modules=args.reuse_installed_modules,
                    camera_capture=args.camera_capture,
                    replace_modules=args.replace_module)
    recovery()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    (OUT / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    print('Private functional boot prepared; no boot selected', flush=True)


def verify_retained_modules(prepared, modules):
    """Keep a module baseline only with the Image that owns that tree."""
    assert modules.is_dir() and not prepared.get('replace_modules')
    assert sha(modules / 'vmlinuz') == sha(BUILD / 'arch/arm64/boot/Image'), \
        'installed module tree belongs to a different kernel Image'
    words = Path('/proc/cmdline').read_text().split()
    if os.uname().release == RELEASE:
        current = [w.split('=', 1)[1] for w in words if w.startswith('spx_attempt=')]
        assert len(current) == 1
        previous = json.loads((OUT.parent / current[0] / 'installed.json').read_text())
        assert previous['boot_payloads']['vmlinuz'] == prepared['boot_payloads']['vmlinuz']
    else:
        assert os.uname().release == '6.18.3-1-surface+'
        assert 'spx_boot=known-good' in words


def install(args):
    os.umask(63)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    r = recovery()
    prepared = json.loads((OUT / 'prepared.json').read_text())
    assert prepared['release'] == RELEASE
    # A rebuilt Image can be prepared on the trial, then installed after
    # returning to recovery so the running module tree is never replaced.
    if prepared['preboot_id'] != BOOT_ID:
        assert os.uname().release == '6.18.3-1-surface+'
        assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
        assert not prepared.get('reuse_installed_modules')
    assert not prepared['venus_trial']
    boot = Path('/boot/spx-trial-{ATTEMPT}'.format(ATTEMPT=ATTEMPT))
    modules = Path('/usr/lib/modules') / RELEASE
    assert not boot.exists() and not (OUT / 'installed.json').exists()
    payloads = {'vmlinuz': OUT / 'vmlinuz', 'initramfs.img': OUT / 'initramfs.img', 'spx.dtb': OUT / 'spx.dtb'}
    expected = dict(zip(payloads, (prepared['boot_payloads'][k] for k in ('vmlinuz', 'initramfs', 'dtb'))))
    for name, source in payloads.items():
        assert sha(source) == expected[name]
    if prepared.get('reuse_installed_modules'):
        verify_retained_modules(prepared, modules)
    space = os.statvfs('/boot')
    assert space.f_bavail * space.f_frsize > sum((f.stat().st_size for f in payloads.values())) + 1048576
    unit_dir = Path('/etc/systemd/system')
    service = '[Unit]\nDescription=Capture mainline functional test and return to known-good\nConditionKernelCommandLine=spx_attempt=%i\nAfter=local-fs.target\nRequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -B /usr/local/lib/spx-boot-diagnostics/trial.py return %i\nTimeoutStartSec=120\n'.format(ATTEMPT=ATTEMPT)
    timer = '[Unit]\nDescription=Bounded mainline functional test return\nConditionKernelCommandLine=spx_attempt=%i\n\n[Timer]\nOnBootSec=900\nAccuracySec=1\nUnit=spx-trial-return@%i.service\n\n[Install]\nWantedBy=timers.target\n'.format(ATTEMPT=ATTEMPT)
    for name, text in [('spx-trial-return@.service', service), ('spx-trial-return@.timer', timer)]:
        target = unit_dir / name
        assert not target.exists() or target.read_text() == text
        target.write_text(text)
        target.chmod(420)
    check_service = '[Unit]\nDescription=SPX bounded functional checks\nConditionKernelCommandLine=spx_attempt=%i\nAfter=network-online.target bluetooth.service\nRequiresMountsFor=/var/lib/spx-boot-diagnostics\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -B /usr/local/lib/spx-boot-diagnostics/trial.py check %i\nTimeoutStartSec=infinity\nTimeoutStopSec=20\n'
    check_timer = '[Unit]\nDescription=Run SPX functional checks after startup\nConditionKernelCommandLine=spx_attempt=%i\n\n[Timer]\nOnBootSec=50\nAccuracySec=1\nUnit=spx-trial-check@%i.service\n\n[Install]\nWantedBy=timers.target\n'
    for name, text in [('spx-trial-check@.service', check_service), ('spx-trial-check@.timer', check_timer)]:
        target = unit_dir / name
        previous = text.replace('TimeoutStartSec=infinity\nTimeoutStopSec=20\n', 'TimeoutStartSec=180\n')
        bounded = text.replace('TimeoutStartSec=infinity\n', 'TimeoutStartSec=90000\n')
        assert not target.exists() or target.read_text() in (text, previous, bounded)
        target.write_text(text)
        target.chmod(420)
    helper = Path('/usr/local/lib/spx-boot-diagnostics/trial.py')
    shutil.copy2(__file__, helper)
    helper.chmod(493)
    # Bluetooth is fitted and checked on every functional baseline.
    shutil.copy2(HERE / 'bluetooth_power.py', helper.parent / 'bluetooth_power.py')
    (helper.parent / 'bluetooth_power.py').chmod(0o644)
    if prepared.get('cdsp_capabilities'):
        cdsp_helpers = helper.parent / 'cdsp'
        cdsp_helpers.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / 'cdsp/capabilities.py', cdsp_helpers / 'capabilities.py')
        (cdsp_helpers / 'capabilities.py').chmod(0o644)
    if prepared.get('tpm_sign'):
        tpm_helpers = helper.parent / 'tpm'
        tpm_helpers.mkdir(parents=True, exist_ok=True)
        for name in ('check.py', 'sign.py'):
            shutil.copy2(HERE / 'tpm' / name, tpm_helpers / name)
            (tpm_helpers / name).chmod(0o644)
    shutil.copy2(HERE / 'audio_stop.py', helper.parent / 'audio_stop.py')
    (helper.parent / 'audio_stop.py').chmod(0o644)
    if prepared.get('camera_capture'):
        for name in ('camera.py', 'camera_render.py'):
            shutil.copy2(HERE / name, helper.parent / name)
            (helper.parent / name).chmod(0o644)
    # The retained board DTB already contains this policy in later trials.
    shutil.copy2(HERE / 'thermal.py', helper.parent / 'thermal.py')
    if prepared.get('pmic_rtc'):
        shutil.copy2(HERE / 'pmic_rtc.py', helper.parent / 'pmic_rtc.py')
    (helper.parent / 'thermal.py').chmod(0o644)
    if prepared.get('pmic_rtc') and prepared.get('sensors_startup'):
        shutil.copy2(HERE / 'systemd_sleep.py', helper.parent / 'systemd_sleep.py')
        (helper.parent / 'systemd_sleep.py').chmod(0o644)
        shutil.copy2(HERE / 'bluetooth_resume.py', helper.parent / 'bluetooth_resume.py')
        (helper.parent / 'bluetooth_resume.py').chmod(0o644)
        if prepared.get('live_audio_resume'):
            shutil.copy2(HERE / 'audio_resume.py', helper.parent / 'audio_resume.py')
            (helper.parent / 'audio_resume.py').chmod(0o644)
    if prepared.get('sensors_startup'):
        sensor_helpers = helper.parent / 'sensors'
        sensor_helpers.mkdir(parents=True, exist_ok=True)
        for name in ('lifecycle.py', 'recovery.py', 'crash_test.py', 'supervise.py'):
            shutil.copy2(HERE / 'sensors' / name, sensor_helpers / name)
            (sensor_helpers / name).chmod(0o644)
    if prepared.get('audio_mode') == 'parked':
        from audio import UNITS as audio_units

        shutil.copy2(HERE / 'audio.py', helper.parent / 'audio.py')
        shutil.copy2(HERE / 'desktop_controls.py', helper.parent / 'desktop_controls.py')
        if (HERE / 'acoustic.py').exists():
            shutil.copy2(HERE / 'acoustic.py', helper.parent / 'acoustic.py')
        account = pwd.getpwuid(REPO.stat().st_uid)
        for name in audio_units:
            guard = Path(account.pw_dir) / '.config/systemd/user' / (name + '.d/40-mainline-audio-trial.conf')
            guard.parent.mkdir(parents=True, exist_ok=True)
            os.chown(guard.parent, account.pw_uid, account.pw_gid)
            text = (HERE / 'audio-manual.conf').read_text()
            assert not guard.exists() or guard.read_text() == text
            guard.write_text(text)
            guard.chmod(0o644)
            os.chown(guard, account.pw_uid, account.pw_gid)
    subprocess.run(['systemd-analyze', 'verify', str(unit_dir / ('spx-trial-return@' + ATTEMPT + '.service')), str(unit_dir / ('spx-trial-return@' + ATTEMPT + '.timer'))], check=True, timeout=30)
    if prepared.get('reuse_installed_modules'):
        # Also preserve the trial baseline when preparing from recovery.
        print('Keeping installed modules for the unchanged trial Image', flush=True)
    elif modules.exists() and os.uname().release == RELEASE:
        # Only explicitly named, currently blacklisted and unloaded modules may
        # be replaced while this release is running. Keep all other files.
        replacements = prepared.get('replace_modules', [])
        assert replacements, 'name the changed modules with --replace-module'
        blocked = set()
        for word in Path('/proc/cmdline').read_text().split():
            if word.startswith('module_blacklist='):
                blocked.update(name.replace('-', '_') for name in word.split('=', 1)[1].split(','))
        staged = OUT / 'module-root'
        copies = []
        for name in replacements:
            assert re.fullmatch(r'[a-zA-Z0-9_-]+', name)
            assert name.replace('-', '_') in blocked and not (Path('/sys/module') / name.replace('-', '_')).exists()
            source = Path(subprocess.check_output(['modinfo', '-b', str(staged), '-k', RELEASE, '-n', name], text=True).strip())
            target = Path(subprocess.check_output(['modinfo', '-k', RELEASE, '-n', name], text=True).strip())
            source.resolve().relative_to((staged / 'lib/modules' / RELEASE).resolve())
            target.resolve().relative_to(modules.resolve())
            copies.append((source, target))
        for source, target in copies:
            temporary = target.with_name(target.name + '.trial-new')
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        subprocess.run(['depmod', '-ae', '-F', str(BUILD / 'System.map'), RELEASE], check=True)
    elif modules.exists():
        assert os.uname().release != RELEASE
        shutil.rmtree(modules)
        shutil.copytree(OUT / 'module-root/lib/modules' / RELEASE, modules, symlinks=True)
    else:
        shutil.copytree(OUT / 'module-root/lib/modules' / RELEASE, modules, symlinks=True)
    boot.mkdir()
    for name, source in payloads.items():
        shutil.copy2(source, boot / name)
        assert sha(boot / name) == expected[name]
    shutil.copy2('/boot/grub/custom.cfg', OUT / 'previous-custom.cfg')
    shutil.copy2(OUT / 'entry.cfg', '/boot/grub/custom.cfg.trial-new')
    os.replace('/boot/grub/custom.cfg.trial-new', '/boot/grub/custom.cfg')
    subprocess.run(['grub-script-check', '/boot/grub/custom.cfg'], check=True, timeout=30)
    shutil.copy2(RECOVERY, OUT / 'working-recovery.json')
    if prepared.get('sensors_startup'):
        install_sensors(OUT / 'sensors')
        subprocess.run(['systemd-analyze', 'verify', str(unit_dir / 'spx-sensors.service')], check=True, timeout=30)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    if prepared.get('sensors_startup'):
        subprocess.run(['systemctl', 'enable', 'spx-sensors.service'], check=True)
    subprocess.run(['systemctl', 'enable', 'spx-trial-return@' + ATTEMPT + '.timer'], check=True)
    subprocess.run(['systemd-analyze', 'verify', str(unit_dir / 'spx-trial-check@.service'), str(unit_dir / 'spx-trial-check@.timer')], check=True, timeout=30)
    subprocess.run(['systemctl', 'enable', 'spx-trial-check@' + ATTEMPT + '.timer'], check=True)
    assert subprocess.check_output(['systemctl', 'is-enabled', 'spx-trial-return@' + ATTEMPT + '.timer'], text=True).strip() == 'enabled'
    recovery()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    installed = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT_ID, release=RELEASE, source_commit=subprocess.check_output(['git', '-c', 'safe.directory=' + str(REPO), 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), boot_payloads=expected, persistent_default='spx-known-good', next_entry_empty=True, return_timer_seconds=900, installed=True, boot_selected=False)
    (OUT / 'installed.json').write_text(json.dumps(installed, indent=2) + '\n')
    os.sync()
    print(ATTEMPT + ' installed with900s return; known-good default retained, no selection', flush=True)


def prepare_shutdown_ramfs():
    """Build native encrypted-root shutdown support before experimental work."""
    started = time.monotonic()
    unit = 'mkinitcpio-generate-shutdown-ramfs.service'
    subprocess.run(['systemctl', 'start', unit], check=True, timeout=60)
    state = dict(line.split('=', 1) for line in subprocess.check_output(
        ['systemctl', 'show', unit, '-p', 'Result', '-p', 'ExecMainStatus'],
        text=True, timeout=10).splitlines())
    assert state == {'Result': 'success', 'ExecMainStatus': '0'}, state
    shutdown = Path('/run/initramfs/shutdown')
    assert shutdown.is_file() and os.access(shutdown, os.X_OK), \
        'native shutdown ramdisk is not ready'
    return dict(ready=True, seconds=time.monotonic() - started,
                scope='native shutdown preparation; kernel waits remain unverified')


def boot(args):
    require_source_boot()
    assert float(Path('/proc/uptime').read_text().split()[0]) > 120
    recovery()
    prepare_shutdown_ramfs()
    installed = json.loads((OUT / 'installed.json').read_text())
    prepared = json.loads((OUT / 'prepared.json').read_text())
    selected = OUT / 'selected.json'
    assert installed['installed'] and (not selected.exists())
    for name, digest in installed['boot_payloads'].items():
        assert sha(Path('/boot/spx-trial-{ATTEMPT}'.format(ATTEMPT=ATTEMPT)) / name) == digest
    assert Path('/boot/grub/custom.cfg').read_bytes() == (OUT / 'entry.cfg').read_bytes()
    assert subprocess.check_output(['systemctl', 'is-enabled', 'spx-trial-return@' + ATTEMPT + '.timer'], text=True).strip() == 'enabled'
    assert subprocess.check_output(['git', '-c', 'safe.directory=' + str(REPO), 'status', '--porcelain', '--untracked-files=no'], cwd=REPO, text=True).strip() == ''
    # Retain the current mainline result before choosing the next trial.
    for word in Path('/proc/cmdline').read_text().split():
        if word.startswith('spx_attempt='):
            previous = OUT.parent / word.split('=', 1)[1]
            for name, extra in [('kernel.log', ['-k']), ('journal.log', [])]:
                with (previous / name).open('wb') as stream:
                    subprocess.run(['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'] + extra,
                                   stdout=stream, check=True, timeout=30)
            (previous / 'handoff.json').write_text(json.dumps(dict(
                boot_id=BOOT_ID, next_attempt=ATTEMPT,
                utc=datetime.now(timezone.utc).isoformat()), indent=2) + '\n')
    selected.write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=BOOT_ID, entry=prepared['entry'], source_commit=installed['source_commit'], select_once=True), indent=2) + '\n')
    subprocess.run(['grub-reboot', prepared['entry']], check=True)
    recovery(pending=prepared['entry'])
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    os.sync()
    subprocess.run(['systemctl', 'reboot'], check=True)


def configure_cpu_scaling():
    """Apply the mainline fragment's schedutil default to reused trial kernels."""
    assert os.geteuid() == 0
    assert 'spx_boot=mainline-functional' in Path('/proc/cmdline').read_text().split()
    policies = sorted(Path('/sys/devices/system/cpu/cpufreq').glob('policy*'))
    assert policies, 'No CPU frequency policies available'
    previous = {}
    for policy in policies:
        assert 'schedutil' in (policy / 'scaling_available_governors').read_text().split()
        previous[policy] = (policy / 'scaling_governor').read_text().strip()
    changed = []
    try:
        for policy, governor in previous.items():
            # Keep a userspace-selected policy; replace only the old kernel's
            # performance default. No frequency limits or thermal settings change.
            if governor == 'performance':
                (policy / 'scaling_governor').write_text('schedutil\n')
                changed.append(policy)
                assert (policy / 'scaling_governor').read_text().strip() == 'schedutil'
    except BaseException:
        for policy in reversed(changed):
            (policy / 'scaling_governor').write_text(previous[policy] + '\n')
        raise
    return {policy.name: dict(before=governor,
                             after=(policy / 'scaling_governor').read_text().strip())
            for policy, governor in previous.items()}


def functional_check(args):
    """Small repeatable checks; observations do not imply feature acceptance."""
    os.umask(0o077)
    words = Path('/proc/cmdline').read_text().split()
    assert 'spx_attempt=' + ATTEMPT in words
    assert 'spx_boot=mainline-functional' in words and os.uname().release == RELEASE
    result = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  release=os.uname().release, checks={}, observations={})
    target = OUT / 'functional.json'

    def save():
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        os.replace(temporary, target)

    def run(name, argv, timeout=15):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            result['checks'][name] = dict(returncode=proc.returncode,
                                          stdout=proc.stdout, stderr=proc.stderr)
        except (OSError, subprocess.TimeoutExpired) as error:
            result['checks'][name] = dict(error=str(error))
        save()

    save()
    result['checks']['shutdown-ramfs'] = prepare_shutdown_ramfs()
    save()
    result['checks']['cpu-frequency-policy'] = configure_cpu_scaling()
    save()
    for pattern in ('class/power_supply/*/uevent', 'class/thermal/thermal_zone*/type',
                    'class/thermal/thermal_zone*/temp', 'class/remoteproc/remoteproc*/name',
                    'class/remoteproc/remoteproc*/state', 'bus/iio/devices/iio:device*/name',
                    'bus/iio/devices/iio:device*/in_illuminance_raw',
                    'bus/iio/devices/iio:device*/in_intensity_[xyz]_raw',
                    'bus/iio/devices/iio:device*/in_intensity_ir_raw',
                    'bus/iio/devices/iio:device*/in_proximity_raw'):
        for path in Path('/sys').glob(pattern):
            try:
                result['observations'][str(path)] = path.read_text().strip()
            except OSError as error:
                result['observations'][str(path)] = str(error)
    save()
    for module in ('rfcomm', 'hidp', 'uhid'):
        run('module-' + module, ['modprobe', module])
    try:
        with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM):
            result['checks']['rfcomm-socket'] = dict(opened=True)
    except OSError as error:
        result['checks']['rfcomm-socket'] = dict(opened=False, error=str(error))
    try:
        fd = os.open('/dev/uhid', os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)
        result['checks']['uhid-open'] = dict(opened=True)
    except OSError as error:
        result['checks']['uhid-open'] = dict(opened=False, error=str(error))
    save()
    run('bluetooth-controller', ['bluetoothctl', 'show'])
    run('wifi-link', ['iw', 'dev', 'wlan0', 'link'])
    run('wifi-transfer', ['curl', '--interface', 'wlan0', '-4', '--fail', '--silent',
                         '--show-error', '--max-time', '45', '-o', '/dev/null',
                         '-w', 'bytes=%{size_download} seconds=%{time_total} bytes_per_second=%{speed_download}\n',
                         'https://speed.cloudflare.com/__down?bytes=25000000'], timeout=50)
    run('kernel-log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'])
    result['complete'] = True
    save()


def wifi_band_gate():
    """Reject recovery, unfinished boots and expiring return timers before mutation."""
    assert os.geteuid() == 0 and os.uname().release == RELEASE
    assert RELEASE == '7.3.0-rc2-spx-mainline-20261004bg+'
    words = Path('/proc/cmdline').read_text().split()
    assert [w for w in words if w.startswith('spx_attempt=')] == ['spx_attempt=' + ATTEMPT]
    assert 'spx_boot=mainline-functional' in words
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    checked = json.loads((OUT / 'functional.json').read_text())
    assert checked.get('complete') and checked['boot_id'] == boot
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    assert 90 <= uptime <= 600
    unit = 'spx-trial-return@' + ATTEMPT + '.timer'
    assert subprocess.check_output(['systemctl', 'is-active', unit], text=True, timeout=5).strip() == 'active'
    value = subprocess.check_output(['systemctl', 'show', unit, '-p',
                                    'NextElapseUSecMonotonic', '--value'], text=True, timeout=5).strip()
    units = {'us': 1e-6, 'ms': .001, 's': 1, 'min': 60, 'h': 3600, 'd': 86400}
    parts = re.findall(r'([0-9]+(?:\.[0-9]+)?)(us|ms|min|s|h|d)', value)
    assert parts and re.sub(r'([0-9]+(?:\.[0-9]+)?)(us|ms|min|s|h|d)|\s+', '', value) == '', value
    expires = sum(float(n) * units[u] for n, u in parts)
    # Reserve the 135-second test budget plus restoration, logs and lock cleanup.
    assert expires - time.clock_gettime(time.CLOCK_MONOTONIC) >= 200, 'return timer too close'
    return boot


def wifi_band(args):
    """Two bounded 2.4 GHz downloads using an owned temporary saved-profile clone."""
    os.umask(0o077)
    boot = wifi_band_gate()
    assert args.wifi_profile, '--wifi-profile requires an existing saved profile ID'
    output = OUT / 'wifi-band'
    owner = 'wifi-' + ATTEMPT
    lock = str(REPO / 'tools/spx/spx-lock')
    subprocess.run([lock, 'acquire', 'device', owner], check=True, timeout=5)
    result = dict(boot_id=boot, release=RELEASE, source_profile=args.wifi_profile,
                  links=[], transfers=[], restoration={}, complete=False)
    target = output / 'result.json'
    original = None
    clone_name = 'spx-wifi-band-' + ATTEMPT
    clone_uuid = None
    clone_attempted = False
    claimed = False
    handlers = {}
    start = float(Path('/proc/uptime').read_text().split()[0])
    deadline = time.monotonic() + 135

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')

    def command(argv, timeout=10, cleanup=False):
        if not cleanup:
            timeout = min(timeout, deadline - time.monotonic())
            assert timeout > 0, 'Wi-Fi test deadline expired'
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    def nm(*argv, timeout=10, cleanup=False):
        proc = command(['nmcli', '--wait', str(min(30, int(timeout))), *argv], timeout + 2, cleanup)
        assert proc.returncode == 0, 'nmcli failed: ' + proc.stderr.strip()
        return proc.stdout.strip()

    def link(phase):
        proc = command(['iw', 'dev', 'wlan0', 'link'])
        entry = dict(phase=phase, returncode=proc.returncode, link=proc.stdout.strip())
        result['links'].append(entry)
        save()
        match = re.search(r'^\s*freq:\s*(\d+(?:\.\d+)?)\s*$', proc.stdout, re.M)
        assert proc.returncode == 0 and match and 2400 <= float(match[1]) <= 2500, 'not associated on 2.4 GHz'
        entry['frequency_mhz'] = float(match[1])

    def interrupted(signum, frame):
        raise RuntimeError('Wi-Fi test interrupted by signal ' + str(signum))

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, interrupted)
        # Recheck after acquiring exclusive access; all gates precede any NM change.
        assert wifi_band_gate() == boot
        fields = nm('--escape', 'no', '-g', 'connection.uuid,connection.type,802-11-wireless.ssid',
                    'connection', 'show', 'id', args.wifi_profile).splitlines()
        assert len(fields) == 3 and fields[1] == '802-11-wireless'
        source_uuid, _, ssid = fields
        original = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', 'wlan0')
        assert re.fullmatch(r'[0-9a-fA-F-]{36}', original), 'wlan0 has no saved active UUID'
        result.update(source_uuid=source_uuid, ssid=ssid, original_uuid=original)
        scan = nm('--escape', 'no', '-t', '-f', 'SSID,FREQ', 'device', 'wifi', 'list',
                  'ifname', 'wlan0', '--rescan', 'no')
        visible = [line.rsplit(':', 1) for line in scan.splitlines() if ':' in line]
        assert any(name == ssid and re.fullmatch(r'\d+(?: MHz)?', freq) and
                   2400 <= int(freq.split()[0]) <= 2500 for name, freq in visible), 'saved SSID not visible on 2.4 GHz'
        assert not nm('-g', 'NAME', 'connection', 'show').splitlines().count(clone_name), 'clone ID already exists'
        output.mkdir(mode=0o700, exist_ok=True)
        # Exclusive creation consumes the attempt before cloning or association.
        with target.open('x') as stream:
            stream.write(json.dumps(result) + '\n')
        claimed = True
        clone_attempted = True
        nm('connection', 'clone', '--temporary', 'uuid', source_uuid, clone_name)
        clone_uuid = nm('-g', 'connection.uuid', 'connection', 'show', 'id', clone_name)
        result['clone_uuid'] = clone_uuid
        nm('connection', 'modify', '--temporary', 'uuid', clone_uuid,
           '802-11-wireless.band', 'bg', 'connection.autoconnect', 'no',
           'connection.interface-name', 'wlan0')
        nm('connection', 'up', 'uuid', clone_uuid, 'ifname', 'wlan0', timeout=30)
        for index in (1, 2):
            link('before-' + str(index))
            proc = command(['curl', '--interface', 'wlan0', '-4', '--fail', '--silent',
                            '--show-error', '--max-time', '45', '-o', '/dev/null', '-w',
                            '%{size_download} %{time_total} %{speed_download}',
                            'https://speed.cloudflare.com/__down?bytes=25000000'], timeout=47)
            transfer = dict(index=index, returncode=proc.returncode,
                            summary=proc.stdout.strip(), error=proc.stderr.strip())
            result['transfers'].append(transfer)
            save()
            link('after-' + str(index))
            stats = proc.stdout.split()
            assert proc.returncode == 0 and len(stats) == 3 and float(stats[0]) == 25000000, 'incomplete HTTPS transfer'
            transfer.update(bytes=int(float(stats[0])), seconds=float(stats[1]), bytes_per_second=float(stats[2]))
        result['data_passed'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        try:
            for signum in handlers:
                signal.signal(signum, signal.SIG_IGN)
            if clone_attempted:
                try:
                    nm('connection', 'up', 'uuid', original, 'ifname', 'wlan0', timeout=30, cleanup=True)
                    active = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', 'wlan0', timeout=3, cleanup=True)
                    result['restoration']['original_active'] = active == original
                    assert active == original, 'original UUID was not restored'
                except Exception as error:
                    result['restoration']['error'] = str(error)
                try:
                    # ID is owned by this invocation even if clone UUID lookup failed.
                    nm('connection', 'delete', 'id', clone_name, timeout=3, cleanup=True)
                    result['restoration']['clone_deleted'] = True
                except Exception as error:
                    result['restoration']['delete_error'] = str(error)
            if claimed:
                try:
                    proc = command(['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], timeout=5, cleanup=True)
                    lines = [line for line in proc.stdout.splitlines()
                             if (stamp := re.match(r'\[\s*([0-9.]+)\]', line)) and float(stamp[1]) >= start]
                    (output / 'kernel.log').write_text('\n'.join(lines) + '\n')
                    result['new_kernel_faults'] = [line for line in lines if re.search(
                        r'(?i)(ath10k.*(?:fail|error|crash|timeout)|firmware crashed|BUG:|Oops:|Call trace:)', line)]
                    result['kernel_log_exit'] = proc.returncode
                except Exception as error:
                    result['kernel_log_error'] = str(error)
                result['complete'] = bool(result.get('data_passed') and
                    result['restoration'].get('original_active') and result['restoration'].get('clone_deleted') and
                    result.get('kernel_log_exit') == 0 and not result.get('new_kernel_faults'))
                save()
        finally:
            try:
                subprocess.run([lock, 'release', 'device', owner], check=True, timeout=5)
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
    print(json.dumps(result), flush=True)


def power_sample(root=Path('/sys')):
    """Read numeric telemetry only; fail closed without battery/mains/thermal data."""
    supplies = list((root / 'class/power_supply').iterdir())
    batteries = [p for p in supplies if (p / 'type').read_text().strip() == 'Battery']
    mains = [p for p in supplies if (p / 'online').exists()]
    assert len(batteries) == 1 and mains, 'missing power telemetry'
    assert all(int((p / 'online').read_text()) == 0 for p in mains), 'external power online'
    battery = batteries[0]
    assert (battery / 'status').read_text().strip() == 'Discharging', 'battery not discharging'
    values = {k: int((battery / k).read_text()) for k in
              ('capacity', 'voltage_now', 'power_now', 'energy_now')}
    assert 20 <= values['capacity'] <= 100, 'battery below 20 percent or invalid'
    assert all(values[k] > 0 for k in ('voltage_now', 'power_now', 'energy_now')), 'invalid battery telemetry'
    values['thermal_mc'] = [int(p.read_text()) for p in sorted((root / 'class/thermal').glob('thermal_zone*/temp'))]
    assert values['thermal_mc'] and all(-40000 <= t < 75000 for t in values['thermal_mc']), 'thermal stop or invalid telemetry'
    policies = sorted((root / 'devices/system/cpu/cpufreq').glob('policy*'))
    values['frequency_khz'] = [int((p / 'scaling_cur_freq').read_text()) for p in policies]
    assert policies and all(f > 0 for f in values['frequency_khz']), 'missing CPU telemetry'
    return values


def power_measure(args):
    """Bounded idle/load/recovery measurement; never change power controls."""
    os.umask(0o077)
    boot = wifi_band_gate()
    owner, lock = 'power-' + ATTEMPT, str(REPO / 'tools/spx/spx-lock')
    target = OUT / 'power-measure/result.json'
    result = dict(attempt=ATTEMPT, boot_id=boot, release=RELEASE, phases={}, complete=False)
    workers, handlers, claimed = [], {}, False

    def stop():
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=2)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=2)
        workers.clear()

    def interrupted(signum, frame):
        raise RuntimeError('measurement interrupted')

    subprocess.run([lock, 'acquire', 'device', owner], check=True, timeout=5)
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, interrupted)
        assert wifi_band_gate() == boot
        power_sample()  # Refuse low charge or missing data before creating any worker.
        policies = sorted(Path('/sys/devices/system/cpu/cpufreq').glob('policy*'))
        cpus = [int((p / 'affected_cpus').read_text().split()[0]) for p in policies]
        assert cpus and len(set(cpus)) == len(cpus), 'missing CPU policies'
        target.parent.mkdir(mode=0o700, exist_ok=True)
        with target.open('x') as stream:
            json.dump(result, stream)
        claimed = True
        started = time.monotonic()
        for phase in ('idle', 'load', 'recovery'):
            power_sample()  # Recheck immediately before starting load.
            if phase == 'load':
                for cpu in cpus:
                    code = ('import os,time; os.nice(19); os.sched_setaffinity(0,{' + str(cpu) +
                            '}); end=time.monotonic()+32\nwhile time.monotonic()<end: sum(range(10000))')
                    workers.append(subprocess.Popen(['/usr/bin/python3', '-c', code],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            begin = time.monotonic()
            rows = []
            result['phases'][phase] = dict(samples=rows)
            for index in range(16):
                time.sleep(max(0, begin + index * 2 - time.monotonic()))
                assert time.monotonic() - started < 135, 'measurement deadline expired'
                assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot, 'boot changed'
                sample = power_sample()
                sample.update(seconds=time.monotonic() - started, phase_seconds=time.monotonic() - begin)
                rows.append(sample)
                assert not workers or all(w.poll() is None for w in workers), 'CPU worker exited early'
            if phase == 'load':
                stop()
            result['phases'][phase].update(
                median_watts=statistics.median(r['power_now'] / 1e6 for r in rows if r['phase_seconds'] >= 15),
                energy_delta_uwh=rows[0]['energy_now'] - rows[-1]['energy_now'])
        result['complete'] = True
    except Exception as error:
        # Never persist exception text containing battery paths or identities.
        result['failure'] = str(error) if isinstance(error, AssertionError) else type(error).__name__
    finally:
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            stop()  # Reap workers before result writes or lock release, including failed samples.
            if claimed:
                target.write_text(json.dumps(result, indent=2) + '\n')
        finally:
            try:
                subprocess.run([lock, 'release', 'device', owner], check=True, timeout=5)
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
    print(json.dumps(result), flush=True)
    assert result['complete'], result.get('failure', 'incomplete measurement')


def display_power(args):
    """Exercise ordinary GNOME display power, with actual off and restored scanout."""
    os.umask(0o077)
    boot = wifi_band_gate()  # Same completed-boot and return-window prerequisites.
    output = OUT / 'display-power'
    target = output / 'result.json'
    owner, lock = 'display-' + ATTEMPT, str(REPO / 'tools/spx/spx-lock')
    account = pwd.getpwuid(REPO.stat().st_uid)
    assert account.pw_uid != 0 and account.pw_name == args.desktop_user
    bus = ['runuser', '-u', account.pw_name, '--', 'env',
           'XDG_RUNTIME_DIR=/run/user/' + str(account.pw_uid),
           'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/' + str(account.pw_uid) + '/bus',
           'busctl', '--user', '--timeout=5']
    interface = ['org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                 'org.gnome.Mutter.DisplayConfig', 'PowerSaveMode']
    subprocess.run([lock, 'acquire', 'device', owner], check=True, timeout=5)
    result = dict(boot_id=boot, release=RELEASE, snapshots={}, complete=False)
    claimed, changed, handlers = False, False, {}
    start = float(Path('/proc/uptime').read_text().split()[0])
    result['start_uptime'] = start

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')

    def mode(value=None):
        argv = bus + (['get-property'] + interface if value is None else
                      ['set-property'] + interface + ['i', str(value)])
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=7)
        assert proc.returncode == 0, 'desktop power request failed: ' + proc.stderr.strip()
        return proc.stdout.strip()

    def snapshot(name):
        text = state.read_text()
        (output / (name + '-drm-state.txt')).write_text(text)
        blocks = re.split(r'(?=^(?:plane|crtc|connector)\[)', text, flags=re.M)
        crtcs, connectors, framebuffers = {}, {}, {}
        for block in blocks:
            if match := re.match(r'crtc\[\d+\]: crtc-(\d+)\n', block):
                crtcs[match[1]] = dict(re.findall(r'^\t(enable|active)=(\d+)$', block, re.M))
                crtcs[match[1]]['mode'] = re.search(r'^\tmode: (.+)$', block, re.M)[1]
            elif match := re.match(r'connector\[\d+\]: ([^\n]+)\n\tcrtc=crtc-(\d+)', block):
                connectors[match[1]] = match[2]
            elif match := re.match(r'plane\[\d+\]: [^\n]+\n\tcrtc=crtc-(\d+)\n\tfb=(\d+)', block):
                if int(match[2]) and '\t\tallocated by = gnome-shell\n' in block:
                    framebuffers[match[1]] = int(match[2])
        snap = dict(power_mode=mode(), crtcs=crtcs, connectors=connectors, framebuffers=framebuffers)
        result['snapshots'][name] = snap
        return snap

    def settled(name, on):
        deadline = time.monotonic() + 10
        while True:
            snap = snapshot(name)
            okay = (all(snap['crtcs'][c]['active'] == '0' and snap['crtcs'][c]['enable'] == '0'
                        for c in active.values()) if not on else
                    all(snap['connectors'].get(n) == c and snap['crtcs'][c]['active'] == '1' and
                        snap['crtcs'][c]['enable'] == '1' and c in snap['framebuffers'] and
                        snap['crtcs'][c]['mode'] == before['crtcs'][c]['mode'] for n, c in active.items()))
            if okay and snap['power_mode'] == ('i 0' if on else 'i 3'):
                break
            assert time.monotonic() < deadline, 'DRM display state did not settle: ' + name
            time.sleep(.25)
        if on:
            fd = os.open('/dev/dri/' + card, os.O_RDWR | os.O_CLOEXEC)
            try:
                snap['vblank'] = {}
                for c in sorted(set(active.values())):
                    rows = []
                    for _ in range(2):
                        buf = bytearray(struct.pack('=IIQQ', 1 | (int(c) << 1), 1, 0, 0))
                        fcntl.ioctl(fd, 0xc018643a, buf, True)
                        _, sequence, seconds, useconds = struct.unpack('=IIqq', buf)
                        rows.append(dict(sequence=sequence, timestamp=seconds + useconds / 1e6))
                    snap['vblank'][c] = rows
                    assert 0 < ((rows[1]['sequence'] - rows[0]['sequence']) & 0xffffffff)
                    assert rows[1]['timestamp'] > rows[0]['timestamp'], 'stale vblank timestamp'
            finally:
                os.close(fd)
        save()

    def interrupted(signum, frame):
        raise RuntimeError('interrupted by signal ' + str(signum))

    try:
        wifi_band_gate()
        assert mode() == 'i 0', 'desktop must start powered on'
        edps = list(Path('/sys/class/drm').glob('card*-eDP-1'))
        assert len(edps) == 1
        card = edps[0].name.split('-', 1)[0]
        state = Path('/sys/kernel/debug/dri') / card[4:] / 'state'
        output.mkdir(mode=0o700, exist_ok=True)
        with target.open('x') as handle:
            json.dump(result, handle)
        claimed = True
        before = snapshot('before')
        active = {n: c for n, c in before['connectors'].items()
                  if before['crtcs'][c]['active'] == before['crtcs'][c]['enable'] == '1'}
        result['original_active_connectors'] = active
        assert 'eDP-1' in active and active['eDP-1'] in before['framebuffers']
        assert '"2880x1920"' in before['crtcs'][active['eDP-1']]['mode']
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, interrupted)
        settled('before', True)
        for cycle in (1, 2):
            changed = True
            mode(3)
            settled('off-' + str(cycle), False)
            time.sleep(3)
            mode(0)
            settled('on-' + str(cycle), True)
        result['cycles_passed'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            if changed:
                try:
                    mode(0)
                    settled('finally-restored', True)
                    result['restored'] = True
                except Exception as error:
                    result['restoration_error'] = str(error)
            if claimed:
                try:
                    proc = subprocess.run(['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'],
                                          capture_output=True, text=True, timeout=7)
                    lines = [line for line in proc.stdout.splitlines()
                             if (stamp := re.match(r'\[\s*([0-9.]+)\]', line)) and float(stamp[1]) >= start]
                    (output / 'kernel.log').write_text('\n'.join(lines) + '\n')
                    result['new_kernel_faults'] = [line for line in lines if re.search(
                        r'(?i)((?:dpu|drm|dp_display|panel|aux).*(?:error|fail|timeout)|BUG:|Oops:|Call trace:)', line)]
                    result['complete'] = bool(result.get('cycles_passed') and result.get('restored') and
                                              proc.returncode == 0 and not result['new_kernel_faults'])
                except Exception as error:
                    result['kernel_log_error'] = str(error)
                save()
        finally:
            subprocess.run([lock, 'release', 'device', owner], check=True, timeout=5)
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
    print(json.dumps(result), flush=True)


def srtc_timer(args):
    """Verify the documented SQ2 AC/DC timer countdown without suspending."""
    os.umask(0o077)
    assert os.geteuid() == 0
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if os.uname().release != '6.18.3-1-surface+':
        assert os.uname().release == RELEASE
        assert 'spx_attempt=' + ATTEMPT in Path('/proc/cmdline').read_text().split()
        checked = json.loads((OUT / 'functional.json').read_text())
        assert checked.get('complete') and checked['boot_id'] == boot
        timer = 'spx-trial-return@' + ATTEMPT + '.timer'
        assert subprocess.check_output(['systemctl', 'is-active', timer], text=True).strip() == 'active'
        value = subprocess.check_output(['systemctl', 'show', timer, '-p',
            'NextElapseUSecMonotonic', '--value'], text=True).strip()
        units = {'us': 1e-6, 'ms': .001, 's': 1, 'min': 60, 'h': 3600, 'd': 86400}
        parts = re.findall(r'([0-9]+(?:\.[0-9]+)?)(us|ms|min|s|h|d)', value)
        assert parts and not re.sub(r'([0-9]+(?:\.[0-9]+)?)(us|ms|min|s|h|d)|\s+', '', value)
        deadline = sum(float(n) * units[u] for n, u in parts)
        assert time.clock_gettime(time.CLOCK_MONOTONIC) + 60 < deadline
    recovery()

    base = (Path('/var/lib/spx-boot-diagnostics/attempts') if
            os.uname().release == '6.18.3-1-surface+' else OUT.parent)
    assert not args.srtc_queue_events or args.srtc_observe_expiry
    assert not args.srtc_observe_irq or args.srtc_queue_events
    assert not args.srtc_d0_notify or args.srtc_observe_irq
    label = 'srtc-d0-expiry' if args.srtc_d0_notify else ('srtc-irq-expiry' if args.srtc_observe_irq else ('srtc-queued-expiry' if args.srtc_queue_events else (
        'srtc-expiry' if args.srtc_observe_expiry else 'srtc-timer')
    ))
    output = base / ATTEMPT / label
    output.mkdir(parents=True, mode=0o700)
    target = output / 'result.json'
    owner, lock = 'srtc-' + ATTEMPT, str(REPO / 'tools/spx/spx-lock')
    subprocess.run([lock, 'acquire', 'device', owner], check=True, timeout=5)
    result = dict(boot_id=boot, release=os.uname().release, command='srtc-timer',
                  controller='/dev/surface/aggregator', before={}, after={},
                  complete=False, suspended=False)
    armed = False
    queued = False
    d0_exited = False
    loaded_here = False
    irq_observer_owned = False

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')

    def request(fd, command, payload, response_size=4):
        payload_buf = ctypes.create_string_buffer(payload) if payload else None
        response_buf = ctypes.create_string_buffer(response_size)
        payload_ptr = ctypes.addressof(payload_buf) if payload_buf else 0
        response_ptr = ctypes.addressof(response_buf)
        header = bytearray(struct.pack('=BBBBHhQH6xQH6x', 1, 1, command, 0, 1, 0,
                                       payload_ptr, len(payload), response_ptr, response_size))
        assert len(header) == 40
        ioctl = (3 << 30) | (len(header) << 16) | (0xA5 << 8) | 1
        fcntl.ioctl(fd, ioctl, header, True)
        fields = struct.unpack('=BBBBHhQH6xQH6x', header)
        assert fields[5] == 0, 'SSAM transport status: ' + str(fields[5])
        assert fields[9] == response_size, 'unexpected SSAM response size'
        return int.from_bytes(response_buf.raw, 'little')

    def timer_read(fd, timer_id):
        return request(fd, 0x1D, struct.pack('<I', timer_id))

    def timer_set(fd, timer_id, seconds):
        status = request(fd, 0x1A, struct.pack('<II', timer_id, seconds))
        assert status == 0, 'firmware rejected timer update with status ' + hex(status)

    try:
        if not Path('/sys/module/surface_aggregator_cdev').exists():
            subprocess.run(['modprobe', 'surface_aggregator_cdev'], check=True, timeout=10)
            loaded_here = True
        device = Path('/dev/surface/aggregator')
        assert device.exists(), 'SSAM cdev device was not created'
        if args.srtc_observe_irq:
            assert not Path('/sys/module/irq_observer').exists(), 'IRQ observer already owned'
            lines = [line for line in Path('/proc/interrupts').read_text().splitlines()
                     if line.rstrip().endswith('ssam_wakeup')]
            assert len(lines) == 1, 'expected exactly one SSAM wake IRQ'
            irq = int(lines[0].split(':')[0])
            irq_observer_owned = True
            subprocess.run(['insmod', str(HERE / 'srtc/irq_observer.ko'), 'irq=' + str(irq)],
                           check=True, timeout=10)
            result['awake_irq_observer'] = irq

        mains = [p for p in Path('/sys/class/power_supply').glob('*')
                 if (p / 'type').exists() and (p / 'type').read_text().strip() == 'Mains']
        assert mains, 'could not identify AC/DC power source'
        online = any((p / 'online').exists() and (p / 'online').read_text().strip() == '1'
                     for p in mains)
        selected = 0 if online else 1
        result.update(power_source='AC' if online else 'DC', selected_timer=selected,
                      duration_seconds=30, cdev_loaded_here=loaded_here)

        with device.open('rb', buffering=0) as stream:
            fd = stream.fileno()
            if args.srtc_observe_expiry:
                # Software-only observer: no firmware event-enable or wake change.
                notifier = struct.pack('=iB', 0, 1)
                fcntl.ioctl(fd, (1 << 30) | (5 << 16) | (0xA5 << 8) | 2, notifier)
                result['observed_events'] = []
                result['wake_irq_before'] = [line.strip() for line in
                    Path('/proc/interrupts').read_text().splitlines() if 'ssam_wakeup' in line]
            values = {timer_id: timer_read(fd, timer_id) for timer_id in (0, 1)}
            result['before'] = {str(k): v for k, v in values.items()}
            save()
            assert values[selected] == 0xFFFFFFFF, (
                'selected timer is already active; left both firmware timers untouched')
            if args.srtc_queue_events:
                queued = True
                result['display_off_reply'] = request(fd, 0x15, b'', 1)

            armed = True  # Set before the request so cleanup also covers an uncertain reply.
            started = time.monotonic()
            timer_set(fd, selected, 30)
            first = timer_read(fd, selected)
            result['armed_remaining_seconds'] = first
            assert 1 <= first <= 30, 'firmware did not report the requested countdown'
            time.sleep(4)
            second = timer_read(fd, selected)
            result['later_remaining_seconds'] = second
            result['elapsed_seconds'] = 4
            assert 0 <= second < first, 'firmware countdown did not decrease'
            result['countdown_passed'] = True
            if args.srtc_observe_expiry:
                if args.srtc_d0_notify:
                    d0_exited = True
                    result['d0_exit_reply'] = request(fd, 0x33, b'', 1)
                while time.monotonic() < started + 32:
                    ready, _, _ = select.select([fd], [], [], max(0, min(1, started + 32 - time.monotonic())))
                    if ready:
                        data = os.read(fd, 4096)
                        offset = 0
                        while offset < len(data):
                            assert len(data) - offset >= 6, 'short SSAM event header'
                            tc, tid, cid, iid, length = struct.unpack_from('=BBBBH', data, offset)
                            offset += 6
                            assert offset + length <= len(data), 'short SSAM event payload'
                            result['observed_events'].append(dict(category=tc, target=tid,
                                command=cid, instance=iid, payload=data[offset:offset+length].hex(),
                                elapsed_seconds=time.monotonic()-started))
                            offset += length
                result['wake_irq_after'] = [line.strip() for line in
                    Path('/proc/interrupts').read_text().splitlines() if 'ssam_wakeup' in line]
                if d0_exited:
                    result['d0_entry_reply'] = request(fd, 0x34, b'', 1)
                    d0_exited = False
                    result['d0_restored'] = True
                result['expiry_remaining_seconds'] = timer_read(fd, selected)
                result['expiry_elapsed_seconds'] = time.monotonic() - started
                if queued:
                    result['display_on_reply'] = request(fd, 0x16, b'', 1)
                    queued = False
                    result['display_on_restored'] = True
    except Exception as error:
        result['error'] = repr(error)
    finally:
        try:
            if d0_exited:
                try:
                    with Path('/dev/surface/aggregator').open('rb', buffering=0) as stream:
                        result['cleanup_d0_entry_reply'] = request(stream.fileno(), 0x34, b'', 1)
                    d0_exited = False
                    result['d0_restored'] = True
                except Exception as error:
                    result['cleanup_error'] = 'D0 restoration: ' + repr(error)
            if queued:
                try:
                    with Path('/dev/surface/aggregator').open('rb', buffering=0) as stream:
                        result['cleanup_display_on_reply'] = request(stream.fileno(), 0x16, b'', 1)
                    queued = False
                    result['display_on_restored'] = True
                except Exception as error:
                    result['cleanup_error'] = 'display-on restoration: ' + repr(error)
            if armed:
                try:
                    device = Path('/dev/surface/aggregator')
                    with device.open('rb', buffering=0) as stream:
                        timer_set(stream.fileno(), selected, 0xFFFFFFFF)
                        restored = timer_read(stream.fileno(), selected)
                        final_values = {timer_id: timer_read(stream.fileno(), timer_id)
                                        for timer_id in (0, 1)}
                    result['cleanup_disabled_value'] = restored
                    result['after'] = {str(k): v for k, v in final_values.items()}
                    result['cleanup_passed'] = restored == 0xFFFFFFFF
                    if not result['cleanup_passed']:
                        result['cleanup_error'] = 'timer remained active after disable'
                except Exception as error:
                    result['cleanup_error'] = repr(error)
            if irq_observer_owned and Path('/sys/module/irq_observer').exists():
                try:
                    subprocess.run(['rmmod', 'irq_observer'], check=True, timeout=10)
                    result['awake_irq_observer_unloaded'] = True
                except Exception as error:
                    result['cleanup_error'] = 'IRQ observer unload: ' + repr(error)
            if loaded_here:
                subprocess.run(['modprobe', '-r', 'surface_aggregator_cdev'],
                               check=True, timeout=10)
                result['cdev_unloaded'] = True
        except Exception as error:
            result['cleanup_error'] = repr(error)
        result['complete'] = bool(result.get('countdown_passed') and
                                  result.get('cleanup_passed') and not result.get('error') and
                                  not result.get('cleanup_error') and
                                  (not loaded_here or result.get('cdev_unloaded')))
        save()
        subprocess.run([lock, 'release', 'device', owner], check=True, timeout=5)
    print(json.dumps(result), flush=True)


def usbc_reload(args):
    """Restart only the USC subscriber; observe the attached display path."""
    assert os.geteuid() == 0 and os.uname().release == RELEASE
    assert 'spx_attempt=' + ATTEMPT in Path('/proc/cmdline').read_text().split()
    assert 'spx_boot=mainline-functional' in Path('/proc/cmdline').read_text().split()
    assert 90 <= float(Path('/proc/uptime').read_text().split()[0]) <= 750
    assert subprocess.check_output(['systemctl', 'is-active',
                                   'spx-trial-return@' + ATTEMPT + '.timer'],
                                   text=True).strip() == 'active'
    output = OUT / 'usb-c'
    output.mkdir(mode=0o700, exist_ok=True)
    target = output / 'reload.json'
    assert not target.exists(), 'one subscriber restart per trial'
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'usbc-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    result = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  release=RELEASE, steps={}, snapshots={}, complete=False)
    module = Path('/sys/module/surface_aggregator_usbc')
    removed = False

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')

    def run(name, argv):
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        result['steps'][name] = dict(returncode=proc.returncode,
                                    stdout=proc.stdout, stderr=proc.stderr)
        save()
        return proc.returncode == 0

    def snapshot(name):
        dp = list(Path('/sys/class/drm').glob('card*-DP-1'))
        assert len(dp) == 1, 'expected one primary external connector'
        card = dp[0].name.split('-', 1)[0]
        edp = dp[0].with_name(card + '-eDP-1')
        state = (Path('/sys/kernel/debug/dri') / card[4:] / 'state').read_text()
        (output / (name + '-drm-state.txt')).write_text(state)
        match = re.search(r'connector\[\d+\]: DP-1\n\s+crtc=crtc-(\d+)', state)
        assert match, 'external connector has no CRTC'
        values = dict(forwarder_bound=Path(
            '/sys/bus/platform/devices/surface_aggregator_usbc/driver').exists(),
            dp_status=(dp[0] / 'status').read_text().strip(),
            dp_enabled=(dp[0] / 'enabled').read_text().strip(),
            edp_status=(edp / 'status').read_text().strip(),
            edp_enabled=(edp / 'enabled').read_text().strip())
        edid = (dp[0] / 'edid').read_bytes()
        values['edid_valid'] = (len(edid) >= 128 and len(edid) % 128 == 0 and
                               edid[:8] == bytes.fromhex('00ffffffffffff00') and
                               all(sum(edid[i:i + 128]) % 256 == 0
                                   for i in range(0, len(edid), 128)))
        fd = os.open('/dev/dri/' + card, os.O_RDWR | os.O_CLOEXEC)
        try:
            replies = []
            # Standard WAIT_VBLANK: relative sequence, selected CRTC index.
            # DRM bounds the blocking wait; no modeset or framebuffer change.
            # Wait for both samples: a zero-relative query can return an old
            # timestamp when vblank IRQs were idle between compositor frames.
            for delta in (1, 1):
                buf = bytearray(struct.pack('=IIQQ', 1 | (int(match[1]) << 1), delta, 0, 0))
                fcntl.ioctl(fd, 0xc018643a, buf, True)
                _, sequence, seconds, useconds = struct.unpack('=IIqq', buf)
                replies.append(dict(sequence=sequence, timestamp=seconds + useconds / 1e6))
            values['vblank'] = replies
            values['advancing'] = ((replies[1]['sequence'] - replies[0]['sequence']) &
                                   0xffffffff) > 0
        finally:
            os.close(fd)
        result['snapshots'][name] = values
        save()
        assert values['dp_status'] == values['edp_status'] == 'connected'
        assert values['dp_enabled'] == values['edp_enabled'] == 'enabled'
        assert values['edid_valid'] and values['advancing']

    try:
        save()
        assert module.exists()
        snapshot('before')
        assert result['snapshots']['before']['forwarder_bound']
        result['restart_uptime'] = float(Path('/proc/uptime').read_text().split()[0])
        # rmmod names exactly one module; modprobe -r could remove suppliers.
        assert run('remove', ['rmmod', 'surface_aggregator_usbc'])
        removed = True
        assert not module.exists()
        snapshot('unloaded')
        assert run('load', ['modprobe', 'surface_aggregator_usbc'])
        time.sleep(30)
        snapshot('after')
        assert result['snapshots']['after']['forwarder_bound']
        result['scanout_at_all_snapshots'] = True
        result['complete'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        try:
            if removed and not module.exists():
                run('restore', ['modprobe', 'surface_aggregator_usbc'])
            result['forwarder_loaded_at_exit'] = module.exists()
            proc = subprocess.run(['journalctl', '-b', '-k', '--no-pager', '-o',
                                   'short-monotonic'], capture_output=True, text=True, timeout=15)
            (output / 'reload-kernel.log').write_text(proc.stdout + proc.stderr)
            result['kernel_log_exit'] = proc.returncode
            result['usc_events_after_restart'] = [line for line in proc.stdout.splitlines()
                if 'USC DP port 0' in line and
                (stamp := re.match(r'\[\s*([0-9.]+)\]', line)) and
                float(stamp[1]) >= result.get('restart_uptime', float('inf'))]
            # Sampled scanout is not continuity; events do not prove GET/replay semantics.
            save()
        finally:
            subprocess.run([lock, 'release', 'device', owner], check=True)
    print(json.dumps(result), flush=True)


def return_to_default(args):
    os.umask(63)
    words = Path('/proc/cmdline').read_text().split()
    attempts = [w.split('=', 1)[1] for w in words if w.startswith('spx_attempt=')]
    assert attempts == [ATTEMPT] and 'spx_boot=mainline-functional' in words
    out = Path('/var/lib/spx-boot-diagnostics/functional') / attempts[0]
    prepared = json.loads((out / 'prepared.json').read_text())
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot != prepared['preboot_id'] and os.uname().release == prepared['release']
    recovery = json.loads((out / 'working-recovery.json').read_text())
    cfg = Path('/boot/grub/grub.cfg').read_text()
    assert recovery['entry'] in cfg and 'set default="spx-known-good"' in cfg
    for path, expected in recovery['payload_sha256'].items():
        h = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for data in iter(lambda: stream.read(1048576), b''):
                h.update(data)
        assert h.hexdigest() == expected
    env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert not any((l.startswith('next_entry=') and l != 'next_entry=' for l in env.splitlines()))
    assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
    audio_stop = stop_desktop_audio(args)
    for label, args in [('kernel.log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic']), ('journal.log', ['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'])]:
        with (out / label).open('wb') as stream:
            subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=30)
    # This record precedes shutdown; only the next boot can establish recovery.
    (out / 'return.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=boot, release=os.uname().release, uptime=Path('/proc/uptime').read_text().strip(), phase='reboot-request', shutdown_completion_verified=False, audio_stop_complete=audio_stop['complete'], audio_stop_result=str(out / 'audio-stop.json'), known_good_payloads_intact=True, persistent_default='spx-known-good', next_entry_empty=True), indent=2) + '\n')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    env = dict((line.split('=', 1) for line in subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines()))
    assert env['saved_entry'] == 'spx-known-good' and (not env.get('next_entry'))
    os.sync()
    subprocess.run(['systemctl', 'reboot'], check=True)

def extend_window(args):
    """Keep the existing automatic return, allowing time for physical tests."""
    assert os.geteuid() == 0 and os.uname().release == RELEASE
    assert 'spx_attempt=' + ATTEMPT in Path('/proc/cmdline').read_text().split()
    assert not (OUT / 'return.json').exists()
    seconds = args.return_seconds
    assert float(Path('/proc/uptime').read_text().split()[0]) + 60 < seconds <= 86400
    unit = 'spx-trial-return@' + ATTEMPT + '.timer'
    assert subprocess.check_output(['systemctl', 'is-active', unit], text=True).strip() == 'active'
    override = Path('/run/systemd/system') / (unit + '.d/window.conf')
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text('[Timer]\nOnBootSec=\nOnBootSec=' + str(seconds) + 's\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'restart', unit], check=True)
    subprocess.run(['systemctl', 'is-active', unit], check=True)
    (OUT / 'window.json').write_text(json.dumps(dict(
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        return_seconds_after_boot=seconds, runtime_only=True), indent=2) + '\n')
    subprocess.run(['systemctl', 'list-timers', unit, '--no-pager'], check=True)


def validate_microphone_source(action, source):
    assert source in ('DMIC0', 'DMIC1'), 'unknown microphone source'
    assert source == 'DMIC1' or action in ('capture', 'feedback', 'desktop-mic'), 'DMIC0 requires capture or feedback or desktop-mic'


def validate_microphone_array(action, source, enabled):
    assert type(enabled) is bool and (not enabled or (action == 'feedback' and source == 'DMIC1')), \
        '--microphone-array requires feedback with primary DMIC1'


def validate_capture_reopen(action, enabled):
    assert type(enabled) is bool and (not enabled or action == 'desktop-mic'), \
        '--capture-reopen requires desktop-mic'


def validate_capture_contract_check(action, reopen, enabled):
    assert type(enabled) is bool and (not enabled or (action == 'desktop-mic' and reopen is True)), \
        '--capture-contract-check requires desktop-mic --capture-reopen'


def validate_native_mic_on_demand(action, enabled, reopen=False, contract=False):
    assert type(enabled) is bool and (not enabled or
        (action == 'desktop-mic' and not reopen and not contract)), \
        '--native-mic-on-demand requires desktop-mic and excludes capture-reopen/contract-check'


def validate_native_mic_cold_start(action, enabled, on_demand=False, reopen=False, contract=False):
    assert type(enabled) is bool and (not enabled or
        (action == 'desktop-mic' and on_demand is True and not reopen and not contract)), \
        '--native-mic-cold-start requires desktop-mic --native-mic-on-demand and excludes capture-reopen/contract-check'


def validate_desktop_microphone(action, enabled):
    assert type(enabled) is bool and (not enabled or action == 'serve'), \
        '--desktop-microphone requires serve'


def validate_native_mic_app_formats(action, microphone, enabled):
    assert type(enabled) is bool and (not enabled or
        (action == 'serve' and microphone is True)), \
        '--native-mic-app-formats requires serve --desktop-microphone'


def validate_desktop_controls(action, enabled):
    assert type(enabled) is bool and (not enabled or action == "serve"), \
        "--desktop-controls requires serve"


def arm_audio(args):
    """Queue one authorized initialization or microphone-monitored audio test."""
    action = 'initialize' if args.audio_action == 'plan' else args.audio_action
    validate_native_mic_app_formats(action, getattr(args, 'desktop_microphone', False),
                                   getattr(args, 'native_mic_app_formats', False))
    source = getattr(args, 'microphone_source', 'DMIC1')
    validate_native_mic_cold_start(action, getattr(args, 'native_mic_cold_start', False),
        getattr(args, 'native_mic_on_demand', False), getattr(args, 'capture_reopen', False),
        getattr(args, 'capture_contract_check', False))
    validate_native_mic_on_demand(action, getattr(args, 'native_mic_on_demand', False),
                                 getattr(args, 'capture_reopen', False),
                                 getattr(args, 'capture_contract_check', False))
    validate_desktop_microphone(action, getattr(args, 'desktop_microphone', False))
    validate_desktop_controls(action, getattr(args, 'desktop_controls', False))
    validate_microphone_source(action, source)
    validate_microphone_array(action, source, getattr(args, 'microphone_array', False))
    validate_capture_reopen(action, getattr(args, 'capture_reopen', False))
    validate_capture_contract_check(action, getattr(args, 'capture_reopen', False),
                                    getattr(args, 'capture_contract_check', False))
    require_source_boot()
    recovery()
    assert args.allow_amp_power, 'explicit amplifier-power authorization required'
    assert action in ('initialize', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic')
    if action in ('feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
        assert args.allow_playback and args.allow_capture, 'feedback needs playback and capture authorization'
    if action == 'serve':
        assert 0 <= args.serve_seconds <= 82800
        assert 1433 <= args.desktop_peak <= 12000
    if args.return_after_audio_seconds is not None:
        assert 61 <= args.return_after_audio_seconds <= 900
    prepared = json.loads((OUT / 'prepared.json').read_text())
    assert prepared.get('audio_mode') == 'parked'
    assert (OUT / 'installed.json').exists() and not (OUT / 'selected.json').exists()
    assert not (OUT / 'audio-started.json').exists()
    account = pwd.getpwnam(args.desktop_user)
    assert account.pw_uid != 0
    os.umask(0o077)
    with (OUT / 'audio-request.json').open('x') as stream:
        json.dump(dict(attempt=ATTEMPT, release=RELEASE, preboot_id=BOOT_ID,
                       desktop_user=account.pw_name, action=action,
                       microphone_source=source, microphone_array=getattr(args, 'microphone_array', False), capture_reopen=getattr(args, 'capture_reopen', False),
                       capture_contract_check=getattr(args, 'capture_contract_check', False),
                       native_mic_on_demand=getattr(args, 'native_mic_on_demand', False),
                       native_mic_cold_start=getattr(args, 'native_mic_cold_start', False),
                       allow_amp_power=True, playback=action in ('feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'),
                       capture=action in ('feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'),
                       serve_seconds=args.serve_seconds if action == 'serve' else None,
                       desktop_peak=args.desktop_peak if action == 'serve' else None,
                       desktop_controls=getattr(args, 'desktop_controls', False),
                       desktop_microphone=getattr(args, 'desktop_microphone', False),
                       native_mic_app_formats=getattr(args, 'native_mic_app_formats', False),
                       return_after_audio_seconds=args.return_after_audio_seconds,
                       utc=datetime.now(timezone.utc).isoformat()), stream, indent=2)
        stream.write('\n')
    print('One audio ' + action + ' test queued for the selected trial boot', flush=True)


def audio_boot():
    """Require this candidate's completed checks in the current boot."""
    assert os.geteuid() == 0 and os.uname().release == RELEASE
    words = Path('/proc/cmdline').read_text().split()
    assert [w for w in words if w.startswith('spx_attempt=')] == ['spx_attempt=' + ATTEMPT]
    assert 'spx_audio=parked' in words and 'spx_boot=mainline-functional' in words
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    checked = json.loads((OUT / 'functional.json').read_text())
    assert checked.get('complete') is True and checked['boot_id'] == boot
    assert checked['release'] == RELEASE
    return boot


def claim_audio_boot(boot, source):
    """Consume before hardware access, including failed starts and checker restarts."""
    directory = OUT / 'audio-started-boots'
    directory.mkdir(mode=0o700, exist_ok=True)
    try:
        with (directory / (boot + '.json')).open('x') as stream:
            json.dump(dict(boot_id=boot, source=source, release=RELEASE), stream)
            stream.write('\n')
    except FileExistsError:
        return False
    return True


def write_desktop_policy(record):
    target = OUT / 'desktop-audio.json'
    temporary = target.with_name('.desktop-audio-' + str(os.getpid()) + '.json')
    try:
        with temporary.open('x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(record, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def desktop_ready(ready, boot):
    return (type(ready) is dict and ready.get('boot_id') == boot and ready.get('release') == RELEASE and
            all(ready.get(key) is True for key in
                ('acoustic_passed', 'public_acoustic_passed', 'recording_closed')))


def desktop_microphone_ready(ready):
    # Preserving an explicit other default source skips default-client proof;
    # that fixture cannot authorize microphone persistence.
    if type(ready) is not dict:
        return False
    microphone = ready.get('microphone')
    return (type(microphone) is dict and microphone.get('source') == 'spx_microphone' and
            type(microphone.get('source_index')) is int and microphone['source_index'] >= 0 and
            type(microphone.get('module')) is str and microphone['module'].isdigit() and
            all(microphone.get(key) is True for key in
                ('default_selected', 'bounded_clients_passed', 'all_automated_recordings_bounded')) and
            'recording' in microphone and microphone['recording'] is None and
            microphone.get('source_lifetime') == 'serve-owner')


def desktop_microphone_result(ready, result):
    """Match proof within one boot; source/module indices may change next boot."""
    if type(result) is not dict:
        return False
    served = result.get('serve')
    microphone = result.get('desktop_microphone')
    return (desktop_microphone_ready(ready) and type(served) is dict and
            desktop_ready(served, ready['boot_id']) and desktop_microphone_ready(served) and
            served['microphone'] == ready['microphone'] and type(microphone) is dict and
            microphone.get('microphone_client_passed') is True and
            all(microphone.get(key) == ready['microphone'][key] for key in
                ('source', 'source_index', 'module')) and not result.get('error'))


def check_live_desktop_microphone(ready, result, account):
    """Read metadata only; enabling persistence must not open native capture."""
    assert desktop_microphone_result(ready, result), 'Unverified desktop microphone'
    identity = result['desktop_microphone'].get('module_identity')
    assert type(identity) is dict and identity.get('index') == ready['microphone']['module']
    assert identity.get('name') == 'module-alsa-source' and type(identity.get('argument')) is str
    command = ['runuser', '-u', account.pw_name, '--', 'env',
               'XDG_RUNTIME_DIR=/run/user/' + str(account.pw_uid),
               'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/' + str(account.pw_uid) + '/bus',
               'pactl']
    sources = json.loads(subprocess.run(command + ['--format=json', 'list', 'sources'],
                        capture_output=True, text=True, check=True, timeout=5).stdout)
    owned = [source for source in sources if source.get('name') == 'spx_microphone']
    assert len(owned) == 1, 'Desktop microphone missing or duplicated'
    source = owned[0]
    assert type(source.get('index')) is int and source['index'] == ready['microphone']['source_index']
    assert str(source.get('owner_module')) == identity['index']
    assert source.get('monitor_source') == '' and source.get('sample_specification') == 's16le 1ch 48000Hz'
    assert source.get('channel_map') == 'mono'
    modules = []
    text = subprocess.run(command + ['--format=text', 'list', 'short', 'modules'],
                          capture_output=True, text=True, check=True, timeout=5).stdout
    for line in text.splitlines():
        fields = line.split('\t', 3)
        if len(fields) >= 3 and fields[1] == 'module-alsa-source' and re.search(
                r'(?:^|\s)source_name=spx_microphone(?:\s|$)', fields[2]):
            modules.append(dict(index=fields[0], name=fields[1], argument=fields[2]))
    assert modules == [identity], 'Desktop microphone module identity changed'


def quarantine_desktop_audio(boot):
    (OUT / 'desktop-audio.json').rename(OUT / ('desktop-audio-failed-' + boot + '.json'))
    print('Desktop opt-in quarantined after an unsuccessful or interrupted run; '
          'no automatic retry on this or a later boot.', flush=True)


def archive_audio_result(boot):
    """Retain small prior-boot evidence before the shared output is reused."""
    for name in ('serve-ready.json', 'serve-result.json', 'audio-stop.json'):
        source = OUT / name if name == 'audio-stop.json' else OUT / 'audio' / name
        if not source.exists():
            continue
        record = json.loads(source.read_text())
        previous = (record.get('boot_id') or (record.get('serve') or {}).get('boot_id') or
                    (record.get('before') or {}).get('boot_id'))
        if previous and previous != boot:
            assert re.fullmatch(r'[A-Za-z0-9-]+', previous)
            directory = OUT / 'audio/boots' / previous
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            target = directory / name
            if not target.exists():
                shutil.copy2(source, target)
            if name == 'audio-stop.json':
                # The stop tool refuses another boot's record. Preserve its
                # exact bytes before allowing the new owner's independent stop.
                assert target.read_bytes() == source.read_bytes(), 'Conflicting archived stop evidence'
                source.unlink()


def stop_desktop_audio(args):
    """Orderly owner-only stop; failure prevents the guarded return reboot."""
    from audio_stop import Live, exercise
    os.umask(0o077)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    live = Live(OUT, ATTEMPT, RELEASE, boot, HERE, args.desktop_user, args.desktop_peak)
    result = exercise(live)
    print(json.dumps(dict(audio_stop_complete=result['complete'],
                         result=str(OUT / 'audio-stop.json'),
                         no_active_audio=result.get('no_active_audio', False))), flush=True)
    return result


def enable_desktop_audio(args):
    """Opt in only from the same verified, still-running desktop stream."""
    os.umask(0o077)
    boot = audio_boot()
    ready = json.loads((OUT / 'audio/serve-ready.json').read_text())
    assert desktop_ready(ready, boot)
    assert not ready.get('stopped') and ready['sink'] == 'spx_speakers'
    assert type(args.desktop_peak) is int and 1433 <= args.desktop_peak <= 12000
    assert ready['peak_limit'] == args.desktop_peak and ready['pa_gain'] == 0
    account = pwd.getpwnam(args.desktop_user)
    assert account.pw_uid != 0
    owner, pcm = ready['owner_pid'], ready['pcm_pid']
    assert all(type(pid) is int and pid > 1 for pid in (owner, pcm))
    command_path = Path(f'/proc/{owner}/cmdline')
    command = command_path.read_bytes().decode().rstrip('\0').split('\0')
    assert any(path in command for path in (str(HERE / 'audio.py'),
               '/usr/local/lib/spx-boot-diagnostics/audio.py')) and 'serve' in command
    for option, value in (('--owner', 'audio-' + ATTEMPT),
                          ('--desktop-user', args.desktop_user),
                          ('--desktop-peak', str(args.desktop_peak)),
                          ('--output', str(OUT / 'audio'))):
        assert command.count(option) == 1 and command[command.index(option) + 1] == value
    assert re.search(r'^Uid:\s+0\s+0\s+0\s+0\s*$',
                     Path(f'/proc/{owner}/status').read_text(), re.M)
    assert Path('/tmp/spx-locks/spx-device.lock/owner').read_text().strip() == 'audio-' + ATTEMPT
    assert command.count('--desktop-microphone') <= 1
    microphone = '--desktop-microphone' in command
    if microphone:
        result = json.loads((OUT / 'audio/serve-result.json').read_text())
        check_live_desktop_microphone(ready, result, account)
    else:
        assert 'microphone' not in ready, 'Microphone readiness and live owner flag disagree'
    assert Path(f'/proc/{pcm}/comm').read_text().strip() == 'aplay'
    assert re.search(r'^PPid:\s*' + str(owner) + r'\s*$',
                     Path(f'/proc/{pcm}/status').read_text(), re.M)
    playback = list(Path('/proc/asound').glob('card*/pcm*p/sub*/status'))
    opened = [value for path in playback if (value := path.read_text().strip()) != 'closed']
    assert len(opened) == 1 and re.search(r'^state:\s+RUNNING$', opened[0], re.M)
    assert re.search(r'^owner_pid\s*:\s*' + str(pcm) + r'\s*$', opened[0], re.M)
    capture = list(Path('/proc/asound').glob('card*/pcm*c/sub*/status'))
    assert capture and all(path.read_text().strip() == 'closed' for path in capture)
    assert command_path.read_bytes().decode().rstrip('\0').split('\0') == command
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    # Enabling while the old checker owns a live stream must not allow a restart
    # in this boot, even if that checker predates the common consumed marker.
    claim_audio_boot(boot, 'enabled-existing-serve')
    policy = dict(attempt=ATTEMPT, release=RELEASE, desktop_user=args.desktop_user,
                  desktop_peak=args.desktop_peak, verified_boot_id=boot,
                  desktop_microphone=microphone)
    write_desktop_policy(policy)
    print('Desktop audio opted in for this candidate: bounded microphone verification '
          'at startup, then serve until stopped. Boot selection and return timer unchanged.', flush=True)


def dispatch_audio(args):
    # A queued experiment always wins; it must never fall through to another
    # initialization after its stream closes or fails.
    if (OUT / 'audio-request.json').exists():
        requested_audio(args)
        return
    policy_path = OUT / 'desktop-audio.json'
    if not policy_path.exists():
        return
    metadata = policy_path.lstat()
    assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
    assert metadata.st_mode & 0o022 == 0, 'Desktop opt-in must be root-owned and not writable by others'
    record = json.loads(policy_path.read_text())
    boot = audio_boot()
    assert record['attempt'] == ATTEMPT and record['release'] == RELEASE
    peak = record['desktop_peak']
    assert type(peak) is int and 1433 <= peak <= 12000
    assert pwd.getpwnam(record['desktop_user']).pw_uid != 0
    microphone = record.get('desktop_microphone', False)
    validate_desktop_microphone('serve', microphone)
    if microphone:
        assert type(record.get('verified_boot_id')) is str and record['verified_boot_id']
    previous = record.get('last_start_boot_id') or (record.get('verified_boot_id') if microphone else None)
    if previous and previous != boot:
        # If the wrapper was killed during startup it could not quarantine its
        # policy. Missing/mismatched readiness still prevents a blind next boot.
        try:
            ready = json.loads((OUT / 'audio/serve-ready.json').read_text())
            result = json.loads((OUT / 'audio/serve-result.json').read_text())
            passed = desktop_ready(ready, previous) and type(result) is dict and not result.get('error')
            if microphone:
                evidence = result.get('desktop_microphone') if type(result) is dict else None
                passed = (passed and desktop_microphone_result(ready, result) and
                          result.get('success') is True and evidence.get('restored') is True and
                          'adapter_error' in evidence and evidence['adapter_error'] is None and
                          evidence.get('kernel_errors') == [] and evidence.get('cleanup_errors') == [] and
                          result.get('cleanup_errors') == [])
        except (OSError, ValueError):
            passed = False
        if not passed:
            quarantine_desktop_audio(previous)
            return
    if not claim_audio_boot(boot, 'desktop-opt-in'):
        return
    archive_audio_result(boot)
    record['last_start_boot_id'] = boot
    write_desktop_policy(record)
    # Remove the previous boot's readiness even if lock acquisition or startup
    # fails before audio.py can write its own fresh report.
    (OUT / 'audio/serve-ready.json').unlink(missing_ok=True)
    args.audio_action = 'serve'
    args.microphone_source = 'DMIC1'
    args.serve_seconds = 0
    args.desktop_peak = peak
    args.desktop_user = record['desktop_user']
    args.desktop_microphone = microphone
    args.native_mic_app_formats = False  # Application-format trials are never desktop opt-in policy.
    args.allow_amp_power = args.allow_playback = args.allow_capture = True
    print('Starting bounded speaker tones and microphone verification; helper recording '
          'closes before desktop readiness.' + (' Native microphone available to applications.'
          if microphone else ' No continuous microphone capture.'), flush=True)
    try:
        audio_check(args)  # Holds the device lock; no return-timer changes or retries.
    except BaseException:
        quarantine_desktop_audio(boot)
        raise


def requested_audio(args):
    request = OUT / 'audio-request.json'
    if not request.exists():
        return
    record = json.loads(request.read_text())
    validate_native_mic_app_formats(record['action'], record.get('desktop_microphone', False),
                                   record.get('native_mic_app_formats', False))
    source = record.get('microphone_source', 'DMIC1')
    validate_native_mic_cold_start(record['action'], record.get('native_mic_cold_start', False),
        record.get('native_mic_on_demand', False), record.get('capture_reopen', False),
        record.get('capture_contract_check', False))
    validate_native_mic_on_demand(record['action'], record.get('native_mic_on_demand', False),
                                 record.get('capture_reopen', False),
                                 record.get('capture_contract_check', False))
    validate_desktop_microphone(record['action'], record.get('desktop_microphone', False))
    validate_desktop_controls(record['action'], record.get('desktop_controls', False))
    validate_microphone_source(record['action'], source)
    validate_microphone_array(record['action'], source, record.get('microphone_array', False))
    validate_capture_reopen(record['action'], record.get('capture_reopen', False))
    validate_capture_contract_check(record['action'], record.get('capture_reopen', False),
                                    record.get('capture_contract_check', False))
    words = Path('/proc/cmdline').read_text().split()
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert record['attempt'] == ATTEMPT and record['release'] == os.uname().release
    source_boot = json.loads((OUT / 'installed.json').read_text())['boot_id']
    assert record['preboot_id'] == source_boot and boot_id != source_boot
    assert 'spx_attempt=' + ATTEMPT in words and 'spx_audio=parked' in words
    assert record['action'] in ('initialize', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic') and record['allow_amp_power'] is True
    feedback = record['action'] in ('feedback', 'desktop', 'serve', 'reopen', 'desktop-mic')
    assert record['playback'] is feedback and record['capture'] is feedback
    if record['action'] == 'serve':
        assert type(record.get('serve_seconds')) is int and 0 <= record['serve_seconds'] <= 82800
        peak = record.get('desktop_peak', 1433)
        assert type(peak) is int and 1433 <= peak <= 12000
    started = OUT / 'audio-started.json'
    assert not started.exists()
    if not claim_audio_boot(boot_id, 'one-shot-request'):
        return
    # Consume before hardware access; restarting the checker cannot repeat it.
    request.rename(started)
    archive_audio_result(boot_id)
    (OUT / 'audio/serve-ready.json').unlink(missing_ok=True)
    args.audio_action = record['action']
    args.desktop_controls = record.get('desktop_controls', False)
    args.desktop_microphone = record.get('desktop_microphone', False)
    args.native_mic_app_formats = record.get('native_mic_app_formats', False)
    args.microphone_source = source
    args.microphone_array = record.get('microphone_array', False)
    args.capture_reopen = record.get('capture_reopen', False)
    args.capture_contract_check = record.get('capture_contract_check', False)
    args.native_mic_on_demand = record.get('native_mic_on_demand', False)
    args.native_mic_cold_start = record.get('native_mic_cold_start', False)
    args.allow_amp_power = True
    args.allow_playback = feedback
    args.allow_capture = feedback
    args.desktop_user = record['desktop_user']
    try:
        if args.audio_action == 'serve':
            args.serve_seconds = record['serve_seconds']
            args.desktop_peak = record.get('desktop_peak', 1433)
            # Keep the automatic return beyond verification and the requested
            # application session. A failed start still uses the short return
            # in finally; no per-attempt service is needed.
            if args.serve_seconds:
                args.return_seconds = int(float(Path('/proc/uptime').read_text().split()[0])) + args.serve_seconds + 180
                extend_window(args)
            # An untimed application bridge never changes the boot fallback.
            # The coordinator settles that policy separately after readiness.
        audio_check(args)
    finally:
        for name, extra in [('kernel.log', ['-k']), ('journal.log', [])]:
            with (OUT / name).open('wb') as stream:
                subprocess.run(['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'] + extra,
                               stdout=stream, check=True, timeout=30)
        delay = record.get('return_after_audio_seconds')
        # An untimed desktop restore is part of the wider hardware trial.
        # Failure must preserve its existing recovery window so the coordinator
        # can collect results and continue non-audio checks. Timed audio-only
        # sessions retain their short return after completion or failure.
        if delay is None and record['action'] == 'serve' and record['serve_seconds']:
            delay = 61
        if delay is not None:
            assert isinstance(delay, int) and 61 <= delay <= 900
            args.return_seconds = int(float(Path('/proc/uptime').read_text().split()[0])) + delay + 1
            extend_window(args)


def audio_check(args):
    action = args.audio_action
    validate_native_mic_app_formats(action, getattr(args, 'desktop_microphone', False),
                                   getattr(args, 'native_mic_app_formats', False))
    source = getattr(args, 'microphone_source', 'DMIC1')
    validate_native_mic_cold_start(action, getattr(args, 'native_mic_cold_start', False),
        getattr(args, 'native_mic_on_demand', False), getattr(args, 'capture_reopen', False),
        getattr(args, 'capture_contract_check', False))
    validate_native_mic_on_demand(action, getattr(args, 'native_mic_on_demand', False),
                                 getattr(args, 'capture_reopen', False),
                                 getattr(args, 'capture_contract_check', False))
    validate_desktop_microphone(action, getattr(args, 'desktop_microphone', False))
    validate_desktop_controls(action, getattr(args, 'desktop_controls', False))
    validate_microphone_source(action, source)
    validate_microphone_array(action, source, getattr(args, 'microphone_array', False))
    validate_capture_reopen(action, getattr(args, 'capture_reopen', False))
    validate_capture_contract_check(action, getattr(args, 'capture_reopen', False),
                                    getattr(args, 'capture_contract_check', False))
    command = ['python3', '-B', str(HERE / 'audio.py'), action,
               '--output', str(OUT / 'audio'), '--microphone-source', source]
    if action == 'plan':
        subprocess.run(command, check=True)
        return
    assert os.geteuid() == 0 and os.uname().release == RELEASE
    words = Path('/proc/cmdline').read_text().split()
    assert 'spx_attempt=' + ATTEMPT in words and 'spx_audio=parked' in words
    owner = 'audio-' + ATTEMPT
    lock = str(REPO / 'tools/spx/spx-lock')
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    active = []
    try:
        if action in ('initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
            from audio import UNITS as audio_units

            assert action in ('recover', 'capture') or args.allow_amp_power, 'this run needs explicit speaker-power authorization'
            assert action not in ('listen', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic') or args.allow_playback, 'this run needs explicit playback authorization'
            assert action not in ('capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic') or args.allow_capture, 'this run needs microphone authorization'
            account = pwd.getpwnam(args.desktop_user)
            userctl = ['runuser', '-u', account.pw_name, '--', 'env',
                       'XDG_RUNTIME_DIR=/run/user/' + str(account.pw_uid),
                       'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/' + str(account.pw_uid) + '/bus',
                       'systemctl', '--user']
            for unit in audio_units:
                result = subprocess.run(userctl + ['is-active', unit], capture_output=True, text=True)
                if result.stdout.strip() in ('active', 'activating', 'reloading'):
                    active.append(unit)
            (OUT / 'audio').mkdir(exist_ok=True)
            (OUT / 'audio/desktop-units.json').write_text(json.dumps(active, indent=2) + '\n')
            # A previous run cannot establish that this one parked successfully.
            (OUT / 'audio' / (action + '-result.json')).unlink(missing_ok=True)
            if active:
                subprocess.run(userctl + ['stop'] + active, check=True, timeout=30)
            command += ['--owner', owner, '--desktop-user', account.pw_name]
            if action in ('initialize', 'listen', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
                command.append('--allow-amp-power')
            if action in ('listen', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
                command.append('--allow-playback')
            if action in ('capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'):
                command.append('--allow-capture')
            if getattr(args, 'microphone_array', False):
                command.append('--microphone-array')
            if getattr(args, 'capture_contract_check', False):
                command.append('--capture-contract-check')
            if getattr(args, 'desktop_microphone', False):
                command.append('--desktop-microphone')
            if getattr(args, 'native_mic_app_formats', False):
                command.append('--native-mic-app-formats')
            if getattr(args, 'native_mic_cold_start', False):
                command.append('--native-mic-cold-start')
            if getattr(args, 'native_mic_on_demand', False):
                command.append('--native-mic-on-demand')
            if getattr(args, 'capture_reopen', False):
                command.append('--capture-reopen')
            if action == 'reopen' and getattr(args, 'reopen_first_channel', None):
                command += ['--reopen-first-channel', args.reopen_first_channel]
            if getattr(args, 'desktop_controls', False):
                command.append('--desktop-controls')
            if action == 'serve':
                assert 0 <= args.serve_seconds <= 82800
                assert 1433 <= args.desktop_peak <= 12000
                command += ['--serve-seconds', str(args.serve_seconds),
                            '--desktop-peak', str(args.desktop_peak)]
        process = subprocess.Popen(command)
        try:
            status = process.wait(timeout=(args.serve_seconds + (180 if getattr(args, 'desktop_controls', False) else 120) if args.serve_seconds else None) if action == 'serve' else
                                  120 if action in ('feedback', 'desktop', 'reopen', 'desktop-mic') else 90 if action == 'listen' else 40)
        except subprocess.TimeoutExpired:
            # Allow the initializer's signal handler/finally block to park.
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        if status:
            raise subprocess.CalledProcessError(status, command)
    finally:
        try:
            if active:
                result = OUT / 'audio' / (action + '-result.json')
                if result.exists() and json.loads(result.read_text()).get('parked') is True:
                    subprocess.run(userctl + ['start'] + active, check=True, timeout=30)
                else:
                    print('Amplifier parking was not confirmed; desktop audio remains stopped. '
                          'Previous units are recorded in audio/desktop-units.json.', flush=True)
        finally:
            subprocess.run([lock, 'release', 'device', owner], check=True)


def sensors_lifecycle(args):
    """One exclusive lifecycle run; the helper gates before any device action."""
    import importlib.util

    assert os.geteuid() == 0
    spec = importlib.util.spec_from_file_location('spx_sensor_lifecycle', HERE / 'sensors/lifecycle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'sensor-lifecycle-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        result = module.exercise(module.Live(OUT / 'sensors-lifecycle', ATTEMPT, RELEASE))
        print(json.dumps(dict(complete=result['complete'], result=str(OUT / 'sensors-lifecycle/result.json'))), flush=True)
        if not result['complete']:
            raise RuntimeError(result.get('error', 'sensor lifecycle capture failed'))
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True)


def dispatch_sensors_crash(args, prepared):
    if not prepared.get('sensors_crash_recovery') or (OUT / 'sensors-crash').exists():
        return
    import sys
    sys.path.insert(0, str(HERE / 'sensors'))
    import crash_test
    owner = 'sensor-crash-' + ATTEMPT
    lock = str(REPO / 'tools/spx/spx-lock')
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        result = crash_test.exercise(crash_test.Live(OUT / 'sensors-crash', ATTEMPT, RELEASE))
        print(json.dumps(dict(complete=result['complete'], result=str(OUT / 'sensors-crash/result.json'))), flush=True)
        if not result['complete']:
            raise RuntimeError(result.get('error', 'sensor crash recovery failed'))
    finally:
        state = subprocess.check_output(['systemctl', 'show', 'spx-sensors-recovery.service', '-p', 'ActiveState', '--value'], text=True, timeout=5).strip()
        if state in ('active', 'activating', 'deactivating'):
            print('Keeping device lock while automatic recovery is live', flush=True)
        else:
            subprocess.run([lock, 'release', 'device', owner], check=True)


def dispatch_thermal(args, prepared):
    """Consume an explicitly queued combined workload once after baseline."""
    if not prepared.get('thermal_combined') or (OUT / 'combined-thermal').exists():
        return
    args.thermal_combined = True
    args.thermal_gpu_fixture = Path(prepared['thermal_gpu_fixture'])
    args.thermal_cpu_stress_ng = (Path(prepared['thermal_cpu_stress_ng'])
                                 if prepared.get('thermal_cpu_stress_ng') else None)
    thermal_check(args)


def thermal_check(args):
    from thermal import Live, CombinedLive
    prepared = json.loads((OUT / 'prepared.json').read_text())
    expected_trip = prepared.get('cpu_passive_trip_mc', 75000)
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'thermal-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        output = OUT / ('combined-thermal' if args.thermal_combined else 'cpu-thermal')
        live = (CombinedLive(output, ATTEMPT, RELEASE, args.thermal_gpu_fixture, args.thermal_cpu_stress_ng, passive_trip=expected_trip)
                if args.thermal_combined else Live(output, ATTEMPT, RELEASE, passive_trip=expected_trip))
        result = live.exercise()
        print(json.dumps(dict(complete=result['complete'], result=str(output / 'result.json'),
                             responses=result.get('responses'))), flush=True)
        if not result['complete']:
            raise RuntimeError(result.get('error', 'scoped thermal test did not pass'))
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True)


def dispatch_tpm_sign(args, prepared):
    """Consume one explicit signing request after completed baseline/PMIC checks."""
    if not prepared.get('tpm_sign') or (OUT / 'tpm-sign').exists():
        return
    args.tpm_tools = Path(prepared['tpm_tools'])
    tpm_sign(args)


def tpm_sign(args):
    import importlib.util
    assert os.geteuid() == 0
    spec = importlib.util.spec_from_file_location('spx_tpm_sign', HERE / 'tpm/sign.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'tpm-sign-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        result = module.exercise(module.Live(OUT / 'tpm-sign', ATTEMPT, RELEASE, args.tpm_tools))
        print(json.dumps(dict(complete=result['complete'], result=str(OUT / 'tpm-sign/result.json'),
                             error=result.get('error'), cleanup_error=result.get('cleanup_error'))), flush=True)
        if not result['complete']:
            raise RuntimeError(result.get('error', result.get('cleanup_error', 'TPM signing failed')))
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True)


def camera_capture(args):
    """Run the queued rear-camera capture once, after every other check."""
    from camera import exercise
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'camera-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        result = exercise(OUT / 'camera', ATTEMPT, RELEASE)
        print(json.dumps(dict(complete=result['complete'], error=result.get('error'),
                              result=str(OUT / 'camera/result.json'))), flush=True)
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True)


def systemd_suspend(args):
    from systemd_sleep import Live, exercise, verify_returned
    assert os.geteuid() == 0
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'systemd-suspend-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        name = 'bluetooth-discovery-resume' if args.retain_bluetooth_discovery else ('bluetooth-resume' if args.bluetooth_resume else ('audio-resume' if args.live_audio_resume else ('systemd-suspend-recovery' if args.verify_sleep_return else 'systemd-suspend')))
        live = Live(OUT / name, ATTEMPT, RELEASE, parked_audio=args.parked_audio or args.live_audio_resume or args.bluetooth_resume,
                    desktop_user=args.desktop_user,
                    default_mic_resume=getattr(args, 'default_mic_resume', False),
                    native_mic_resume=getattr(args, 'native_mic_resume', False))
        if args.bluetooth_resume:
            from bluetooth_resume import exercise as bluetooth_resume
            result = bluetooth_resume(live, allow_radio_on=args.allow_radio_on,
                                      retain_discovery=args.retain_bluetooth_discovery)
        elif args.live_audio_resume:
            from audio_resume import exercise as audio_resume
            result = audio_resume(live, args, owner)
        else:
            result = verify_returned(live, json.loads((OUT / 'systemd-suspend/result.json').read_text())) if args.verify_sleep_return else exercise(live)
        print(json.dumps(dict(complete=result['complete'], result=str(OUT / name / 'result.json'),
                             error=result.get('error'), cleanup_error=result.get('cleanup_error'))), flush=True)
        if not result['complete']:
            raise RuntimeError(result.get('error', result.get('cleanup_error', 'normal suspend did not pass')))
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True)


def dispatch_live_audio_resume(args, prepared):
    """One explicit prepared opt-in; any output means consumed, including failure."""
    if not prepared.get('live_audio_resume') or (OUT / 'audio-resume').exists():
        return
    assert prepared.get('audio_mode') == 'parked' and prepared.get('slim_s2idle_retain') is True
    assert prepared.get('pmic_rtc') is True and prepared.get('sensors_startup') is True
    baseline = json.loads((OUT / 'functional.json').read_text())
    current_boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert current_boot != prepared['preboot_id'], 'prepared boot has not run'
    assert baseline.get('complete') is True and baseline['boot_id'] == current_boot and baseline['release'] == RELEASE
    subprocess.run(['systemd-run', '--unit=spx-systemd-suspend', '--collect', '--wait', '--pipe',
                    '--property=Type=exec',
                    '--property=RuntimeMaxSec=' + ('260' if prepared.get('native_mic_resume') else '200'),
                    '/usr/bin/python3', '-B', '/usr/local/lib/spx-boot-diagnostics/trial.py',
                    'systemd-suspend', ATTEMPT, '--live-audio-resume', '--allow-amp-power',
                    '--allow-playback', '--allow-capture',
                    *(['--default-mic-resume'] if prepared.get('default_mic_resume') else []),
                    *(['--native-mic-resume'] if prepared.get('native_mic_resume') else []),
                    '--desktop-user', args.desktop_user],
                   check=True, timeout=265 if prepared.get('native_mic_resume') else 205)


def bluetooth_power(args):
    from bluetooth_power import Live, exercise
    assert os.geteuid() == 0
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'bluetooth-power-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True, timeout=5)
    try:
        result = exercise(Live(OUT / 'bluetooth-power', ATTEMPT, RELEASE))
        print(json.dumps(dict(complete=result['complete'], result=str(OUT / 'bluetooth-power/result.json'),
                             error=result.get('error'), cleanup_error=result.get('cleanup_error'))), flush=True)
        if not result['complete']:
            raise RuntimeError(result.get('error', result.get('cleanup_error', 'Bluetooth power trial failed')))
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True, timeout=5)


def cdsp_capabilities(args):
    import sys

    assert os.geteuid() == 0
    lock = str(REPO / 'tools/spx/spx-lock')
    owner = 'cdsp-capabilities-' + ATTEMPT
    subprocess.run([lock, 'acquire', 'device', owner], check=True)
    try:
        # Bound the syscall and close path independently of the coordinator.
        code = ('import sys; from pathlib import Path; from cdsp.capabilities import query; '
                'r=query(Path(sys.argv[1]),sys.argv[2],sys.argv[3]); '
                'sys.exit(0 if r["complete"] else 1)')
        subprocess.run([sys.executable, '-B', '-c', code, str(OUT / 'cdsp-capabilities'),
                        ATTEMPT, RELEASE], cwd=HERE, check=True, timeout=25)
        result = json.loads((OUT / 'cdsp-capabilities/result.json').read_text())
        print(json.dumps(result), flush=True)
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'install', 'boot', 'check', 'return', 'extend', 'audio', 'arm-audio', 'enable-desktop-audio', 'stop-audio', 'usbc-reload', 'wifi-band', 'display-power', 'srtc-timer', 'power-measure', 'sensors-lifecycle', 'thermal', 'cdsp-capabilities', 'tpm-sign', 'systemd-suspend', 'bluetooth-power'))
    parser.add_argument('attempt')
    parser.add_argument('--build', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/work-build'))
    parser.add_argument('--parent', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bf'))
    parser.add_argument('--recovery', type=Path, default=Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf/working-recovery.json'))
    parser.add_argument('--dtb', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/spx.dtb'))
    parser.add_argument('--address')
    parser.add_argument('--pmic-rtc', action='store_true',
                        help='add upstream PMIC RTC as rtc1 and test one awake alarm; no suspend')
    parser.add_argument('--verify-sleep-return', action='store_true', help='systemd-suspend: verify a returned sleep from fresh journal evidence without sleeping again')
    parser.add_argument('--live-audio-resume', action='store_true',
                        help='prepare/systemd-suspend: quiet public audio before/after one normal sleep with the same native owners')
    parser.add_argument('--native-mic-resume', action='store_true',
                        help='live-audio-resume only: stock microphone idle across sleep, fresh bounded default clients after wake')
    parser.add_argument('--default-mic-resume', action='store_true',
                        help='live-audio-resume only: retain one ordinary default-source recording client across normal sleep')
    parser.add_argument('--retain-bluetooth-discovery', action='store_true',
                        help='Bluetooth-resume-only: retain one active native discovery client through sleep')
    parser.add_argument('--allow-radio-on', action='store_true',
                        help='Bluetooth-resume-only: temporarily enable an initially off/softblocked fitted radio and restore it')
    parser.add_argument('--bluetooth-resume', action='store_true',
                        help='systemd-suspend: fresh native discovery before/after one normal sleep; loaded audio remains parked')
    parser.add_argument('--parked-audio', action='store_true', help='systemd-suspend: opt in to quiescent loaded-codec powered retention; no playback/capture')
    parser.add_argument('--tpm-sign', action='store_true', help='prepare-only opt in to one transient TPM signing test after baseline')
    parser.add_argument('--tpm-tools', type=Path, default=Path('/var/tmp/spx-tpm2-tools-5.8/usr/bin'), help='private tpm2-tools 5.8 executable directory')
    parser.add_argument('--wifi-profile', help='saved Wi-Fi profile ID to clone for the 2.4 GHz test')
    parser.add_argument('--srtc-observe-expiry', action='store_true',
                        help='observe one 30s AC/DC timer expiry while awake; no suspend or wake-policy change')
    parser.add_argument('--srtc-queue-events', action='store_true',
                        help='temporarily notify EC display-off during expiry; restore display-on')
    parser.add_argument('--srtc-observe-irq', action='store_true',
                        help='temporarily enable the existing disabled IRQ for awake-only observation')
    parser.add_argument('--srtc-d0-notify', action='store_true',
                        help='also test the documented D0-exit/entry EC notification pair while awake')
    parser.add_argument('--sensors-crash-recovery', action='store_true', help='queue one verified SensorsPD host failure and guarded automatic recovery test')
    parser.add_argument('--sensors-close-debug', action='store_true', help='enable existing private proxy SSC disable/client-close traces during the crash trial')
    parser.add_argument('--sensors', action='store_true', help='retain initial SensorsPD listener and gate desktop proxy on SSC readiness')
    parser.add_argument('--sensors-config', type=Path, default=Path('/var/tmp/spx-sensors-config'))
    parser.add_argument('--sensors-daemon', type=Path, default=Path('/var/tmp/spx-hexagonrpc/build/hexagonrpcd/hexagonrpcd'))
    parser.add_argument('--sensors-library', type=Path, default=Path('/var/tmp/spx-hexagonrpc/build/libhexagonrpc/libhexagonrpc.so.0.5'))
    parser.add_argument('--sensors-ssc-library', type=Path, help='opt in to private patched libssc.so.2 for SensorsPD readiness and desktop proxy')
    parser.add_argument('--sensors-ready', type=Path, default=Path('/var/tmp/spx-sensors-ready'))
    parser.add_argument('--cpu-passive-cooling', action='store_true',
                        help='stage board Linux75C/5C passive CPU policy into the retained DTB')
    parser.add_argument('--cpu-passive-trip', type=int, choices=(55000, 75000),
                        help='prepare-only CPU trip in millidegrees;55C is a temporary Linux policy test')
    parser.add_argument('--thermal-combined', action='store_true',
                        help='opt in to300s AC-only CPU+GPU load with80C ceiling; prepare queues it after baseline')
    parser.add_argument('--thermal-gpu-fixture', type=Path,
                        default=Path('/var/tmp/spx-gpu-benchmark-20261003/fixture'),
                        help='retained glmark2-es2-gbm/data fixture for combined thermal test')
    parser.add_argument('--thermal-cpu-stress-ng', type=Path,
                        help='opt in to private stress-ng verified doublemul workers for combined thermal test')
    parser.add_argument('--cdsp', action='store_true',
                        help='enable the guarded CDSP translated capability-only transport')
    parser.add_argument('--qca-setup-trace', action='store_true',
                        help='prepare-only opt in to bounded Surface QCA firmware-setup parser metadata')
    parser.add_argument('--audio', action='store_true', help='enable codecs with both amplifiers parked; no playback')
    parser.add_argument('--slim-s2idle-retain', action='store_true',
                        help='opt in to WIP powered-PIO retention during guarded s2idle; no energy claim')
    parser.add_argument('--usbc', action='store_true',
                        help='load experimental USC-to-DP0 forwarding in the initramfs')
    parser.add_argument('--usbc-phy-orientation', action='store_true',
                        help='opt in to firmware-grounded primary QMP orientation switching')
    parser.add_argument('--replace-module', action='append', default=[],
                        help='changed unloaded/blacklisted module to install while this release runs')
    parser.add_argument('--return-seconds', type=int, default=3600)
    parser.add_argument('--audio-action', choices=('plan', 'inspect', 'initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen', 'desktop-mic'), default='plan')
    parser.add_argument('--capture-contract-check', action='store_true',
                        help='desktop-mic capture-reopen only: bounded incompatible contract rejection probes')
    parser.add_argument('--desktop-microphone', action='store_true',
                        help='audio/arm-audio serve only: fitted stock microphone on demand')
    parser.add_argument('--native-mic-app-formats', action='store_true',
                        help='audio/arm-audio serve desktop-microphone only: bounded application-format clients')
    parser.add_argument('--native-mic-cold-start', action='store_true',
                        help='native-mic-on-demand only: cold stock first-owner ambient prelude')
    parser.add_argument('--native-mic-on-demand', action='store_true',
                        help='desktop-mic-only stock ALSA source demand and idle-close test')
    parser.add_argument('--capture-reopen', action='store_true',
                        help='desktop-mic-only native capture reopen with a third default client')
    parser.add_argument('--reopen-first-channel', choices=('left', 'right'),
                        help='audio reopen only: second-cycle first channel')
    parser.add_argument('--serve-seconds', type=int, default=3600,
                        help='ordinary desktop playback after acoustic verification (0 until stopped, or 1..82800 seconds)')
    parser.add_argument('--desktop-peak', type=int, default=1433,
                        help='ordinary desktop digital peak cap (1433..12000); minimum PA gain remains fixed')
    parser.add_argument('--desktop-controls', action='store_true',
                        help='serve-only acoustic software volume/mute/restoration test')
    parser.add_argument('--allow-amp-power', action='store_true')
    parser.add_argument('--allow-playback', action='store_true')
    parser.add_argument('--allow-capture', action='store_true')
    parser.add_argument('--microphone-array', action='store_true',
                        help='feedback-only fresh native stereo DMIC1/DMIC0 capture')
    parser.add_argument('--microphone-source', choices=('DMIC0', 'DMIC1'), default='DMIC1',
                        help='bounded capture/feedback/desktop-mic input (default: DMIC1)')
    parser.add_argument('--camera-capture', action='store_true',
                        help='prepare only: queue one rear-camera capture of three raw frames, kept in the attempt directory')
    parser.add_argument('--reuse-installed-modules', action='store_true',
                        help='retain current module tree for a command-line-only trial')
    parser.add_argument('--return-after-audio-seconds', type=int,
                        help='after a queued audio test, use the existing return timer after this delay (61..900)')
    parser.add_argument('--desktop-user', default='dvitali')
    args = parser.parse_args()
    if args.native_mic_resume and (not args.live_audio_resume or args.default_mic_resume or args.desktop_controls):
        parser.error('--native-mic-resume requires --live-audio-resume and excludes default-mic-resume/desktop-controls')
    if args.default_mic_resume and not args.live_audio_resume:
        parser.error('--default-mic-resume requires --live-audio-resume')
    if args.retain_bluetooth_discovery and not args.bluetooth_resume:
        parser.error('--retain-bluetooth-discovery requires --bluetooth-resume')
    if args.allow_radio_on and not args.bluetooth_resume:
        parser.error('--allow-radio-on requires --bluetooth-resume')
    if args.bluetooth_resume and (args.command != 'systemd-suspend' or args.live_audio_resume or args.verify_sleep_return):
        parser.error('--bluetooth-resume requires systemd-suspend and excludes live-audio/recovery modes')
    if args.live_audio_resume and (args.command not in ('prepare', 'systemd-suspend') or args.parked_audio or args.verify_sleep_return):
        parser.error('--live-audio-resume requires prepare/systemd-suspend and excludes parked/recovery modes')
    if args.live_audio_resume and args.command == 'prepare' and not (args.audio and args.pmic_rtc and args.slim_s2idle_retain and args.sensors):
        parser.error('--live-audio-resume preparation requires audio, PMIC RTC, retention and sensors')
    if args.qca_setup_trace and args.command != 'prepare':
        parser.error('--qca-setup-trace requires prepare')
    if args.camera_capture and args.command != 'prepare':
        parser.error('--camera-capture requires prepare')
    if args.parked_audio and args.command != 'systemd-suspend':
        parser.error('--parked-audio requires systemd-suspend')
    if args.desktop_microphone and (args.command not in ('audio', 'arm-audio') or args.audio_action != 'serve'):
        parser.error('--desktop-microphone requires audio/arm-audio serve')
    if args.native_mic_app_formats and (args.command not in ('audio', 'arm-audio') or
                                      args.audio_action != 'serve' or not args.desktop_microphone):
        parser.error('--native-mic-app-formats requires audio/arm-audio serve --desktop-microphone')
    if args.desktop_controls and not ((args.command in ('audio', 'arm-audio') and args.audio_action == 'serve') or
                                     (args.command == 'prepare' and args.audio)):
        parser.error('--desktop-controls requires audio/arm-audio serve or prepare --audio')
    if args.tpm_sign and (args.command != 'prepare' or args.audio or args.cdsp or args.thermal_combined or args.sensors_crash_recovery):
        parser.error('--tpm-sign requires prepare and excludes audio/CDSP/thermal/sensor-crash experiments')
    if args.slim_s2idle_retain and (args.command != 'prepare' or not args.audio or not args.pmic_rtc):
        parser.error('--slim-s2idle-retain requires prepare --audio --pmic-rtc')
    if args.microphone_array and (args.command not in ('audio', 'arm-audio') or
                                  args.audio_action != 'feedback' or args.microphone_source != 'DMIC1'):
        parser.error('--microphone-array requires audio/arm-audio feedback with primary DMIC1')
    if args.capture_contract_check and (args.command not in ('audio', 'arm-audio') or
                                        args.audio_action != 'desktop-mic' or not args.capture_reopen):
        parser.error('--capture-contract-check requires audio/arm-audio desktop-mic --capture-reopen')
    if args.native_mic_cold_start and (args.command not in ('audio', 'arm-audio') or args.audio_action != 'desktop-mic' or not args.native_mic_on_demand or args.capture_reopen or args.capture_contract_check):
        parser.error('--native-mic-cold-start requires audio/arm-audio desktop-mic --native-mic-on-demand and excludes capture-reopen/contract-check')
    if args.native_mic_on_demand and (args.command not in ('audio', 'arm-audio') or args.audio_action != 'desktop-mic' or args.capture_reopen or args.capture_contract_check):
        parser.error('--native-mic-on-demand requires audio/arm-audio desktop-mic and excludes capture-reopen/contract-check')
    if args.capture_reopen and (args.command not in ('audio', 'arm-audio') or args.audio_action != 'desktop-mic'):
        parser.error('--capture-reopen requires audio/arm-audio --audio-action desktop-mic')
    if args.reopen_first_channel is not None and (args.command != 'audio' or args.audio_action != 'reopen'):
        parser.error('--reopen-first-channel requires audio --audio-action reopen')
    if args.microphone_source != 'DMIC1' and (args.command not in ('audio', 'arm-audio') or
                                            args.audio_action not in ('capture', 'feedback', 'desktop-mic')):
        parser.error('--microphone-source DMIC0 requires audio/arm-audio capture, feedback or desktop-mic')
    if args.sensors_crash_recovery and (args.command != 'prepare' or not args.sensors or not args.sensors_ssc_library or args.audio or args.cdsp or args.thermal_combined):
        parser.error('--sensors-crash-recovery requires prepare --sensors --sensors-ssc-library and excludes audio/CDSP/thermal')
    if args.sensors_close_debug and (args.command != 'prepare' or not args.sensors_crash_recovery):
        parser.error('--sensors-close-debug requires prepare --sensors-crash-recovery')
    if args.cpu_passive_trip is not None and (args.command != 'prepare' or not args.cpu_passive_cooling):
        parser.error('--cpu-passive-trip requires prepare --cpu-passive-cooling')
    if args.thermal_combined and args.command not in ('prepare', 'thermal'):
        parser.error('--thermal-combined requires prepare or thermal')
    if args.thermal_cpu_stress_ng and (not args.thermal_combined or args.command not in ('prepare', 'thermal')):
        parser.error('--thermal-cpu-stress-ng requires prepare/thermal --thermal-combined')
    if args.command == 'prepare' and args.thermal_combined and (args.audio or args.cdsp):
        parser.error('combined thermal trial requires audio and experimental CDSP disabled')
    assert re.fullmatch(r'[0-9]{8}[a-z0-9]+', args.attempt)
    global ATTEMPT, OUT, STAGE, BUILD, PARENT, OLD, RECOVERY, BOOT_ID, RELEASE
    ATTEMPT = args.attempt
    OUT = Path('/var/lib/spx-boot-diagnostics/functional') / ATTEMPT
    STAGE = args.build.parent
    BUILD = args.build
    PARENT = args.parent
    OLD = args.recovery.parent
    RECOVERY = args.recovery
    if args.command == 'prepare':
        assert not args.sensors_ssc_library or args.sensors, '--sensors-ssc-library requires --sensors'
        assert args.address, '--address must name this installation, never a shared board address'
        BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        RELEASE = (args.build / 'include/config/kernel.release').read_text().strip()
        prepare(args)
    elif args.command == 'srtc-timer':
        BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        RELEASE = (args.build / 'include/config/kernel.release').read_text().strip()
        srtc_timer(args)
    else:
        record = json.loads((OUT / 'prepared.json').read_text())
        BOOT_ID, RELEASE = record['preboot_id'], record['release']
        if args.command == 'install':
            BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        elif args.command in ('boot', 'arm-audio'):
            BOOT_ID = json.loads((OUT / 'installed.json').read_text())['boot_id']
        if args.command == 'check':
            lock = str(REPO / 'tools/spx/spx-lock')
            owner = 'functional-' + ATTEMPT
            subprocess.run([lock, 'acquire', 'device', owner], check=True)
            try:
                functional_check(args)
            finally:
                subprocess.run([lock, 'release', 'device', owner], check=True)
            if record.get('pmic_rtc') and not (OUT / 'pmic-rtc').exists():
                from pmic_rtc import exercise
                subprocess.run([lock, 'acquire', 'device', 'pmic-rtc-' + ATTEMPT], check=True)
                try:
                    result = exercise(OUT / 'pmic-rtc', ATTEMPT, RELEASE)
                    print(json.dumps(result), flush=True)
                finally:
                    subprocess.run([lock, 'release', 'device', 'pmic-rtc-' + ATTEMPT], check=True)
            if record.get('cdsp_capabilities') and not (OUT / 'cdsp-capabilities').exists():
                cdsp_capabilities(args)
            dispatch_tpm_sign(args, record)
            dispatch_sensors_crash(args, record)
            dispatch_thermal(args, record)
            dispatch_live_audio_resume(args, record)
            dispatch_audio(args)
            if record.get('qca_setup_trace') and not record.get('live_audio_resume') and not (OUT / 'bluetooth-power').exists():
                # A failed Bluetooth step must not cost the boot its capture.
                try:
                    bluetooth_power(args)
                finally:
                    if record.get('camera_capture') and not (OUT / 'camera').exists():
                        camera_capture(args)
            elif record.get('camera_capture') and not (OUT / 'camera').exists():
                camera_capture(args)
        else:
            {'install': install, 'boot': boot, 'return': return_to_default,
             'extend': extend_window, 'audio': audio_check, 'arm-audio': arm_audio,
             'usbc-reload': usbc_reload, 'wifi-band': wifi_band, 'display-power': display_power,
             'enable-desktop-audio': enable_desktop_audio, 'stop-audio': stop_desktop_audio, 'power-measure': power_measure, 'sensors-lifecycle': sensors_lifecycle, 'thermal': thermal_check, 'cdsp-capabilities': cdsp_capabilities, 'tpm-sign': tpm_sign, 'systemd-suspend': systemd_suspend, 'bluetooth-power': bluetooth_power}[args.command](args)


if __name__ == '__main__':
    main()
