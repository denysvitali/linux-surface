#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble AU modules/private initrd, preserving AT's reviewed camera DTB."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

STAGE = Path('/var/tmp/spx-mainline-trial-20261003au')
PARENT = Path('/var/tmp/spx-mainline-trial-20261003ar')
AT = Path('/var/lib/spx-boot-diagnostics/attempts/20261003at')
RELEASE = '7.3.0-rc2-spx-mainline-20261003au+'
BOOT = '74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 193
    assert built['source_snapshot_unchanged'] and built['embedded_config_exact']
    assert built['base_dtb_exact_ar']
    assert not (STAGE / 'assembly-started.json').exists()
    (STAGE / 'assembly-started.json').write_text(json.dumps({'started': time.time()}) + '\n')
    shutil.copy2(__file__, STAGE / 'assemble-au.py')
    commands = []
    source, build = STAGE / 'source', STAGE / 'work-build'

    def run(args, log, cwd=source):
        start = time.monotonic()
        with (STAGE / log).open('xb') as stream:
            result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        commands.append({'command': args, 'cwd': str(cwd), 'exit_code': result.returncode,
                         'seconds': round(time.monotonic() - start, 2), 'log': log})
        (STAGE / 'assembly-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, log
        print(log, 'passed', flush=True)

    # Camera topology is an exact historical artifact, not regenerated or relabeled.
    assert sha(AT / 'dtb-build/spx.dtb') == '50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c'
    historical = json.loads((AT / 'dtb-sha256.json').read_text())
    assert files(AT / 'dtb-build') == historical
    shutil.copytree(AT / 'dtb-build', STAGE / 'dtb-build')
    shutil.copy2(AT / 'dtb-sha256.json', STAGE / 'dtb-sha256.json')
    shutil.copy2(AT / 'dt-input-files-sha256.json', STAGE / 'dt-input-files-sha256.json')
    inputs = json.loads((STAGE / 'dt-input-files-sha256.json').read_text())
    for name, digest in inputs.items():
        assert sha(source / name) == digest, name
    (STAGE / 'dt-provenance.json').write_text(json.dumps({
        'origin_attempt': '20261003at', 'origin_manifest_sha256': sha(AT / 'dtb-sha256.json'),
        'candidate_dtb_sha256': sha(STAGE / 'dtb-build/spx.dtb'),
        'exact_at_tree_preserved': True, 'compiled_base_dtb_exact_ar': True,
        'new_camera_stream_or_receiver_power_enabled': False}, indent=2) + '\n')
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / name, STAGE / name, symlinks=True)
    shutil.copy2(PARENT / 'mkinitcpio.conf', STAGE / 'mkinitcpio.conf')
    for path in (STAGE / 'initcpio/install/spx_diagnostics', STAGE / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace('20261003ar', '20261003au'))
    assert str(STAGE / 'logging') in (STAGE / 'initcpio/install/spx_diagnostics').read_text()
    make = ['make', '-C', str(source), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run(make + ['-j4', 'INSTALL_MOD_PATH=' + str(STAGE / 'module-root'),
                'DEPMOD=true', 'modules_install'], 'modules-stage.log')
    root = STAGE / 'module-root/lib/modules' / RELEASE
    run(['depmod', '-b', str(STAGE / 'module-root'), '-ae', '-F',
         str(STAGE / 'artifacts/System.map'), RELEASE], 'depmod.log')
    assert not (STAGE / 'depmod.log').read_text().strip()
    shutil.copy2(STAGE / 'artifacts/arch/arm64/boot/Image', root / 'vmlinuz')
    manifest = files(root)
    assert len(manifest) == 208
    (STAGE / 'module-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    vermagic = {}
    for module in sorted(root.rglob('*.ko')):
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
        assert value.split()[0] == RELEASE
        vermagic[str(module.relative_to(root))] = value
    assert len(vermagic) == 193
    (STAGE / 'module-vermagic.json').write_text(json.dumps(vermagic, indent=2) + '\n')
    run(['mkinitcpio', '-k', RELEASE, '-r', str(STAGE / 'module-root'),
         '-c', str(STAGE / 'mkinitcpio.conf'), '-D', str(STAGE / 'initcpio'),
         '-D', '/etc/initcpio', '-D', '/usr/lib/initcpio', '-g',
         str(STAGE / 'initramfs.img'), '--nopost'], 'initramfs-build.log')
    extract = STAGE / 'initramfs-extracted'
    extract.mkdir()
    run(['lsinitcpio', '-x', str(STAGE / 'initramfs.img')], 'initramfs-extract.log', cwd=extract)
    assert sha(extract / 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == sha(STAGE / 'logging/initrd-log.sh')
    embedded = sorted(extract.rglob('*.ko'))
    assert len(embedded) == 54
    prefix = 'usr/lib/modules/' + RELEASE + '/'
    for module in embedded:
        name = str(module.relative_to(extract))
        assert name.startswith(prefix) and sha(module) == manifest[name[len(prefix):]]
    assert sha(build / '.config') == built['config_sha256']
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    (STAGE / 'build-verification.json').write_text(json.dumps({
        'release': RELEASE, 'modules': 193, 'module_tree_files': 208,
        'embedded_modules': len(embedded), 'embedded_module_payloads_exact': True,
        'private_logger_exact': True, 'exact_at_dtb_preserved': True,
        'boot_selected': False, 'deployed': False,
        'artifacts': {n: sha(STAGE / n) for n in ('vmlinuz', 'initramfs.img',
                      'dtb-build/spx.dtb', 'artifacts/.config')}}, indent=2) + '\n')
    os.sync()
    print('AU private payloads assembled and verified; no deployment or selection', flush=True)


if __name__ == '__main__':
    main()
