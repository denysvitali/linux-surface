#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One reusable SPX functional trial: fixed kernel build, prepare/install/boot/return."""
import argparse
from datetime import datetime, timezone
import hashlib
import gzip
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess

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
            'snd_soc_wsa881x.spx_write_only=', 'snd_soc_wcd934x.spx_persist_stream='))]
        cmdline += ['spx_audio=parked', 'wcd934x.spx_wsa_en_pin=-1',
                    'wcd934x.spx_wsa_gpio_mask=0x1e', 'wcd934x.spx_wsa_gpio_dir=0x1e',
                    'wcd934x.spx_wsa_gpio_val=0x18', 'soundwire_qcom.spx_force_attach=0',
                    'snd_soc_wsa881x.spx_enumerated_mode=1', 'snd_soc_wsa881x.spx_write_only=0',
                    'snd_soc_wcd934x.spx_persist_stream=1']
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
    check_service = '[Unit]\nDescription=SPX bounded functional checks\nConditionKernelCommandLine=spx_attempt=%i\nAfter=network-online.target bluetooth.service\nRequiresMountsFor=/var/lib/spx-boot-diagnostics\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -B /usr/local/lib/spx-boot-diagnostics/trial.py check %i\nTimeoutStartSec=90000\nTimeoutStopSec=20\n'
    check_timer = '[Unit]\nDescription=Run SPX functional checks after startup\nConditionKernelCommandLine=spx_attempt=%i\n\n[Timer]\nOnBootSec=50\nAccuracySec=1\nUnit=spx-trial-check@%i.service\n\n[Install]\nWantedBy=timers.target\n'
    for name, text in [('spx-trial-check@.service', check_service), ('spx-trial-check@.timer', check_timer)]:
        target = unit_dir / name
        previous = text.replace('TimeoutStartSec=90000\nTimeoutStopSec=20\n', 'TimeoutStartSec=180\n')
        assert not target.exists() or target.read_text() in (text, previous)
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

    for pattern in ('class/power_supply/*/uevent', 'class/thermal/thermal_zone*/type',
                    'class/thermal/thermal_zone*/temp', 'class/remoteproc/remoteproc*/name',
                    'class/remoteproc/remoteproc*/state', 'bus/iio/devices/iio:device*/name',
                    'bus/iio/devices/iio:device*/in_illuminance_raw',
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


def arm_audio(args):
    """Queue one authorized initialization or microphone-monitored audio test."""
    require_source_boot()
    recovery()
    assert args.allow_amp_power, 'explicit amplifier-power authorization required'
    action = 'initialize' if args.audio_action == 'plan' else args.audio_action
    assert action in ('initialize', 'feedback', 'desktop', 'serve')
    if action in ('feedback', 'desktop', 'serve'):
        assert args.allow_playback and args.allow_capture, 'feedback needs playback and capture authorization'
    if action == 'serve':
        assert 1 <= args.serve_seconds <= 82800
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
                       allow_amp_power=True, playback=action in ('feedback', 'desktop', 'serve'),
                       capture=action in ('feedback', 'desktop', 'serve'),
                       serve_seconds=args.serve_seconds if action == 'serve' else None,
                       return_after_audio_seconds=args.return_after_audio_seconds,
                       utc=datetime.now(timezone.utc).isoformat()), stream, indent=2)
        stream.write('\n')
    print('One audio ' + action + ' test queued for the selected trial boot', flush=True)


def requested_audio(args):
    request = OUT / 'audio-request.json'
    if not request.exists():
        return
    record = json.loads(request.read_text())
    words = Path('/proc/cmdline').read_text().split()
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert record['attempt'] == ATTEMPT and record['release'] == os.uname().release
    assert record['preboot_id'] == BOOT_ID and boot_id != BOOT_ID
    assert 'spx_attempt=' + ATTEMPT in words and 'spx_audio=parked' in words
    assert record['action'] in ('initialize', 'feedback', 'desktop', 'serve') and record['allow_amp_power'] is True
    feedback = record['action'] in ('feedback', 'desktop', 'serve')
    assert record['playback'] is feedback and record['capture'] is feedback
    if record['action'] == 'serve':
        assert type(record.get('serve_seconds')) is int and 1 <= record['serve_seconds'] <= 82800
    started = OUT / 'audio-started.json'
    assert not started.exists()
    # Consume before hardware access; restarting the checker cannot repeat it.
    request.rename(started)
    args.audio_action = record['action']
    args.allow_amp_power = True
    args.allow_playback = feedback
    args.allow_capture = feedback
    args.desktop_user = record['desktop_user']
    try:
        if args.audio_action == 'serve':
            args.serve_seconds = record['serve_seconds']
            # Keep the automatic return beyond verification and the requested
            # application session. A failed start still uses the short return
            # in finally; no per-attempt service is needed.
            args.return_seconds = int(float(Path('/proc/uptime').read_text().split()[0])) + args.serve_seconds + 180
            extend_window(args)
        audio_check(args)
    finally:
        for name, extra in [('kernel.log', ['-k']), ('journal.log', [])]:
            with (OUT / name).open('wb') as stream:
                subprocess.run(['journalctl', '-b', '--no-pager', '-o', 'short-monotonic'] + extra,
                               stdout=stream, check=True, timeout=30)
        delay = record.get('return_after_audio_seconds')
        if delay is None and record['action'] == 'serve':
            delay = 61
        if delay is not None:
            assert isinstance(delay, int) and 61 <= delay <= 900
            args.return_seconds = int(float(Path('/proc/uptime').read_text().split()[0])) + delay + 1
            extend_window(args)


def audio_check(args):
    action = args.audio_action
    command = ['python3', '-B', str(HERE / 'audio.py'), action,
               '--output', str(OUT / 'audio')]
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
        if action in ('initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve'):
            from audio import UNITS as audio_units

            assert action in ('recover', 'capture') or args.allow_amp_power, 'this run needs explicit speaker-power authorization'
            assert action not in ('listen', 'feedback', 'desktop', 'serve') or args.allow_playback, 'this run needs explicit playback authorization'
            assert action not in ('capture', 'feedback', 'desktop', 'serve') or args.allow_capture, 'this run needs microphone authorization'
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
            if action in ('initialize', 'listen', 'feedback', 'desktop', 'serve'):
                command.append('--allow-amp-power')
            if action in ('listen', 'feedback', 'desktop', 'serve'):
                command.append('--allow-playback')
            if action in ('capture', 'feedback', 'desktop', 'serve'):
                command.append('--allow-capture')
            if action == 'serve':
                assert 1 <= args.serve_seconds <= 82800
                command += ['--serve-seconds', str(args.serve_seconds)]
        process = subprocess.Popen(command)
        try:
            status = process.wait(timeout=args.serve_seconds + 120 if action == 'serve' else
                                  120 if action in ('feedback', 'desktop') else 90 if action == 'listen' else 40)
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
    parser.add_argument('command', choices=('prepare', 'install', 'boot', 'check', 'return', 'extend', 'audio', 'arm-audio'))
    parser.add_argument('attempt')
    parser.add_argument('--build', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/work-build'))
    parser.add_argument('--parent', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bf'))
    parser.add_argument('--recovery', type=Path, default=Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf/working-recovery.json'))
    parser.add_argument('--dtb', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/spx.dtb'))
    parser.add_argument('--address')
    parser.add_argument('--audio', action='store_true', help='enable codecs with both amplifiers parked; no playback')
    parser.add_argument('--replace-module', action='append', default=[],
                        help='changed unloaded/blacklisted module to install while this release runs')
    parser.add_argument('--return-seconds', type=int, default=3600)
    parser.add_argument('--audio-action', choices=('plan', 'inspect', 'initialize', 'listen', 'recover', 'capture', 'feedback', 'desktop', 'serve'), default='plan')
    parser.add_argument('--serve-seconds', type=int, default=3600,
                        help='ordinary desktop playback window after acoustic verification (1..82800)')
    parser.add_argument('--allow-amp-power', action='store_true')
    parser.add_argument('--allow-playback', action='store_true')
    parser.add_argument('--allow-capture', action='store_true')
    parser.add_argument('--reuse-installed-modules', action='store_true',
                        help='retain current module tree for a command-line-only trial')
    parser.add_argument('--return-after-audio-seconds', type=int,
                        help='after a queued audio test, use the existing return timer after this delay (61..900)')
    parser.add_argument('--desktop-user', default='dvitali')
    args = parser.parse_args()
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
            requested_audio(args)
        else:
            {'install': install, 'boot': boot, 'return': return_to_default,
             'extend': extend_window, 'audio': audio_check, 'arm-audio': arm_audio}[args.command](args)


if __name__ == '__main__':
    main()
