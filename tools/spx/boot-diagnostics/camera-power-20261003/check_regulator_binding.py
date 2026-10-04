#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the direct provider, measured constraints and upstream wiring offline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import libfdt

REPO = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
TOOLS = Path('/var/tmp/spx-dtschema-venv-20260915/bin')
PROVIDER = '/soc@0/spmi@c440000/pmic@1/regulators'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    records = []

    def run(name, command):
        r = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=40)
        output = r.stdout + r.stderr
        (work / (name + '.log')).write_text(output)
        records.append({'name': name, 'command': command, 'returncode': r.returncode})
        assert r.returncode == 0, output
        return output

    schema = work / 'schema/regulator'
    schema.mkdir(parents=True, exist_ok=True)
    for name in ('qcom,spmi-regulator.yaml', 'regulator.yaml'):
        shutil.copy2(REPO / 'Documentation/devicetree/bindings/regulator' / name, schema / name)
    assert not run('doc', [str(TOOLS / 'dt-doc-validate'),
                           str(schema / 'qcom,spmi-regulator.yaml')]).strip()
    dts = work / 'provider.dts'
    dts.write_text('#include "sc8180x-surface-pro-x.dts"\n'
                   '#include "spx-camera-regulators-disabled.dtsi"\n')
    pre = work / 'provider.pre.dts'
    run('cpp', ['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x',
                'assembler-with-cpp', '-I', str(REPO / 'include'), '-I',
                str(REPO / 'scripts/dtc/include-prefixes'), '-I',
                str(REPO / 'arch/arm64/boot/dts/qcom'), '-I', str(HERE),
                str(dts), '-o', str(pre)])
    dtb = work / 'provider.dtb'
    run('dtc', ['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(dtb), str(pre)])
    raw = dtb.read_bytes()
    fdt = libfdt.Fdt(raw)
    provider = fdt.path_offset(PROVIDER)
    rpmh = fdt.path_offset('/soc@0/rsc@18200000/pmc8180-a-rpmh-regulators')
    upstream = [('vdd_l1_l8_l11-supply', 'vdd-l1-l8-l11-supply'),
                ('vdd_l7_l12_l14_l15-supply', 'vdd-l7-l12-l14-l15-supply'),
                ('vdd_l13_l16_l17-supply', 'vdd-l13-l16-l17-supply')]
    for direct, existing in upstream:
        assert bytes(fdt.getprop(provider, direct)) == bytes(fdt.getprop(rpmh, existing))
    for name, voltage in [('l1', 1200000), ('l14', 1800000), ('l17', 2856000)]:
        node = fdt.path_offset(PROVIDER + '/' + name)
        assert fdt.getprop(node, 'regulator-min-microvolt').as_uint32() == voltage
        assert fdt.getprop(node, 'regulator-max-microvolt').as_uint32() == voltage
        for prop in ('regulator-always-on', 'regulator-boot-on', 'regulator-initial-mode'):
            try:
                fdt.getprop(node, prop)
            except libfdt.FdtException:
                pass
            else:
                raise AssertionError(prop)
    for name in ('ldo1', 'ldo14', 'ldo17'):
        try:
            fdt.subnode_offset(rpmh, name)
        except libfdt.FdtException:
            pass
        else:
            raise AssertionError('Duplicate RPMh control: ' + name)

    def mutate(name, changes):
        f = libfdt.Fdt(raw)
        f.resize(len(raw) + 4096)
        node = f.path_offset(PROVIDER)
        f.setprop(node, 'status', b'okay\0')
        for relative, prop, val in changes:
            target = f.path_offset(PROVIDER + relative)
            f.setprop(target, prop, val)
        path = work / (name + '.dtb')
        path.write_bytes(f.as_bytearray())
        return path

    def validate(name, path):
        return run(name, [str(TOOLS / 'dt-validate'), '-s', str(schema.parent), '-l',
                          'qcom,spmi-regulator', str(path)])

    for name, path in [('disabled', dtb), ('enabled-offline', mutate('enabled-offline', []))]:
        output = validate(name, path)
        assert 'qcom,pmc8180-regulators' not in output, output
    for name, changes in [
        ('bad-pin-control', [('/l1', 'qcom,pin-ctrl-enable', b'\0\0\0\x10')]),
        ('unknown-input', [('', 'vdd_guessed-supply', b'\0' * 4)]),
    ]:
        output = validate(name, mutate(name, changes))
        assert 'regulators' in output, output
    (work / 'result.json').write_text(json.dumps({
        'status': 'Offline provider validation passed', 'commands': records,
        'upstream_phandles_match_existing_board': True,
        'duplicate_rpmh_camera_nodes_absent': True,
        'measured_voltage_constraints_match': True,
        'provider_disabled': True, 'runtime_actions': [],
        'positive_cases': 2, 'negative_cases': 2,
        'dtb_sha256': hashlib.sha256(raw).hexdigest()}, indent=2) + '\n')
    print('Provider schema, upstream phandles, three measured constraints and no duplicate RPMh consumers verified')


if __name__ == '__main__':
    main()
