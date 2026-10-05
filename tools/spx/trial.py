#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One reusable SPX functional trial: fixed kernel build, prepare/install/boot/return."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import gzip
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import stat
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


def prepare(args):
    os.umask(63)
    require_source_boot()
    recovery()
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
    run('modules-install', make + ['-j4', 'INSTALL_MOD_PATH=' + str(module_root), 'DEPMOD=true', 'modules_install'])
    root = module_root / 'lib/modules' / RELEASE
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
    config.write_text(text)
    run('initramfs', ['mkinitcpio', '-k', RELEASE, '-r', str(module_root), '-c', str(OUT / 'mkinitcpio.conf'), '-D', str(OUT / 'initcpio'), '-D', '/etc/initcpio', '-D', '/usr/lib/initcpio', '-g', str(OUT / 'initramfs.img'), '--nopost'])
    run('bluetooth-address', ['/usr/bin/python3', '-B', str(REPO / 'tools/spx/bluetooth-address.py'), str(args.dtb), str(OUT / 'spx.dtb'), '--address', args.address])
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
    cmdline = ' '.join(cmdline)
    entry = (OLD / 'entry.cfg').read_text().replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT))
    entry = entry.replace(previous['cmdline'].replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT)), cmdline)
    title = 'Audio startup with amplifiers parked' if args.audio else 'Bluetooth address and functional hardware tests'
    entry = entry.replace('bounded Venus core startup and Iris1 startup trial', title)
    (OUT / 'entry.cfg').write_text(entry)
    run('grub-syntax', ['grub-script-check', str(OUT / 'entry.cfg')])
    prepared = dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=BOOT_ID, release=RELEASE, attempt=ATTEMPT, entry='spx-trial-' + ATTEMPT, cmdline=cmdline, source_commit=subprocess.check_output(['git', '-c', 'safe.directory=' + str(REPO), 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), build_directory=str(BUILD), private_config=str(OUT / 'kernel.config'), bluetooth_address=args.address, address_is_per_installation=True, venus_trial=False, speaker_drivers_blocked=True, hardware_acceptance_closed=False, installed=False, boot_selected=False, boot_payloads=dict(vmlinuz=sha(OUT / 'vmlinuz'), initramfs=sha(OUT / 'initramfs.img'), dtb=sha(OUT / 'spx.dtb')))
    prepared.update(audio_mode='parked' if args.audio else 'blocked',
                    usbc_early_load=args.usbc,
                    speaker_drivers_blocked=not args.audio,
                    reuse_installed_modules=args.reuse_installed_modules,
                    replace_modules=args.replace_module)
    recovery()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    (OUT / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    print('Private functional boot prepared; no boot selected', flush=True)


def install(args):
    os.umask(63)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    r = recovery()
    prepared = json.loads((OUT / 'prepared.json').read_text())
    assert prepared['preboot_id'] == BOOT_ID and prepared['release'] == RELEASE
    assert not prepared['venus_trial']
    boot = Path('/boot/spx-trial-{ATTEMPT}'.format(ATTEMPT=ATTEMPT))
    modules = Path('/usr/lib/modules') / RELEASE
    assert not boot.exists() and not (OUT / 'installed.json').exists()
    payloads = {'vmlinuz': OUT / 'vmlinuz', 'initramfs.img': OUT / 'initramfs.img', 'spx.dtb': OUT / 'spx.dtb'}
    expected = dict(zip(payloads, (prepared['boot_payloads'][k] for k in ('vmlinuz', 'initramfs', 'dtb'))))
    for name, source in payloads.items():
        assert sha(source) == expected[name]
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
    if prepared.get('audio_mode') == 'parked':
        from audio import UNITS as audio_units

        shutil.copy2(HERE / 'audio.py', helper.parent / 'audio.py')
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
        # A command-line-only trial keeps the coordinator's current module tree.
        # No loaded module is overwritten, removed or reloaded by installation.
        assert modules.exists() and os.uname().release == RELEASE
        assert not prepared.get('replace_modules')
        words = Path('/proc/cmdline').read_text().split()
        current = [w.split('=', 1)[1] for w in words if w.startswith('spx_attempt=')]
        assert len(current) == 1
        previous = json.loads((OUT.parent / current[0] / 'installed.json').read_text())
        assert previous['boot_payloads']['vmlinuz'] == prepared['boot_payloads']['vmlinuz']
        print('Keeping installed modules for the unchanged running kernel', flush=True)
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
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
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


def boot(args):
    require_source_boot()
    assert float(Path('/proc/uptime').read_text().split()[0]) > 120
    recovery()
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
    for label, args in [('kernel.log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic']), ('journal.log', ['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'])]:
        with (out / label).open('wb') as stream:
            subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=30)
    (out / 'return.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=boot, release=os.uname().release, uptime=Path('/proc/uptime').read_text().strip(), known_good_payloads_intact=True, persistent_default='spx-known-good', next_entry_empty=True), indent=2) + '\n')
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
    assert source == 'DMIC1' or action in ('capture', 'feedback'), 'DMIC0 requires capture or feedback'


def arm_audio(args):
    """Queue one authorized initialization or microphone-monitored audio test."""
    action = 'initialize' if args.audio_action == 'plan' else args.audio_action
    source = getattr(args, 'microphone_source', 'DMIC1')
    validate_microphone_source(action, source)
    require_source_boot()
    recovery()
    assert args.allow_amp_power, 'explicit amplifier-power authorization required'
    assert action in ('initialize', 'feedback', 'desktop', 'serve', 'reopen')
    if action in ('feedback', 'desktop', 'serve', 'reopen'):
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
                       microphone_source=source,
                       allow_amp_power=True, playback=action in ('feedback', 'desktop', 'serve', 'reopen'),
                       capture=action in ('feedback', 'desktop', 'serve', 'reopen'),
                       serve_seconds=args.serve_seconds if action == 'serve' else None,
                       desktop_peak=args.desktop_peak if action == 'serve' else None,
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
    return (ready.get('boot_id') == boot and ready.get('release') == RELEASE and
            all(ready.get(key) is True for key in
                ('acoustic_passed', 'public_acoustic_passed', 'recording_closed')))


def quarantine_desktop_audio(boot):
    (OUT / 'desktop-audio.json').rename(OUT / ('desktop-audio-failed-' + boot + '.json'))
    print('Desktop opt-in quarantined after an unsuccessful or interrupted run; '
          'no automatic retry on this or a later boot.', flush=True)


def archive_audio_result(boot):
    """Retain small prior-boot evidence before the shared output is reused."""
    for name in ('serve-ready.json', 'serve-result.json'):
        source = OUT / 'audio' / name
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


def enable_desktop_audio(args):
    """Opt in only from the same verified, still-running desktop stream."""
    os.umask(0o077)
    boot = audio_boot()
    ready = json.loads((OUT / 'audio/serve-ready.json').read_text())
    assert desktop_ready(ready, boot)
    assert not ready.get('stopped') and ready['sink'] == 'spx_speakers'
    assert type(args.desktop_peak) is int and 1433 <= args.desktop_peak <= 12000
    assert ready['peak_limit'] == args.desktop_peak and ready['pa_gain'] == 0
    assert pwd.getpwnam(args.desktop_user).pw_uid != 0
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
                  desktop_peak=args.desktop_peak, verified_boot_id=boot)
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
    previous = record.get('last_start_boot_id')
    if previous and previous != boot:
        # If the wrapper was killed during startup it could not quarantine its
        # policy. Missing/mismatched readiness still prevents a blind next boot.
        try:
            ready = json.loads((OUT / 'audio/serve-ready.json').read_text())
            result = json.loads((OUT / 'audio/serve-result.json').read_text())
            passed = desktop_ready(ready, previous) and not result.get('error')
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
    args.allow_amp_power = args.allow_playback = args.allow_capture = True
    print('Starting bounded speaker tones and microphone verification; recording '
          'closes before desktop readiness. No continuous microphone capture.', flush=True)
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
    source = record.get('microphone_source', 'DMIC1')
    validate_microphone_source(record['action'], source)
    words = Path('/proc/cmdline').read_text().split()
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert record['attempt'] == ATTEMPT and record['release'] == os.uname().release
    assert record['preboot_id'] == BOOT_ID and boot_id != BOOT_ID
    assert 'spx_attempt=' + ATTEMPT in words and 'spx_audio=parked' in words
    assert record['action'] in ('initialize', 'feedback', 'desktop', 'serve', 'reopen') and record['allow_amp_power'] is True
    feedback = record['action'] in ('feedback', 'desktop', 'serve', 'reopen')
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
    args.microphone_source = source
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
    source = getattr(args, 'microphone_source', 'DMIC1')
    validate_microphone_source(action, source)
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
        if action in ('initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen'):
            from audio import UNITS as audio_units

            assert action in ('recover', 'capture') or args.allow_amp_power, 'this run needs explicit speaker-power authorization'
            assert action not in ('listen', 'feedback', 'desktop', 'serve', 'reopen') or args.allow_playback, 'this run needs explicit playback authorization'
            assert action not in ('capture', 'feedback', 'desktop', 'serve', 'reopen') or args.allow_capture, 'this run needs microphone authorization'
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
            if action in ('initialize', 'listen', 'feedback', 'desktop', 'serve', 'reopen'):
                command.append('--allow-amp-power')
            if action in ('listen', 'feedback', 'desktop', 'serve', 'reopen'):
                command.append('--allow-playback')
            if action in ('capture', 'feedback', 'desktop', 'serve', 'reopen'):
                command.append('--allow-capture')
            if action == 'serve':
                assert 0 <= args.serve_seconds <= 82800
                assert 1433 <= args.desktop_peak <= 12000
                command += ['--serve-seconds', str(args.serve_seconds),
                            '--desktop-peak', str(args.desktop_peak)]
        process = subprocess.Popen(command)
        try:
            status = process.wait(timeout=(args.serve_seconds + 120 if args.serve_seconds else None) if action == 'serve' else
                                  120 if action in ('feedback', 'desktop', 'reopen') else 90 if action == 'listen' else 40)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'install', 'boot', 'check', 'return', 'extend', 'audio', 'arm-audio', 'enable-desktop-audio', 'usbc-reload', 'wifi-band', 'display-power'))
    parser.add_argument('attempt')
    parser.add_argument('--build', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/work-build'))
    parser.add_argument('--parent', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bf'))
    parser.add_argument('--recovery', type=Path, default=Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf/working-recovery.json'))
    parser.add_argument('--dtb', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/spx.dtb'))
    parser.add_argument('--address')
    parser.add_argument('--wifi-profile', help='saved Wi-Fi profile ID to clone for the 2.4 GHz test')
    parser.add_argument('--audio', action='store_true', help='enable codecs with both amplifiers parked; no playback')
    parser.add_argument('--usbc', action='store_true',
                        help='load experimental USC-to-DP0 forwarding in the initramfs')
    parser.add_argument('--replace-module', action='append', default=[],
                        help='changed unloaded/blacklisted module to install while this release runs')
    parser.add_argument('--return-seconds', type=int, default=3600)
    parser.add_argument('--audio-action', choices=('plan', 'inspect', 'initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve', 'reopen'), default='plan')
    parser.add_argument('--serve-seconds', type=int, default=3600,
                        help='ordinary desktop playback after acoustic verification (0 until stopped, or 1..82800 seconds)')
    parser.add_argument('--desktop-peak', type=int, default=1433,
                        help='ordinary desktop digital peak cap (1433..12000); minimum PA gain remains fixed')
    parser.add_argument('--allow-amp-power', action='store_true')
    parser.add_argument('--allow-playback', action='store_true')
    parser.add_argument('--allow-capture', action='store_true')
    parser.add_argument('--microphone-source', choices=('DMIC0', 'DMIC1'), default='DMIC1',
                        help='bounded capture/feedback input (default: DMIC1)')
    parser.add_argument('--reuse-installed-modules', action='store_true',
                        help='retain current module tree for a command-line-only trial')
    parser.add_argument('--return-after-audio-seconds', type=int,
                        help='after a queued audio test, use the existing return timer after this delay (61..900)')
    parser.add_argument('--desktop-user', default='dvitali')
    args = parser.parse_args()
    if args.microphone_source != 'DMIC1' and (args.command not in ('audio', 'arm-audio') or
                                            args.audio_action not in ('capture', 'feedback')):
        parser.error('--microphone-source DMIC0 requires audio/arm-audio capture or feedback')
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
        assert args.address, '--address must name this installation, never a shared board address'
        BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        RELEASE = (args.build / 'include/config/kernel.release').read_text().strip()
        prepare(args)
    else:
        record = json.loads((OUT / 'prepared.json').read_text())
        BOOT_ID, RELEASE = record['preboot_id'], record['release']
        if args.command == 'check':
            lock = str(REPO / 'tools/spx/spx-lock')
            owner = 'functional-' + ATTEMPT
            subprocess.run([lock, 'acquire', 'device', owner], check=True)
            try:
                functional_check(args)
            finally:
                subprocess.run([lock, 'release', 'device', owner], check=True)
            dispatch_audio(args)
        else:
            {'install': install, 'boot': boot, 'return': return_to_default,
             'extend': extend_window, 'audio': audio_check, 'arm-audio': arm_audio,
             'usbc-reload': usbc_reload, 'wifi-band': wifi_band, 'display-power': display_power,
             'enable-desktop-audio': enable_desktop_audio}[args.command](args)


if __name__ == '__main__':
    main()
