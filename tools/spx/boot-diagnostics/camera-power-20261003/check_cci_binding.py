#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile an offline disabled camera DT; check actual CCI schema and mutations."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import libfdt

REPO = Path(__file__).resolve().parents[4]
TOOLS = Path('/var/tmp/spx-dtschema-venv-20260915/bin')
CCI = '/soc@0/cci@ac4a000'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    records = []

    def run(name, command):
        started = time.monotonic()
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                                timeout=30)
        output = result.stdout + result.stderr
        (work / (name + '.log')).write_text(output)
        records.append({'name': name, 'command': command, 'returncode': result.returncode,
                        'elapsed_seconds': round(time.monotonic() - started, 3)})
        if result.returncode:
            raise RuntimeError(f'{name}: {output}')
        return output

    schema = work / 'schema'
    shutil.copytree('/var/tmp/spx-camera-offline-20260922/schema-subset', schema,
                    dirs_exist_ok=True)
    shutil.copy2(REPO / 'Documentation/devicetree/bindings/i2c/qcom,i2c-cci.yaml',
                 schema / 'i2c/qcom,i2c-cci.yaml')
    output = run('doc', [str(TOOLS / 'dt-doc-validate'),
                        str(schema / 'i2c/qcom,i2c-cci.yaml')])
    assert not output.strip(), output
    dts = REPO / 'tools/spx/boot-diagnostics/camera-offline/spx-camera-review.dts'
    preprocessed = work / 'review.pre.dts'
    run('cpp', ['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x',
                'assembler-with-cpp', '-I', str(REPO / 'include'), '-I',
                str(REPO / 'scripts/dtc/include-prefixes'), '-I',
                str(REPO / 'arch/arm64/boot/dts/qcom'), str(dts), '-o', str(preprocessed)])
    dtb = work / 'review.dtb'
    run('dtc', ['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(dtb), str(preprocessed)])
    raw = dtb.read_bytes()

    def changed(name, mutations):
        fdt = libfdt.Fdt(raw)
        fdt.resize(len(raw) + 4096)
        offset = fdt.path_offset(CCI)
        fdt.setprop(offset, 'status', b'okay\0')
        for prop, value in mutations:
            if value is None:
                fdt.delprop(offset, prop)
            else:
                fdt.setprop(offset, prop, value)
        path = work / (name + '.dtb')
        path.write_bytes(fdt.as_bytearray())
        return path

    def validate(name, path):
        output = run(name, [str(TOOLS / 'dt-validate'), '-s', str(schema), '-l',
                            'qcom,i2c-cci', str(path)])
        return output

    for name, path in [('disabled', dtb), ('enabled-offline', changed('enabled-offline', []))]:
        output = validate(name, path)
        assert 'cci@ac4a000' not in output, output
    fdt = libfdt.Fdt(raw)
    offset = fdt.path_offset(CCI)
    names = bytes(fdt.getprop(offset, 'clock-names'))
    clocks = bytes(fdt.getprop(offset, 'clocks'))
    for name, changes, expected in [
        ('bad-name', [('clock-names', names.replace(b'cci_src', b'cci_bad'))],
         "'cci_src' was expected"),
        ('four-clocks', [('clock-names', names.rsplit(b'cci_src\0', 1)[0]),
                         ('clocks', clocks[:-8])], 'too short'),
        ('missing-domain', [('power-domains', None)], "'power-domains' is a required property"),
        ('bad-fallback', [('compatible', b'qcom,sc8180x-cci\0qcom,msm8226-cci\0')],
         'compatible:'),
    ]:
        output = validate(name, changed(name, changes))
        assert 'cci@ac4a000' in output and expected in output, output
    # Preserve regression coverage for existing members of the same clock group.
    for compatible in ('sc7280', 'sm8250', 'sm8450'):
        path = changed(compatible, [('compatible',
                       f'qcom,{compatible}-cci\0qcom,msm8996-cci\0'.encode())])
        output = validate(compatible, path)
        assert 'cci@ac4a000' not in output, output
    state = {'status': 'CCI checks passed; all mutations are offline',
             'schema_sha256': hashlib.sha256((schema / 'i2c/qcom,i2c-cci.yaml').read_bytes()).hexdigest(),
             'dtb_sha256': hashlib.sha256(raw).hexdigest(), 'commands': records,
             'positive_cases': 5, 'negative_cases': 4,
             'limits': 'Other camera schemas, rails and capture remain unresolved. '
                       'Existing base DTC/subset reference warnings are retained in logs.'}
    (work / 'result.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({k: state[k] for k in ('status', 'positive_cases', 'negative_cases')}))


if __name__ == '__main__':
    main()
