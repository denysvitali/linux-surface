#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble and verify AY's private module tree, initramfs and codec boot DTB."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ax_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261003ay')
PARENT = Path('/var/tmp/spx-mainline-trial-20261003ax')
RELEASE = '7.3.0-rc2-spx-mainline-20261003ay+'
BOOT = 'b6b4f20b-376f-4577-b282-677ad4ae0ec8'


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 201
    assert built['source_snapshot_unchanged'] and built['embedded_config_exact']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    dt = json.loads((STAGE / 'dtb-build/result.json').read_text())
    assert dt['all_existing_property_values_exact'] and dt['all_existing_memory_reservations_exact']
    assert g.sha(STAGE / 'dtb-build/spx.dtb') == dt['candidate_dtb_sha256']
    assert g.files(STAGE / 'dtb-build') == json.loads((STAGE / 'dtb-build/sha256.json').read_text()) | {
        'sha256.json': g.sha(STAGE / 'dtb-build/sha256.json')}
    (STAGE / 'assembly-started.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat())) + '\n')
    shutil.copy2(__file__, STAGE / 'assemble-ay.py')
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / name, STAGE / name, symlinks=True)
    shutil.copy2(PARENT / 'mkinitcpio.conf', STAGE / 'mkinitcpio.conf')
    for path in (STAGE / 'initcpio/install/spx_diagnostics', STAGE / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace('20261003ax', '20261003ay'))
    assert str(STAGE / 'logging') in (STAGE / 'initcpio/install/spx_diagnostics').read_text()
    source, build = STAGE / 'source', STAGE / 'work-build'
    commands = []

    def run(label, argv, cwd=source):
        start = time.monotonic()
        with (STAGE / (label + '.log')).open('xb') as stream:
            result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        commands.append(dict(label=label, argv=argv, cwd=str(cwd), exit_code=result.returncode,
                             seconds=round(time.monotonic() - start, 3)))
        (STAGE / 'assembly-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, label
        print(json.dumps(commands[-1]), flush=True)

    make = ['make', '-C', str(source), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run('modules-stage', make + ['-j4', 'INSTALL_MOD_PATH=' + str(STAGE / 'module-root'),
                                 'DEPMOD=true', 'modules_install'])
    root = STAGE / 'module-root/lib/modules' / RELEASE
    run('depmod', ['depmod', '-b', str(STAGE / 'module-root'), '-ae', '-F',
                   str(STAGE / 'artifacts/System.map'), RELEASE])
    assert not (STAGE / 'depmod.log').read_text().strip()
    shutil.copy2(STAGE / 'artifacts/arch/arm64/boot/Image', root / 'vmlinuz')
    manifest = g.files(root)
    assert len(manifest) == 216
    (STAGE / 'module-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    vermagic = {}
    for module in sorted(root.rglob('*.ko')):
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
        assert value.split()[0] == RELEASE
        vermagic[str(module.relative_to(root))] = value
    assert len(vermagic) == 201
    (STAGE / 'module-vermagic.json').write_text(json.dumps(vermagic, indent=2) + '\n')
    run('initramfs-build', ['mkinitcpio', '-k', RELEASE, '-r', str(STAGE / 'module-root'),
                           '-c', str(STAGE / 'mkinitcpio.conf'), '-D', str(STAGE / 'initcpio'),
                           '-D', '/etc/initcpio', '-D', '/usr/lib/initcpio', '-g',
                           str(STAGE / 'initramfs.img'), '--nopost'])
    extract = STAGE / 'initramfs-extracted'
    extract.mkdir()
    run('initramfs-extract', ['lsinitcpio', '-x', str(STAGE / 'initramfs.img')], cwd=extract)
    assert g.sha(extract / 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == g.sha(STAGE / 'logging/initrd-log.sh')
    embedded = sorted(extract.rglob('*.ko'))
    assert len(embedded) == 54
    prefix = 'usr/lib/modules/' + RELEASE + '/'
    for module in embedded:
        name = str(module.relative_to(extract))
        assert name.startswith(prefix) and g.sha(module) == manifest[name[len(prefix):]]
    assert g.sha(build / '.config') == built['config_sha256']
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert not g.recovery(a).get('next_entry', '')
    (STAGE / 'build-verification.json').write_text(json.dumps(dict(
        utc=datetime.now(timezone.utc).isoformat(), release=RELEASE, modules=201, module_tree_files=216,
        embedded_modules=54, embedded_module_payloads_exact=True, private_logger_exact=True,
        prior_boot_tree_property_values_exact=True, boot_selected=False, deployed=False,
        artifacts={name: g.sha(STAGE / name) for name in (
            'vmlinuz', 'initramfs.img', 'dtb-build/spx.dtb', 'artifacts/.config')}), indent=2) + '\n')
    os.sync()
    print('AY private payloads assembled; no installation or boot selection', flush=True)


if __name__ == '__main__':
    main()
