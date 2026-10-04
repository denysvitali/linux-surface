#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble and verify BB payloads with BA's exact retained boot DTB."""
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
import ba_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004bb')
PARENT = Path('/var/tmp/spx-mainline-trial-20261004ba')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bb+'
BOOT = 'a824008e-cf43-4287-84f8-4e930fa41a06'


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 202
    assert built['source_snapshot_unchanged'] and built['embedded_config_exact']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'video-power-20261003'))
    from video_dt_contract import validate
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from review_aq_dtb_delta_ar import flatten
    import libfdt
    parent_dt = g.X / 'build/dtb-build'
    assert g.files(parent_dt) == json.loads((parent_dt / 'sha256.json').read_text()) | {
        'sha256.json': g.sha(parent_dt / 'sha256.json')}
    parser_path = Path(__file__).resolve().parent / 'video-power-20261003/video_dt_contract.py'
    assert g.sha(parser_path) == g.sha(parent_dt / 'video_dt_contract.py') == \
        'f7cd315978d0e95c97f19bf6d2fd8cad4da97621c72e46c1876c700b75abc3bc'
    dtroot = STAGE / 'dtb-build'
    shutil.copytree(parent_dt, dtroot, symlinks=True)
    assert g.files(dtroot) == json.loads((dtroot / 'sha256.json').read_text()) | {
        'sha256.json': g.sha(dtroot / 'sha256.json')}
    dt = json.loads((dtroot / 'result.json').read_text())
    assert dt['all_existing_property_values_exact'] and dt['all_existing_memory_reservations_exact']
    assert dt['provider_argument_counts_and_interconnect_tags_verified']
    validate((dtroot / 'spx.dtb').read_bytes())
    validate((STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb').read_bytes())
    old, new = flatten((parent_dt / 'spx.dtb').read_bytes()), flatten((dtroot / 'spx.dtb').read_bytes())
    assert set(old) == set(new)
    deltas = [(path, prop) for path in old for prop in set(old[path]) | set(new[path])
              if old[path].get(prop) != new[path].get(prop)]
    assert deltas == [], deltas
    assert (parent_dt / 'spx.dtb').read_bytes() == (dtroot / 'spx.dtb').read_bytes()
    assert g.sha(dtroot / 'spx.dtb') == '4d96be24498f39afc10db917d7be155ee4b0d8314bfdfec924ddf1131594f4a9'
    raw_name = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    assert (STAGE / 'artifacts' / raw_name).read_bytes() == (g.X / 'build/artifacts' / raw_name).read_bytes()
    assert g.sha(STAGE / 'artifacts' / raw_name) == '8f68dbfea9d04f9c3ba27125eefa4e77e02cf2a190830b6b2b015f226585a958'
    before, after = libfdt.Fdt((parent_dt / 'spx.dtb').read_bytes()), libfdt.Fdt((dtroot / 'spx.dtb').read_bytes())
    assert before.num_mem_rsv() == after.num_mem_rsv()
    assert all(before.get_mem_rsv(i) == after.get_mem_rsv(i) for i in range(before.num_mem_rsv()))
    (STAGE / 'assembly-started.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat())) + '\n')
    shutil.copy2(__file__, STAGE / 'assemble-bb.py')
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / name, STAGE / name, symlinks=True)
    shutil.copy2(PARENT / 'mkinitcpio.conf', STAGE / 'mkinitcpio.conf')
    for path in (STAGE / 'initcpio/install/spx_diagnostics', STAGE / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace('20261004ba', '20261004bb'))
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
    alias = 'of:Nclock-controllerT(null)Cqcom,sc8180x-videoccCqcom,sm8150-videocc'
    resolved = subprocess.check_output(['modprobe', '--resolve-alias', '-d',
        str(STAGE / 'module-root'), '-S', RELEASE, alias], text=True).splitlines()
    assert resolved == ['videocc_sm8150'], resolved
    (STAGE / 'videocc-alias-resolution.json').write_text(json.dumps(dict(
        modalias=alias, modules=resolved, hardware_probe_performed=False), indent=2) + '\n')
    shutil.copy2(STAGE / 'artifacts/arch/arm64/boot/Image', root / 'vmlinuz')
    manifest = g.files(root)
    assert len(manifest) == 217
    (STAGE / 'module-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    vermagic = {}
    for module in sorted(root.rglob('*.ko')):
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
        assert value.split()[0] == RELEASE
        vermagic[str(module.relative_to(root))] = value
    assert len(vermagic) == 202
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
    assert len(embedded) == 55
    prefix = 'usr/lib/modules/' + RELEASE + '/'
    for module in embedded:
        name = str(module.relative_to(extract))
        assert name.startswith(prefix) and g.sha(module) == manifest[name[len(prefix):]]
    assert g.sha(build / '.config') == built['config_sha256']
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert not g.recovery(a).get('next_entry', '')
    (STAGE / 'build-verification.json').write_text(json.dumps(dict(
        utc=datetime.now(timezone.utc).isoformat(), release=RELEASE, modules=202, module_tree_files=217,
        embedded_modules=55, embedded_module_payloads_exact=True, private_logger_exact=True,
        videocc_provider_module_verified=True, actual_of_fallback_alias_resolves=True,
        boot_dtb_exact_parent_ba=True, raw_compiled_board_dtb_exact_parent_ba=True,
        provider_argument_counts_and_interconnect_tags_verified=True,
        prior_boot_tree_property_values_exact=True, prior_boot_tree_memory_reservations_exact=True, boot_selected=False, deployed=False,
        artifacts={name: g.sha(STAGE / name) for name in (
            'vmlinuz', 'initramfs.img', 'dtb-build/spx.dtb', 'artifacts/.config')}), indent=2) + '\n')
    os.sync()
    print('BB private payloads assembled; no installation or boot selection', flush=True)


if __name__ == '__main__':
    main()
