#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble and verify BF payloads with BE's exact static boot DTB."""
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
import be_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004bf')
PARENT = Path('/var/tmp/spx-mainline-trial-20261004bc')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 202
    assert built['source_snapshot_unchanged'] and built['embedded_config_exact']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    a = g.load()
    assert a['state'].startswith('BE terminal;') and not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    bf = g.BASE / 'attempts/20261004bf'
    assert g.sha(bf / 'build-sha256.json') == '0faf4fa9c249d139319f5dc1ca7d33cfc9be2825455c9ec7b64b78c22211cf7e'
    assert g.files(bf / 'build') == json.loads((bf / 'build-sha256.json').read_text())
    assert g.sha(bf / 'build-review.json') == '2b35e937da781140297bf1e927a309409c5c6a9ef13e3b539cf03e166e9dcd81'
    import importlib.util
    spec = importlib.util.spec_from_file_location('bf_build', Path(__file__).with_name('build-bf.py'))
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    diagnostic = json.loads((g.X / 'offline-venus-startup-diag-20261004/report.json').read_text())
    assert b.live_source(diagnostic) == 84669
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'video-power-20261003'))
    import video_dt_contract as contract
    assert contract.EXPECTED['memory-region'] == [('/reserved-memory/video-firmware', [])]
    contract.EXPECTED['memory-region'] = [('/reserved-memory/video-firmware@8d300000', [])]
    import libfdt
    parent_dt = g.X / 'dtb-build'
    expected_dt = json.loads((g.X / 'dtb-sha256.json').read_text())
    assert len(expected_dt) == 39 and g.files(parent_dt) == expected_dt
    dtroot = STAGE / 'dtb-build'
    shutil.copytree(parent_dt, dtroot, symlinks=True)
    assert g.files(dtroot) == expected_dt
    raw_name = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
    raw = STAGE / 'artifacts' / raw_name
    assert raw.read_bytes() == (parent_dt / 'raw-after.dtb').read_bytes()
    assert g.sha(raw) == '0b86a7f1d18f19f281cf880c5cf5159ff2711116b1f51fe56aa5ad361ecd8928'
    assert (dtroot / 'spx.dtb').read_bytes() == (parent_dt / 'spx.dtb').read_bytes()
    assert g.sha(dtroot / 'spx.dtb') == '2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252'
    results = {}
    for label, path in [('raw', raw), ('retained', dtroot / 'spx.dtb')]:
        results[label] = contract.validate(path.read_bytes())
        fdt = libfdt.Fdt(path.read_bytes())
        mem = fdt.path_offset('/reserved-memory/video-firmware@8d300000')
        import struct
        assert bytes(fdt.getprop(mem, 'reg')) == struct.pack('>4I', 0, 0x8d300000, 0, 0x500000)
        assert bytes(fdt.getprop(mem, 'no-map')) == b''
    (STAGE / 'assembly-provider-contracts.json').write_text(json.dumps(results, indent=2) + '\n')
    (STAGE / 'assembly-started.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat())) + '\n')
    shutil.copy2(__file__, STAGE / 'assemble-bf.py')
    for name in ('logging', 'initcpio'):
        shutil.copytree(PARENT / name, STAGE / name, symlinks=True)
    shutil.copy2(PARENT / 'mkinitcpio.conf', STAGE / 'mkinitcpio.conf')
    for path in (STAGE / 'initcpio/install/spx_diagnostics', STAGE / 'mkinitcpio.conf'):
        path.write_text(path.read_text().replace('20261004bc', '20261004bf'))
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
    g.artifacts(a)
    assert b.live_source(diagnostic) == 84669
    assert g.files(bf / 'build') == json.loads((bf / 'build-sha256.json').read_text())
    (STAGE / 'build-verification.json').write_text(json.dumps(dict(
        utc=datetime.now(timezone.utc).isoformat(), release=RELEASE, modules=202, module_tree_files=217,
        embedded_modules=55, embedded_module_payloads_exact=True, private_logger_exact=True,
        videocc_provider_module_verified=True, actual_of_fallback_alias_resolves=True,
        boot_dtb_exact_parent_be=True, raw_compiled_board_dtb_exact_parent_be=True,
        provider_argument_counts_and_interconnect_tags_verified=True,
        prior_boot_tree_property_values_exact=True, prior_boot_tree_memory_reservations_exact=True, boot_selected=False, deployed=False,
        artifacts={name: g.sha(STAGE / name) for name in (
            'vmlinuz', 'initramfs.img', 'dtb-build/spx.dtb', 'artifacts/.config')}), indent=2) + '\n')
    os.sync()
    print('BF private payloads assembled; no installation or boot selection', flush=True)


if __name__ == '__main__':
    main()
