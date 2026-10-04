#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate offline controller drafts; never install or enable a hardware tree."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import libfdt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
WORK = Path('/var/tmp/spx-camera-bindings-20260922')
TOOLS = Path('/var/tmp/spx-dtschema-venv-20260915/bin')
REFERENCE = Path('/var/tmp/spx-camera-offline-20260922/review.dtb')
CCI = '/soc@0/cci@ac4a000'
CAMSS = '/soc@0/camss@ac65000'
LIMIT = 'qcom,i2c-cci:ovti,ov5693:ovti,ov7251:qcom,sc8180x-camss'


def run(name, command, results):
    start = time.monotonic()
    proc = subprocess.run(command, cwd=REPO, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=30)
    log = name + '-draft.log'
    (HERE / log).write_text(proc.stdout)
    results.append({'name': name, 'command': command, 'returncode': proc.returncode,
                    'elapsed_seconds': round(time.monotonic() - start, 3), 'log': log})
    assert proc.returncode == 0, (name, proc.stdout)
    return proc.stdout


def changed_dtb(name, changes):
    raw = REFERENCE.read_bytes()
    fdt = libfdt.Fdt(raw)
    fdt.resize(len(raw) + 4096)
    for path, prop, value in changes:
        fdt.setprop(fdt.path_offset(path), prop, value)
    path = WORK / (name + '.dtb')
    path.write_bytes(fdt.as_bytearray())
    return path


def main():
    WORK.mkdir(exist_ok=True)
    schema = WORK / 'schema-subset'
    shutil.copytree('/var/tmp/spx-camera-offline-20260922/schema-subset', schema,
                    dirs_exist_ok=True)
    for path in (HERE / 'bindings-draft').rglob('*.yaml'):
        target = schema / path.relative_to(HERE / 'bindings-draft')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    results = []
    doc = run('schema-doc', [str(TOOLS / 'dt-doc-validate'),
              str(schema / 'i2c/qcom,i2c-cci.yaml'),
              str(schema / 'media/qcom,sc8180x-camss.yaml')], results)
    assert not doc.strip(), doc
    for patch in ('cci-sc8180x-binding.patch', 'camss-sc8180x-binding-draft.patch'):
        output = run(patch, ['git', 'apply', '--check', str(HERE / patch)], results)
        assert not output.strip(), output
    def validate(name, path):
        return run(name, [str(TOOLS / 'dt-validate'), '-s', str(schema), '-l',
                         LIMIT, str(path)], results)
    disabled = validate('schema-disabled', REFERENCE)
    assert 'cci@ac4a000 (qcom,sc8180x-cci)' not in disabled, disabled
    assert 'camss@ac65000 (qcom,sc8180x-camss)' not in disabled, disabled
    assert '7 is greater than the maximum of 1' in disabled, disabled
    assert "'orientation', 'power-domains', 'rotation'" in disabled, disabled
    missing = validate('missing-supplies', changed_dtb('missing-supplies', [
        (CCI, 'status', b'okay\0'), (CAMSS, 'status', b'okay\0')]))
    for supply in ('vdda-phy-supply', 'vdda-pll-supply'):
        assert f"'{supply}' is a required property" in missing, missing
    fdt = libfdt.Fdt(REFERENCE.read_bytes())
    bad = validate('bad-resource-names', changed_dtb('bad-resource-names', [
        (CCI, 'clock-names', bytes(fdt.getprop(fdt.path_offset(CCI), 'clock-names'))
         .replace(b'cci_src', b'cci_bad')),
        (CAMSS, 'reg-names', bytes(fdt.getprop(fdt.path_offset(CAMSS), 'reg-names'))
         .replace(b'csiphy0', b'csiphy9'))]))
    assert "clock-names:4: 'cci_src' was expected" in bad, bad
    assert "reg-names:0: 'csiphy0' was expected" in bad, bad
    bad_endpoint = validate('bad-endpoint', changed_dtb('bad-endpoint', [
        (CAMSS + '/ports/port@0/endpoint@0', 'data-lanes', b'\0\0\0\0' * 5)]))
    assert 'data-lanes' in bad_endpoint and 'too long' in bad_endpoint, bad_endpoint
    inputs = json.loads((HERE / 'binding-inputs.json').read_text())
    integrity = {path: {'before': digest,
                       'after': hashlib.sha256((REPO / path).read_bytes()).hexdigest()}
                 for path, digest in inputs.items()}
    assert all(v['before'] == v['after'] for v in integrity.values()), integrity
    (HERE / 'binding-active-integrity.json').write_text(json.dumps(integrity, indent=2) + '\n')
    state = {'status': 'offline draft checks passed; deployment requirements unresolved',
             'reference_sha256': hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
             'commands': results, 'runtime_actions': [],
             'active_input_hashes_unchanged': len(integrity),
             'diagnostics_expected': ['OV7251 lane maximum', 'OV7251 node properties',
                                      'subset leds missing type definition'],
             'negative_checks': ['missing CAMSS supplies', 'wrong CCI clock name',
                                 'wrong CAMSS register name', 'five receiver data lanes']}
    (HERE / 'binding-validation-state.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'status': state['status'], 'commands': len(results),
                      'active_input_hashes_unchanged': len(integrity)}))


if __name__ == '__main__':
    main()
