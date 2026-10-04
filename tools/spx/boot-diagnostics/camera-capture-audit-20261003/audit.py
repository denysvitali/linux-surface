#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve offline receiver contracts; never access camera or PMIC hardware."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import libfdt

REPO = Path(__file__).resolve().parents[4]
SIBLING = REPO.parent / 'linux-surface-kernel'
DSDT = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')
OUT = Path(sys.argv[1])
assert not OUT.exists()
OUT.mkdir(mode=0o700)

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def properties(fdt, path):
    result = {}
    node = fdt.path_offset(path)
    offset = fdt.first_property_offset(node, quiet=(libfdt.NOTFOUND,))
    while offset >= 0:
        p = fdt.get_property_by_offset(offset)
        result[p.name] = bytes(p)
        offset = fdt.next_property_offset(offset, quiet=(libfdt.NOTFOUND,))
    return result

def cells(p):
    return list(struct.unpack('>' + 'I' * (len(p) // 4), p))

assert sha(DSDT) == 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
assert sha(SIBLING / 'docs/camdtb/v23.dts') == 'e69f2637abc57ec2eca28925ce9b3e5c984e1d0085f06c0f45d6148fb92899d7'
parser = REPO / 'tools/spx/boot-diagnostics/camera-power-20261003/audit_firmware.py'
spec = importlib.util.spec_from_file_location('firmware_audit', parser)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
firmware = module.extract(DSDT.read_text())
camp = firmware['devices'][r'\\_SB.CAMP']
assert len(camp) == 6
votes = [a for s in camp for a in s['actions'] if a['operation'] == 'PMICVREGVOTE']
assert not votes
mmcx = [a for s in camp for a in s['actions'] if a['operation'] == 'NPARESOURCE']
assert mmcx and all(a['arguments'][1] == '/arc/client/rail_mmcx' for a in mmcx)
fdt = libfdt.Fdt((SIBLING / 'docs/camdtb/v23.dtb').read_bytes())
camss_path = '/soc@0/camss@ac65000'
camss = properties(fdt, camss_path)
assert camss['compatible'] == b'qcom,sc8180x-camss\0'
assert not any(name.endswith('-supply') for name in camss)
receiver = properties(fdt, camss_path + '/ports/port@2/endpoint@0')
sensor = properties(fdt, '/soc@0/cci@ac4a000/i2c-bus@0/camera@10/port/endpoint')
assert cells(receiver['data-lanes']) == [0, 1, 2, 3]
assert cells(receiver['clock-lanes']) == [7]
assert cells(sensor['data-lanes']) == [1, 2, 3, 4]
assert cells(sensor['clock-lanes']) == [7]
for endpoint, peer in ((receiver, sensor), (sensor, receiver)):
    assert endpoint['remote-endpoint'] == peer['phandle']
manifest = Path('/var/log/spx-camera-archive/v23-multi-20260809/SHA256SUMS')
assert sha(manifest) == 'e7c3bb900154f61511bd98fa7a60cb668627677bffb7c231ab60ccbb8e524982'
captures = {}
for line in manifest.read_text().splitlines():
    digest, name = line.split(None, 1)
    p = Path(name)
    assert sha(p) == digest
    captures[name] = {'sha256': digest, 'bytes': p.stat().st_size}
assert len(captures) == 9
paths = {
    'firmware-dsdt.dsl': DSDT,
    'audit_firmware.py': parser,
    'v23.dts': SIBLING / 'docs/camdtb/v23.dts',
    'v23.dtb': SIBLING / 'docs/camdtb/v23.dtb',
    'capture-SHA256SUMS': manifest,
    'camss.c': REPO / 'drivers/media/platform/qcom/camss/camss.c',
    'camss-csid.c': REPO / 'drivers/media/platform/qcom/camss/camss-csid.c',
    'camss-csiphy-3ph-1-0.c': REPO / 'drivers/media/platform/qcom/camss/camss-csiphy-3ph-1-0.c',
    'regulator-core.c': REPO / 'drivers/regulator/core.c',
    'sc8180x.dtsi': REPO / 'arch/arm64/boot/dts/qcom/sc8180x.dtsi',
    'qcom,sc8180x-camss.yaml': REPO / 'tools/spx/boot-diagnostics/camera-offline/bindings-draft/media/qcom,sc8180x-camss.yaml',
    'audit.py': Path(__file__).resolve(),
}
inputs = {name: {'path': str(p), 'sha256': sha(p)} for name, p in paths.items()}
for name, p in paths.items():
    shutil.copyfile(p, OUT / name)
    assert sha(OUT / name) == inputs[name]['sha256']
result = {
    'scope': 'Offline C01 receiver audit; actual AS final regression still pending at audit start',
    'literal_packages_verified': firmware['literal_packages_verified'],
    'camp_states': camp,
    'camp_pmicvregvote_count': len(votes),
    'camp_mmcx_votes': mmcx,
    'historical_camss_supply_properties': [],
    'receiver_endpoint': {k: cells(receiver[k]) for k in ('data-lanes', 'clock-lanes')},
    'sensor_endpoint': {k: cells(sensor[k]) for k in ('data-lanes', 'clock-lanes')},
    'reciprocal_historical_graph_verified': True,
    'capture_files_verified': captures,
    'receiver_analog_supply_mapping_established': False,
    'receiver_lanes_validated_on_current_kernel': False,
    'limits': [
        'CAMP MMCX/GDSC actions do not establish dedicated PHY/PLL analog rail providers.',
        'Current SC8180X resources reuse CSID tables requesting vdda-phy/vdda-pll; normal regulator API permits missing-supply dummy fallback.',
        'Historical capture plus absent supply properties does not establish analog ownership, dummy log occurrence or correct modern provider wiring.',
        'Receiver and sensor lane namespaces differ; do not copy sensor data-lanes to the receiver.',
        'Retain receiver requirements pending actual supply/SoC contract evidence; no new hardware experiment was selected.',
    ],
}
(OUT / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
(OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
hashes = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
assert all(sha(OUT / name) == digest for name, digest in hashes.items())
print(json.dumps({'files_verified': len(hashes), 'capture_files_verified': len(captures),
                  'firmware_packages_verified': firmware['literal_packages_verified'],
                  'manifest_sha256': sha(OUT / 'sha256.json')}, indent=2))
