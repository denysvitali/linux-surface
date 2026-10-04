#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare the already compiling BG kernel for a small functional test boot."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
STAGE = Path('/var/tmp/spx-mainline-trial-20261004bg')
PARENT = Path('/var/tmp/spx-mainline-trial-20261004bf')
OLD = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf')
OUT = Path('/var/lib/spx-boot-diagnostics/functional/20261004bg')
BOOT_ID = '42966575-e6ec-4698-83c2-80e5aeb07011'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bg+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def recovery():
    r = json.loads((OLD / 'working-recovery.json').read_text())
    for path, digest in r['payload_sha256'].items():
        assert sha(path) == digest, path
    cfg = Path('/boot/grub/grub.cfg').read_text()
    assert r['entry'] in cfg and 'set default="spx-known-good"' in cfg
    env = dict(line.split('=', 1) for line in subprocess.check_output(
        ['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines())
    assert env['saved_entry'] == 'spx-known-good' and not env.get('next_entry')
    assert 'BootNext:' not in subprocess.check_output(['efibootmgr'], text=True)
    return r


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    recovery()
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 202
    assert built['full_kernel_linked'] and built['loadable_modules_linked']
    assert built['venus_shared_alloc_actual_zero_default_0400']
    OUT.mkdir(parents=True, mode=0o700)
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
    make = ['make', '-C', str(STAGE / 'source'), 'O=' + str(STAGE / 'work-build'),
            'ARCH=arm64', 'LOCALVERSION=+']
    run('modules-install', make + ['-j4', 'INSTALL_MOD_PATH=' + str(module_root), 'DEPMOD=true', 'modules_install'])
    root = module_root / 'lib/modules' / RELEASE
    shutil.copy2(STAGE / 'artifacts/arch/arm64/boot/Image', root / 'vmlinuz')
    run('depmod', ['depmod', '-b', str(module_root), '-ae', '-F', str(STAGE / 'artifacts/System.map'), RELEASE])
    assert not (OUT / 'depmod.log').read_text().strip()
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / name, OUT / name, symlinks=True)
    shutil.copy2(PARENT / 'mkinitcpio.conf', OUT / 'mkinitcpio.conf')
    for path in (OUT / 'initcpio/install/spx_diagnostics', OUT / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace(str(PARENT), str(OUT)).replace('20261004bf', '20261004bg'))
    run('initramfs', ['mkinitcpio', '-k', RELEASE, '-r', str(module_root), '-c', str(OUT / 'mkinitcpio.conf'),
        '-D', str(OUT / 'initcpio'), '-D', '/etc/initcpio', '-D', '/usr/lib/initcpio',
        '-g', str(OUT / 'initramfs.img'), '--nopost'])
    run('bluetooth-address', ['/usr/bin/python3', '-B', str(REPO / 'tools/spx/bluetooth-address.py'),
        str(STAGE / 'spx.dtb'), str(OUT / 'spx.dtb'), '--address', 'CE:27:F9:D2:B6:C9'])
    previous = json.loads((OLD / 'attempt.json').read_text())
    cmdline = []
    for word in previous['cmdline'].split():
        if word.startswith(('spx_diag=', 'spx_gpu_profile=', 'spx_diag_window=', 'qcom_scm.spx_pas_diag=',
                            'qcom_scm.spx_pas_area_diag=', 'venus_core.spx_hfi_startup_diag=')):
            continue
        cmdline.append(word.replace('spx_attempt=20261004bf', 'spx_attempt=20261004bg')
                           .replace('spx_boot=mainline-trial', 'spx_boot=mainline-functional'))
    assert not any('spx_uc_shared_alloc' in word for word in cmdline)
    cmdline = ' '.join(cmdline)
    entry = (OLD / 'entry.cfg').read_text().replace('20261004bf', '20261004bg')
    entry = entry.replace(previous['cmdline'].replace('20261004bf', '20261004bg'), cmdline)
    entry = entry.replace('bounded Venus core startup and Iris1 startup trial', 'Bluetooth address and functional hardware tests')
    (OUT / 'entry.cfg').write_text(entry)
    run('grub-syntax', ['grub-script-check', str(OUT / 'entry.cfg')])
    prepared = dict(utc=datetime.now(timezone.utc).isoformat(), preboot_id=BOOT_ID, release=RELEASE,
        attempt='20261004bg', entry='spx-trial-20261004bg', cmdline=cmdline,
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        compiled_source_manifest=str(STAGE / 'source-files.json'), private_config=str(STAGE / 'artifacts/.config'),
        bluetooth_address='CE:27:F9:D2:B6:C9', address_is_per_installation=True,
        venus_trial=False, hardware_acceptance_closed=False, installed=False, boot_selected=False,
        boot_payloads=dict(vmlinuz=sha(STAGE / 'vmlinuz'), initramfs=sha(OUT / 'initramfs.img'), dtb=sha(OUT / 'spx.dtb')))
    recovery()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    (OUT / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    print('Private functional boot prepared; no boot selected', flush=True)


if __name__ == '__main__':
    main()
