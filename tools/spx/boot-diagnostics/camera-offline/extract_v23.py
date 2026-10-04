#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create disabled review source from the pinned historical v23 DT artifact.

This writes only this review directory and the selected scratch directory. It
does not produce an overlay or modify kernel/boot/runtime configuration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

import libfdt

REFERENCE_SHA256 = 'e69f2637abc57ec2eca28925ce9b3e5c984e1d0085f06c0f45d6148fb92899d7'
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DEFAULT_REFERENCE = REPO.parent / 'linux-surface-kernel/docs/camdtb/v23.dts'
PIN_LABELS = {
    'spx-cam-mclk0-pins': 'spx_cam_mclk0_review',
    'spx-cam-rear-reset-pins': 'spx_cam_rear_reset_review',
    'spx-cam-mclk2-pins': 'spx_cam_mclk2_review',
    'spx-cam-mclk3-pins': 'spx_cam_mclk3_review',
    'spx-cam-ir-reset-pins': 'spx_cam_ir_enable_review',
}
SENSORS = [
    ('rear', 'i2c-bus@0/camera@10', 2),
    ('ir', 'i2c-bus@0/camera@60', 3),
    ('front', 'i2c-bus@1/camera@36', 0),
]
CCI = '/soc@0/cci@ac4a000'
CAMSS = '/soc@0/camss@ac65000'
TLMM = '/soc@0/pinctrl@3100000'


def header_numbers(name, kind, prefix=''):
    text = (REPO / 'include/dt-bindings' / name).read_text()
    numbers = {}
    for symbol, value in re.findall(
            r'^#define\s+(\w+)\s+(0x[\da-fA-F]+|\d+)\s*$', text, re.M):
        namespace = ('power-domains' if symbol.endswith('_GDSC') else
                     'resets' if symbol.endswith(('_BCR', '_ARES')) else 'clocks')
        if namespace != kind or not symbol.startswith(prefix):
            continue
        number = int(value, 0)
        if number in numbers:
            raise ValueError(f'duplicate {kind} ID {number}: {numbers[number]}, {symbol}')
        numbers[number] = symbol
    return numbers


def extract(reference, scratch):
    if hashlib.sha256(reference.read_bytes()).hexdigest() != REFERENCE_SHA256:
        raise ValueError('reference is not the reviewed v23 artifact')
    scratch.mkdir(parents=True, exist_ok=True)
    reference_dtb = scratch / 'reference-v23.dtb'
    with (scratch / 'reference-v23-dtc.log').open('w') as log:
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(reference_dtb),
                        str(reference)], stderr=log, check=True)
    fdt = libfdt.Fdt(reference_dtb.read_bytes())

    def raw(path, prop):
        return bytes(fdt.getprop(fdt.path_offset(path), prop))

    def cells(path, prop):
        data = raw(path, prop)
        return list(struct.unpack('>' + 'I' * (len(data) // 4), data))

    def strings(path, prop):
        return raw(path, prop).rstrip(b'\0').decode().split('\0')

    def phandle_path(value):
        return fdt.get_path(fdt.node_offset_by_phandle(value))

    clocks = {
        '/soc@0/clock-controller@ad00000': ('camcc', header_numbers('clock/qcom,sc8180x-camcc.h', 'clocks', 'CAM_CC_')),
        '/soc@0/clock-controller@100000': ('gcc', header_numbers('clock/qcom,gcc-sc8180x.h', 'clocks')),
    }
    gdsc = header_numbers('clock/qcom,sc8180x-camcc.h', 'power-domains')

    def clock_refs(path, prop):
        values = cells(path, prop)
        output = []
        for handle, clock in zip(values[::2], values[1::2], strict=True):
            label, names = clocks[phandle_path(handle)]
            output.append(f'<&{label} {names[clock]}>')
        return ', '.join(output)

    def domains(path):
        values = cells(path, 'power-domains')
        output = []
        for handle, domain in zip(values[::2], values[1::2], strict=True):
            assert phandle_path(handle) == '/soc@0/clock-controller@ad00000'
            output.append(f'<&camcc {gdsc[domain]}>')
        return ', '.join(output)

    def string_prop(path, prop):
        return ', '.join(json.dumps(value) for value in strings(path, prop))

    def irq_refs(path):
        values = cells(path, 'interrupts')
        output = []
        for index in range(0, len(values), 3):
            kind, number, flags = values[index:index + 3]
            assert kind == 0 and flags == 1
            output.append(f'<GIC_SPI {number} IRQ_TYPE_EDGE_RISING>')
        return ',\n\t\t\t     '.join(output)

    lines = ['// SPDX-License-Identifier: GPL-2.0-only', '/*',
             ' * OFFLINE REVIEW ONLY: generated from the hash-pinned v23 artifact.',
             ' * All camera/controller nodes are disabled; do not deploy or enable.',
             ' * Supply properties and fake fixed regulators are intentionally absent.',
             ' * The tested capture depended on separate direct SPMI rail setup.',
             ' */', '', '#include <dt-bindings/clock/qcom,sc8180x-camcc.h>',
             '#include <dt-bindings/clock/qcom,gcc-sc8180x.h>',
             '#include <dt-bindings/gpio/gpio.h>',
             '#include <dt-bindings/interrupt-controller/arm-gic.h>',
             '#include <dt-bindings/interconnect/qcom,sc8180x.h>',
             '#include <dt-bindings/interconnect/qcom,icc.h>', '', '&tlmm {']
    for name, label in PIN_LABELS.items():
        path = TLMM + '/' + name
        lines += [f'\t{label}: {name} {{',
                  f'\t\tpins = {string_prop(path, "pins")};',
                  f'\t\tfunction = {string_prop(path, "function")};',
                  f'\t\tdrive-strength = <{cells(path, "drive-strength")[0]}>;',
                  '\t\tbias-disable;']
        try:
            raw(path, 'output-low')
        except libfdt.FdtException:
            pass
        else:
            lines.append('\t\toutput-low;')
        lines += ['\t};', '']
    lines += ['};', '', '&{/soc@0} {', '\tspx_cci0_review: cci@ac4a000 {',
              f'\t\tcompatible = {string_prop(CCI, "compatible")};',
              '\t\t#address-cells = <1>;', '\t\t#size-cells = <0>;',
              '\t\treg = <' + ' '.join(hex(v) for v in cells(CCI, 'reg')) + '>;',
              f'\t\tinterrupts = {irq_refs(CCI)};',
              f'\t\tpower-domains = {domains(CCI)};',
              f'\t\tclocks = {clock_refs(CCI, "clocks")};',
              f'\t\tclock-names = {string_prop(CCI, "clock-names")};',
              '\t\tstatus = "disabled";', '']
    omissions = {}
    for bus in (0, 1):
        bus_path = CCI + f'/i2c-bus@{bus}'
        lines += [f'\t\ti2c-bus@{bus} {{', f'\t\t\treg = <{bus}>;',
                  f'\t\t\tclock-frequency = <{cells(bus_path, "clock-frequency")[0]}>;',
                  '\t\t\t#address-cells = <1>;', '\t\t\t#size-cells = <0>;', '']
        for name, relative, phy in SENSORS:
            if not relative.startswith(f'i2c-bus@{bus}/'):
                continue
            path = CCI + '/' + relative
            sensor_node = relative.split('/')[-1]
            lines += [f'\t\t\tspx_{name}_review: {sensor_node} {{',
                      f'\t\t\t\tcompatible = {string_prop(path, "compatible")};',
                      f'\t\t\t\treg = <{hex(cells(path, "reg")[0])}>;',
                      f'\t\t\t\tpower-domains = {domains(path)};',
                      f'\t\t\t\tclocks = {clock_refs(path, "clocks")};',
                      f'\t\t\t\tclock-names = {string_prop(path, "clock-names")};',
                      f'\t\t\t\tassigned-clocks = {clock_refs(path, "assigned-clocks")};',
                      f'\t\t\t\tassigned-clock-rates = <{cells(path, "assigned-clock-rates")[0]}>;',
                      '\t\t\t\tpinctrl-names = "default";']
            pins = [PIN_LABELS[phandle_path(h).rsplit('/', 1)[-1]] for h in cells(path, 'pinctrl-0')]
            lines.append('\t\t\t\tpinctrl-0 = <' + ' '.join('&' + pin for pin in pins) + '>;')
            gpio = 'enable-gpios' if name == 'ir' else 'reset-gpios'
            handle, pin, flag = cells(path, gpio)
            assert phandle_path(handle) == TLMM and flag in (0, 1)
            lines.append(f'\t\t\t\t{gpio} = <&tlmm {pin} GPIO_ACTIVE_{"LOW" if flag else "HIGH"}>;')
            omissions[path] = ['vdddo-supply', 'vdda-supply', 'vddd-supply'] if name == 'ir' else ['dovdd-supply', 'avdd-supply', 'dvdd-supply']
            lines += ['\t\t\t\t/* Unresolved real rail provider: no placeholder supplies. */',
                      f'\t\t\t\torientation = <{cells(path, "orientation")[0]}>;',
                      f'\t\t\t\trotation = <{cells(path, "rotation")[0]}>;',
                      '\t\t\t\tstatus = "disabled";', '', '\t\t\t\tport {',
                      f'\t\t\t\t\tspx_{name}_endpoint_review: endpoint {{']
            ep = path + '/port/endpoint'
            for prop in ['data-lanes', 'link-frequencies', 'clock-lanes']:
                lines.append(f'\t\t\t\t\t\t{prop} = <' + ' '.join(str(v) for v in cells(ep, prop)) + '>;')
            lines += [f'\t\t\t\t\t\tremote-endpoint = <&spx_phy{phy}_endpoint_review>;',
                      '\t\t\t\t\t};', '\t\t\t\t};', '\t\t\t};', '']
        lines += ['\t\t};', '']
    lines += ['\t};', '', '\tspx_camss_review: camss@ac65000 {',
              f'\t\tcompatible = {string_prop(CAMSS, "compatible")};']
    iommu, sid, mask = cells(CAMSS, 'iommus')
    assert phandle_path(iommu) == '/soc@0/iommu@15000000'
    lines.append(f'\t\tiommus = <&apps_smmu {hex(sid)} {hex(mask)}>;')
    registers = cells(CAMSS, 'reg')
    values = ['<' + ' '.join(hex(v) for v in registers[i:i + 4]) + '>' for i in range(0, len(registers), 4)]
    lines += ['\t\treg = ' + ',\n\t\t      '.join(values) + ';',
              f'\t\treg-names = {string_prop(CAMSS, "reg-names")};',
              f'\t\tinterrupts = {irq_refs(CAMSS)};',
              f'\t\tinterrupt-names = {string_prop(CAMSS, "interrupt-names")};',
              f'\t\tpower-domains = {domains(CAMSS)};',
              f'\t\tpower-domain-names = {string_prop(CAMSS, "power-domain-names")};',
              f'\t\tclocks = {clock_refs(CAMSS, "clocks")};',
              f'\t\tclock-names = {string_prop(CAMSS, "clock-names")};']
    icc = {
        ('/soc@0/interconnect@9680000', 0): ('gem_noc', 'MASTER_AMPSS_M0'),
        ('/soc@0/interconnect@1500000', 9): ('config_noc', 'SLAVE_CAMERA_CFG'),
        ('/soc@0/interconnect@1740000', 1): ('mmss_noc', 'MASTER_CAMNOC_HF0'),
        ('/soc@0/interconnect@1740000', 3): ('mmss_noc', 'MASTER_CAMNOC_SF'),
        ('/soc@0/interconnect@1740000', 2): ('mmss_noc', 'MASTER_CAMNOC_HF1'),
        ('/interconnect-mc-virt', 1): ('mc_virt', 'SLAVE_EBI_CH0'),
    }
    values = cells(CAMSS, 'interconnects')
    paths = []
    for i in range(0, len(values), 6):
        path = []
        for h, number, tag in (values[i:i + 3], values[i + 3:i + 6]):
            assert tag == 3  # Named ACTIVE_ONLY in the current qcom,icc.h.
            label, symbol = icc[(phandle_path(h), number)]
            path.append(f'&{label} {symbol} QCOM_ICC_TAG_ACTIVE_ONLY')
        paths.append('<' + ' '.join(path) + '>')
    lines += ['\t\tinterconnects = ' + ',\n\t\t\t\t'.join(paths) + ';',
              f'\t\tinterconnect-names = {string_prop(CAMSS, "interconnect-names")};',
              '\t\tstatus = "disabled";', '', '\t\tports {',
              '\t\t\t#address-cells = <1>;', '\t\t\t#size-cells = <0>;', '']
    for phy in range(4):
        lines += [f'\t\t\tport@{phy} {{', f'\t\t\t\treg = <{phy}>;',
                  '\t\t\t\t#address-cells = <1>;', '\t\t\t\t#size-cells = <0>;']
        names = [name for name, _, n in SENSORS if n == phy]
        if names:
            ep = CAMSS + f'/ports/port@{phy}/endpoint@0'
            lines += ['', f'\t\t\t\tspx_phy{phy}_endpoint_review: endpoint@0 {{',
                      '\t\t\t\t\treg = <0>;']
            for prop in ['clock-lanes', 'data-lanes']:
                lines.append(f'\t\t\t\t\t{prop} = <' + ' '.join(str(v) for v in cells(ep, prop)) + '>;')
            lines += [f'\t\t\t\t\tremote-endpoint = <&spx_{names[0]}_endpoint_review>;', '\t\t\t\t};']
        lines += ['\t\t\t};', '']
    lines += ['\t\t};', '\t};', '};', '']
    output = HERE / 'spx-camera-v23-disabled.dtsi'
    output.write_text('\n'.join(lines))
    manifest = {'reference': str(reference), 'reference_sha256': REFERENCE_SHA256,
                'reference_dtb': str(reference_dtb), 'source': str(output),
                'excluded_supply_properties': omissions,
                'included_roots': [CCI, CAMSS] + [TLMM + '/' + name for name in PIN_LABELS],
                'intended_status': 'disabled', 'unused_cci_controllers_excluded': [1, 2, 3]}
    (HERE / 'extraction-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument('--scratch', type=Path, default=Path('/var/tmp/spx-camera-offline-20260922'))
    args = parser.parse_args()
    extract(args.reference, args.scratch)
