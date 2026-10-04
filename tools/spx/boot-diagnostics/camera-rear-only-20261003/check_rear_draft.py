#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile and validate the disabled rear-only draft; no device operations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import libfdt

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
TOOLS = REPO / 'tools/spx/boot-diagnostics'
HERE = Path(__file__).resolve().parent
SOURCE = Path('/var/tmp/spx-mainline-trial-20261003ar/source')
DTC = Path('/var/tmp/spx-mainline-trial-20261003aq/work-build/scripts/dtc/dtc')
SCHEMA_TOOLS = Path('/var/tmp/spx-dtschema-venv-20260915/bin')
BASE = Path('/var/tmp/spx-touch-firmware-20261003/candidate.dtb')
DSL = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')
sys.path.insert(0, str(TOOLS))
from review_aq_dtb_delta_ar import flatten
sys.path.insert(0, str(TOOLS / 'camera-power-20261003'))
from audit_firmware import extract


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    out = args.output
    assert not out.exists()
    assert sha(DSL) == 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
    assert sha(BASE) == 'fc567fd1a7593d9b5b430dee4edb7086f3ef3f71179dd2c304801c6b5e49bd3e'
    out.mkdir()
    commands = []

    def run(args, log):
        with (out / log).open('xb') as stream:
            p = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT)
        commands.append({'command': args, 'log': log, 'exit_code': p.returncode})
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert p.returncode == 0, log

    before_raw = BASE.read_bytes()
    fdt = libfdt.Fdt(before_raw)
    before = flatten(before_raw)
    pins = []
    for path, properties in before.items():
        if 'phandle' in properties:
            value = int(properties['phandle'], 16)
            pins.append(f'&{{{path}}} {{ phandle = <0x{value:x}>; }};\n')
    fragment = 'spx-rear-identification-disabled.dtsi'
    shutil.copy2(HERE / fragment, out / fragment)
    shutil.copy2(TOOLS / 'camera-power-20261003/spx-camera-regulators-disabled.dtsi', out)
    (out / 'rear.dts').write_text('#include "sc8180x-surface-pro-x.dts"\n' + ''.join(pins) +
        '#include "spx-camera-regulators-disabled.dtsi"\n' +
        '&spx_camera_regulators { status = "okay"; };\n' + f'#include "{fragment}"\n')
    run(['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
         '-I', str(SOURCE / 'include'), '-I', str(SOURCE / 'scripts/dtc/include-prefixes'),
         '-I', str(SOURCE / 'arch/arm64/boot/dts/qcom'), '-I', str(out),
         str(out / 'rear.dts'), '-o', str(out / 'rear.pre.dts')], 'cpp.log')
    run([str(DTC), '-I', 'dts', '-O', 'dtb', '-H', 'epapr', '-o', str(out / 'rear.dtb'),
         str(out / 'rear.pre.dts')], 'dtc.log')
    after_raw = (out / 'rear.dtb').read_bytes()
    candidate = libfdt.Fdt(after_raw)
    after = flatten(after_raw)
    assert not set(before) - set(after)
    provider = '/soc@0/spmi@c440000/pmic@1/regulators'
    properties_added = []
    for path in before:
        left, right = before[path], dict(after[path])
        if path in ['/soc@0/clock-controller@ad00000', *(provider + '/' + n for n in ('l1', 'l14', 'l17'))]:
            assert 'phandle' not in left and 'phandle' in right
            properties_added.append(path + '/phandle')
            del right['phandle']
        assert left == right, path
    cci = '/soc@0/cci@ac4a000'
    rear = cci + '/i2c-bus@0/camera@10'
    new = set(after) - set(before)
    pinroot = '/soc@0/pinctrl@3100000/'
    allowed = {cci, cci + '/i2c-bus@0', rear, rear + '/port', rear + '/port/endpoint',
               *(pinroot + n for n in ('spx-rear-cci0-default-state', 'spx-rear-cci0-sleep-state',
                                       'spx-rear-mclk0-state', 'spx-rear-reset-state'))}
    assert new == allowed, sorted(new)
    for path in (cci, rear):
        assert after[path]['status'] == b'disabled\0'.hex()
    assert candidate.getprop(candidate.path_offset(cci), 'assigned-clock-rates').as_uint32() == 37500000
    clock = candidate.getprop(candidate.path_offset(cci), 'assigned-clocks')
    clock_values = [int.from_bytes(clock[n:n + 4], 'big') for n in range(0, len(clock), 4)]
    assert len(clock_values) == 2
    assert candidate.get_path(candidate.node_offset_by_phandle(clock_values[0])) == '/soc@0/clock-controller@ad00000'
    header = (SOURCE / 'include/dt-bindings/clock/qcom,sc8180x-camcc.h').read_text()
    import re
    expected = re.search(r'^#define\s+CAM_CC_CCI_0_CLK_SRC\s+(\d+)\s*$', header, re.M)
    assert expected and clock_values[1] == int(expected[1])
    for supply, node in (('dovdd', 'l14'), ('avdd', 'l17'), ('dvdd', 'l1')):
        handle = candidate.getprop(candidate.path_offset(rear), supply + '-supply').as_uint32()
        assert candidate.get_path(candidate.node_offset_by_phandle(handle)) == provider + '/' + node
    assert fdt.num_mem_rsv() == candidate.num_mem_rsv()
    assert all(fdt.get_mem_rsv(n) == candidate.get_mem_rsv(n) for n in range(fdt.num_mem_rsv()))
    schemas = out / 'schema'
    (schemas / 'media/i2c').mkdir(parents=True)
    for name, relative in [('ovti,ov13858.yaml', 'media/i2c/ovti,ov13858.yaml')]:
        shutil.copy2(HERE / name, schemas / relative)
    for relative in ('media/video-interface-devices.yaml', 'media/video-interfaces.yaml',
                     'i2c/qcom,i2c-cci.yaml', 'regulator/regulator.yaml',
                     'regulator/qcom,spmi-regulator.yaml', 'pinctrl/qcom,sc8180x-tlmm.yaml',
                     'pinctrl/qcom,tlmm-common.yaml', 'pinctrl/pinctrl.yaml', 'pinctrl/pinmux-node.yaml', 'pinctrl/pincfg-node.yaml', 'leds/leds-consumer.yaml'):
        target = schemas / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / 'Documentation/devicetree/bindings' / relative, target)
    run([str(SCHEMA_TOOLS / 'dt-doc-validate'), str(schemas / 'media/i2c/ovti,ov13858.yaml')], 'sensor-doc.log')
    assert not (out / 'sensor-doc.log').read_text().strip()
    selections = ('ovti,ov13858', 'qcom,i2c-cci', 'qcom,spmi-regulator', 'qcom,sc8180x-tlmm')
    baseline_log = 'baseline-tlmm-schema.log'
    run([str(SCHEMA_TOOLS / 'dt-validate'), '-s', str(schemas), '-l', 'qcom,sc8180x-tlmm',
         str(BASE)], baseline_log)
    baseline = (out / baseline_log).read_text().replace(str(BASE), '<DTB>')
    assert baseline.count('from schema $id:') == 7, baseline
    enabled = libfdt.Fdt(after_raw)
    enabled.resize(len(after_raw) + 4096)
    for path in (cci, rear):
        enabled.setprop(enabled.path_offset(path), 'status', b'okay\0')
    enabled.pack()
    (out / 'enabled-schema-fixture.dtb').write_bytes(enabled.as_bytearray())
    for mode, payload in [('disabled', out / 'rear.dtb'), ('enabled-fixture', out / 'enabled-schema-fixture.dtb')]:
        for selection in selections:
            log = mode + '-' + selection.replace(',', '-') + '-schema.log'
            run([str(SCHEMA_TOOLS / 'dt-validate'), '-s', str(schemas), '-l', selection,
                 str(payload)], log)
            text = (out / log).read_text()
            if selection == 'qcom,sc8180x-tlmm':
                assert text.replace(str(payload), '<DTB>') == baseline, log
            else:
                assert not text.strip(), log
    negatives = []
    for supply in ('dovdd', 'avdd', 'dvdd'):
        bad = libfdt.Fdt(bytes(enabled.as_bytearray()))
        bad.delprop(bad.path_offset(rear), supply + '-supply')
        negatives.append((supply + '-missing', bad, 'ovti,ov13858', supply + '-supply'))
    bad = libfdt.Fdt(bytes(enabled.as_bytearray()))
    bad.setprop(bad.path_offset(cci), 'clock-names',
                b'camnoc_axi\0slow_ahb_src\0cpas_ahb\0cci\0invalid\0')
    negatives.append(('cci-clock-name-invalid', bad, 'qcom,i2c-cci', "'cci_src' was expected"))
    bad = libfdt.Fdt(bytes(enabled.as_bytearray()))
    bad.setprop(bad.path_offset(rear + '/port/endpoint'), 'data-lanes',
                b''.join(n.to_bytes(4, 'big') for n in (1, 2, 3)))
    negatives.append(('sensor-lane-count-invalid', bad, 'ovti,ov13858', 'data-lanes'))
    for name, bad, selection, expected in negatives:
        path = out / (name + '.dtb')
        path.write_bytes(bad.as_bytearray())
        log = name + '.log'
        run([str(SCHEMA_TOOLS / 'dt-validate'), '-s', str(schemas), '-l', selection, str(path)], log)
        assert expected in (out / log).read_text(), log
    firmware = extract(DSL.read_text())
    relevant = {name: states for name, states in firmware['devices'].items()
                if name.endswith(('CAMP', 'CAMS'))}
    (out / 'firmware-topology.json').write_text(json.dumps({'source_sha256': sha(DSL),
        'literal_packages_verified': firmware['literal_packages_verified'], 'devices': relevant}, indent=2) + '\n')
    shutil.copy2(__file__, out / Path(__file__).name)
    report = {'source_manifest_sha256': sha(SOURCE.parent / 'source-files.json'),
              'before_sha256': sha(BASE), 'draft_dtb_sha256': sha(out / 'rear.dtb'),
              'new_nodes': sorted(new), 'only_existing_node_additions': properties_added,
              'all_other_properties_exact': True, 'memory_reservations_exact': True,
              'cci_sensor_disabled': True, 'real_supply_targets_verified': True,
              'cci0_source_assigned_rate_hz': 37500000,
              'sensor_cci_regulator_schemas_without_diagnostics': True,
              'disabled_and_enabled_schema_fixtures_checked': True,
              'required_supply_clock_lane_negative_cases_rejected': len(negatives),
              'existing_tlmm_schema_diagnostic_groups': 7, 'new_tlmm_diagnostic_delta': False, 'no_camss_front_or_ir_added': True,
              'hardware_actions': [], 'functional_acceptance': False,
              'limits': ['Local sensor binding draft; no upstream approval implied.',
                        'Four-lane driver endpoint described without a remote CSI receiver.',
                        'Firmware action arguments retained; pin configuration mapping is inferred.',
                        'CCI resources/rail enables/sensor identity and capture remain unvalidated.']}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
