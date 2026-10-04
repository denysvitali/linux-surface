#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble AR provider-only DTB, complete staged modules and private initramfs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import libfdt

STAGE = Path('/var/tmp/spx-mainline-trial-20261003ar')
RELEASE = '7.3.0-rc2-spx-mainline-20261003ar+'
PROVIDER = '/soc@0/spmi@c440000/pmic@1/regulators'
TOOLS = Path('/var/tmp/spx-dtschema-venv-20260915/bin')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(fdt, offset=0):
    result = {}
    try:
        prop = fdt.first_property_offset(offset)
        while True:
            value = fdt.get_property_by_offset(prop)
            result[value.name] = bytes(value).hex()
            prop = fdt.next_property_offset(prop)
    except libfdt.FdtException as error:
        assert error.err == -libfdt.NOTFOUND
    try:
        child = fdt.first_subnode(offset)
        while True:
            result[fdt.get_name(child)] = tree(fdt, child)
            child = fdt.next_subnode(child)
    except libfdt.FdtException as error:
        assert error.err == -libfdt.NOTFOUND
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-dt-fix', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    assert os.geteuid() == 0
    if args.resume_dt_fix:
        previous = STAGE / 'initial-provider-assembly-failure'
        hashes = json.loads((previous / 'sha256.json').read_text())
        for name, digest in hashes.items():
            assert sha(previous / name) == digest, name
        assert not (STAGE / 'module-root').exists() and not (STAGE / 'initramfs.img').exists()
        assert not (STAGE / 'assembly-retry-started.json').exists()
    else:
        assert not (STAGE / 'assembly-started.json').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
        '991a6fbd-2217-4f93-8185-287a223a13f6'
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 193
    assert built['source_snapshot_unchanged'] and built['base_dtb_only_touch_delay_delta']
    marker = 'assembly-retry-started.json' if args.resume_dt_fix else 'assembly-started.json'
    (STAGE / marker).write_text(json.dumps({'started': time.time()}) + '\n')
    source, build = STAGE / 'source', STAGE / 'work-build'
    dt = STAGE / 'dtb-build'
    dt.mkdir(exist_ok=args.resume_dt_fix)
    records = []

    def run(args, log, cwd=source):
        start = time.monotonic()
        with (STAGE / log).open('wb') as stream:
            result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        records.append({'command': args, 'cwd': str(cwd), 'exit_code': result.returncode,
                        'seconds': round(time.monotonic() - start, 2), 'log': log})
        (STAGE / 'assembly-commands.json').write_text(json.dumps(records, indent=2) + '\n')
        assert result.returncode == 0, log
        print(log, 'passed', flush=True)

    fragment = source / 'tools/spx/boot-diagnostics/camera-power-20261003/spx-camera-regulators-disabled.dtsi'
    shutil.copy2(fragment, dt / fragment.name)
    base = libfdt.Fdt((STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb').read_bytes())
    rpmh = base.path_offset('/soc@0/rsc@18200000/pmc8180-a-rpmh-regulators')
    pins = []
    for supply in ('vdd-l1-l8-l11-supply', 'vdd-l7-l12-l14-l15-supply', 'vdd-l13-l16-l17-supply'):
        handle = base.getprop(rpmh, supply).as_uint32()
        target = base.get_path(base.node_offset_by_phandle(handle))
        pins.append(f'&{{{target}}} {{ phandle = <0x{handle:x}>; }};\n')
    # Keep the three newly referenced providers' existing IDs. Otherwise DTC
    # assigns them earlier and renumbers unrelated late-allocated phandles.
    (dt / 'provider.dts').write_text('#include "sc8180x-surface-pro-x.dts"\n' +
        ''.join(pins) + '#include "spx-camera-regulators-disabled.dtsi"\n'
        '&spx_camera_regulators { status = "okay"; };\n')
    run(['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
         '-I', str(source / 'include'), '-I', str(source / 'scripts/dtc/include-prefixes'),
         '-I', str(source / 'arch/arm64/boot/dts/qcom'), '-I', str(dt),
         str(dt / 'provider.dts'), '-o', str(dt / 'provider.pre.dts')], 'provider-cpp.log')
    run([str(build / 'scripts/dtc/dtc'), '-I', 'dts', '-O', 'dtb', '-H', 'epapr',
         '-o', str(dt / 'spx.dtb'), str(dt / 'provider.pre.dts')], 'provider-dtc.log')
    candidate = libfdt.Fdt((dt / 'spx.dtb').read_bytes())
    actual = tree(candidate)
    provider = actual['soc@0']['spmi@c440000']['pmic@1'].pop('regulators')
    assert actual == tree(base), 'DT delta exceeds the single provider subtree'
    assert candidate.num_mem_rsv() == base.num_mem_rsv()
    for n in range(base.num_mem_rsv()):
        assert candidate.get_mem_rsv(n) == base.get_mem_rsv(n)
    assert provider['compatible'] == b'qcom,pmc8180-regulators\0'.hex()
    assert provider['status'] == b'okay\0'.hex()
    assert set(provider) == {'compatible', 'status', 'vdd_l1_l8_l11-supply',
                            'vdd_l7_l12_l14_l15-supply', 'vdd_l13_l16_l17-supply',
                            'l1', 'l14', 'l17'}
    for name, voltage in [('l1', 1200000), ('l14', 1800000), ('l17', 2856000)]:
        assert set(provider[name]) == {'regulator-name', 'regulator-min-microvolt', 'regulator-max-microvolt'}
        assert provider[name]['regulator-min-microvolt'] == voltage.to_bytes(4, 'big').hex()
        assert provider[name]['regulator-max-microvolt'] == voltage.to_bytes(4, 'big').hex()
    schema = dt / 'schema/regulator'
    schema.mkdir(parents=True, exist_ok=args.resume_dt_fix)
    for name in ('regulator.yaml', 'qcom,spmi-regulator.yaml', 'fixed-regulator.yaml'):
        shutil.copy2(source / 'Documentation/devicetree/bindings/regulator' / name, schema / name)
    run([str(TOOLS / 'dt-validate'), '-s', str(schema.parent), '-l',
         'qcom,spmi-regulator', str(dt / 'spx.dtb')], 'provider-schema.log')
    assert not (STAGE / 'provider-schema.log').read_text().strip()
    run([str(TOOLS / 'dt-validate'), '-s', str(schema.parent), '-l',
         'fixed-regulator', str(dt / 'spx.dtb')], 'fixed-regulator-schema.log')
    assert not (STAGE / 'fixed-regulator-schema.log').read_text().strip()
    import review_aq_dtb_delta_ar
    parent = Path('/var/lib/spx-boot-diagnostics/attempts/20261003aq')
    timing = review_aq_dtb_delta_ar.compare((parent / 'dtb-build/spx.dtb').read_bytes(),
                                           (dt / 'spx.dtb').read_bytes())
    (dt / 'touch-delta-review.json').write_text(json.dumps(timing, indent=2) + '\n')
    assert sha(dt / 'spx.dtb') == 'fc567fd1a7593d9b5b430dee4edb7086f3ef3f71179dd2c304801c6b5e49bd3e'
    (dt / 'delta-review.json').write_text(json.dumps({
        'single_added_subtree': PROVIDER, 'other_nodes_properties_exact_ar_base': True,
        'memory_reservations_exact_ar_base': True, 'no_sensor_nodes_added': True,
        'no_boot_always_on_or_initial_mode': True, 'provider': provider,
        'base_sha256': sha(STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'),
        'provider_dtb_sha256': sha(dt / 'spx.dtb')}, indent=2) + '\n')
    make = ['make', '-C', str(source), 'O=' + str(build), 'ARCH=arm64', 'LOCALVERSION=+']
    run(make + ['-j4', 'INSTALL_MOD_PATH=' + str(STAGE / 'module-root'),
                'DEPMOD=true', 'modules_install'], 'modules-stage.log')
    root = STAGE / 'module-root/lib/modules' / RELEASE
    run(['depmod', '-b', str(STAGE / 'module-root'), '-ae', '-F',
         str(STAGE / 'artifacts/System.map'), RELEASE], 'depmod.log')
    assert not (STAGE / 'depmod.log').read_text().strip()
    shutil.copy2(STAGE / 'artifacts/arch/arm64/boot/Image', root / 'vmlinuz')
    manifest = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
                if p.is_file() and not p.is_symlink()}
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
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
        '991a6fbd-2217-4f93-8185-287a223a13f6'
    (STAGE / 'build-verification.json').write_text(json.dumps({
        'release': RELEASE, 'modules': 193, 'module_tree_files': 208,
        'embedded_modules': len(embedded), 'embedded_module_payloads_exact': True,
        'private_logger_exact': True, 'provider_only_dtb_delta_verified': True, 'only_touch_property_delta_from_aq': True,
        'boot_selected': False, 'deployed': False,
        'artifacts': {n: sha(STAGE / n) for n in ('vmlinuz', 'initramfs.img',
                      'dtb-build/spx.dtb', 'artifacts/.config')}}, indent=2) + '\n')
    os.sync()
    print('AR private payloads assembled and verified; no deployment or selection', flush=True)


if __name__ == '__main__':
    main()
