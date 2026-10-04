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
import re
import shutil
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


def prepare(args):
    os.umask(63)
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
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
    cmdline.append('module_blacklist=wcd934x,soundwire_qcom,snd_soc_wsa881x,snd_soc_wcd934x')
    cmdline = ' '.join(cmdline)
    entry = (OLD / 'entry.cfg').read_text().replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT))
    entry = entry.replace(previous['cmdline'].replace('20261004bf', '{ATTEMPT}'.format(ATTEMPT=ATTEMPT)), cmdline)
    entry = entry.replace('bounded Venus core startup and Iris1 startup trial', 'Bluetooth address and functional hardware tests')
    (OUT / 'entry.cfg').write_text(entry)
    run('grub-syntax', ['grub-script-check', str(OUT / 'entry.cfg')])
    prepared = dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=BOOT_ID, release=RELEASE, attempt=ATTEMPT, entry='spx-trial-' + ATTEMPT, cmdline=cmdline, source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), build_directory=str(BUILD), private_config=str(OUT / 'kernel.config'), bluetooth_address=args.address, address_is_per_installation=True, venus_trial=False, speaker_drivers_blocked=True, hardware_acceptance_closed=False, installed=False, boot_selected=False, boot_payloads=dict(vmlinuz=sha(OUT / 'vmlinuz'), initramfs=sha(OUT / 'initramfs.img'), dtb=sha(OUT / 'spx.dtb')))
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
    helper = Path('/usr/local/lib/spx-boot-diagnostics/trial.py')
    shutil.copy2(__file__, helper)
    helper.chmod(493)
    subprocess.run(['systemd-analyze', 'verify', str(unit_dir / ('spx-trial-return@' + ATTEMPT + '.service')), str(unit_dir / ('spx-trial-return@' + ATTEMPT + '.timer'))], check=True, timeout=30)
    if modules.exists():
        assert os.uname().release != RELEASE
        shutil.rmtree(modules)
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
    assert subprocess.check_output(['systemctl', 'is-enabled', 'spx-trial-return@' + ATTEMPT + '.timer'], text=True).strip() == 'enabled'
    recovery()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    installed = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT_ID, release=RELEASE, source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), boot_payloads=expected, persistent_default='spx-known-good', next_entry_empty=True, return_timer_seconds=900, installed=True, boot_selected=False)
    (OUT / 'installed.json').write_text(json.dumps(installed, indent=2) + '\n')
    os.sync()
    print(ATTEMPT + ' installed with900s return; known-good default retained, no selection', flush=True)


def boot(args):
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
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
    assert subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=REPO, text=True).strip() == ''
    selected.write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=BOOT_ID, entry=prepared['entry'], source_commit=installed['source_commit'], select_once=True), indent=2) + '\n')
    subprocess.run(['grub-reboot', prepared['entry']], check=True)
    recovery(pending=prepared['entry'])
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    os.sync()
    subprocess.run(['systemctl', 'reboot'], check=True)


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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'install', 'boot', 'return'))
    parser.add_argument('attempt')
    parser.add_argument('--build', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/work-build'))
    parser.add_argument('--parent', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bf'))
    parser.add_argument('--recovery', type=Path, default=Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf/working-recovery.json'))
    parser.add_argument('--dtb', type=Path, default=Path('/var/tmp/spx-mainline-trial-20261004bg/spx.dtb'))
    parser.add_argument('--address')
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
        {'install': install, 'boot': boot, 'return': return_to_default}[args.command](args)


if __name__ == '__main__':
    main()
