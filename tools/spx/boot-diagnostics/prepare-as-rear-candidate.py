#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Review an enabled rear-only DT candidate offline against actual AR provenance."""
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
AR = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ar')
SOURCE = Path('/var/tmp/spx-mainline-trial-20261003ar/source')
V7 = Path('/var/tmp/spx-rear-identification-20261003-v7')
DTC = Path('/var/tmp/spx-mainline-trial-20261003ar/work-build/scripts/dtc/dtc')
SCHEMA = Path('/var/tmp/spx-dtschema-venv-20260915/bin/dt-validate')
CCI = '/soc@0/cci@ac4a000'
SENSOR = CCI + '/i2c-bus@0/camera@10'
sys.path.insert(0, str(TOOLS))
from review_aq_dtb_delta_ar import flatten


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def verify(root):
    expected = json.loads((root / 'sha256.json').read_text())
    assert manifest(root) == expected | {'sha256.json': sha(root / 'sha256.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    out = parser.parse_args().output
    assert os.geteuid() == 0 and not out.exists()
    os.umask(0o077)
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '5b14cce2-951f-4b43-a786-3cd2339f79b5'
    assert os.uname().release == '7.3.0-rc2-spx-mainline-20261003ar+'
    for name in ('final-result', 'post-result-records'):
        verify(AR / name)
    review = json.loads((AR / 'independent-result-review.json').read_text())
    assert review['boot_id'] == bid and review['scoped_passed'] and review['fallback_stopped']
    verify(V7)
    old = AR / 'build/offline-rear-only/v6/rear.dtb'
    disabled = V7 / 'rear.dtb'
    left, right = flatten(old.read_bytes()), flatten(disabled.read_bytes())
    assert left.keys() == right.keys()
    for path in left:
        properties = dict(right[path])
        if path == CCI:
            assert set(properties) - set(left[path]) == {'assigned-clocks', 'assigned-clock-rates'}
            del properties['assigned-clocks'], properties['assigned-clock-rates']
        assert properties == left[path], path
    out.mkdir(mode=0o700)
    for name in ('spx-rear-identification-disabled.dtsi', 'spx-camera-regulators-disabled.dtsi'):
        shutil.copy2(V7 / name, out / name)
    (out / 'candidate.dts').write_text((V7 / 'rear.dts').read_text() +
        '&spx_rear_cci0 { status = "okay"; };\n&spx_rear_sensor { status = "okay"; };\n')
    commands = []

    def run(args, log):
        with (out / log).open('xb') as stream:
            result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT)
        commands.append({'command': args, 'log': log, 'exit_code': result.returncode})
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, log

    run(['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
         '-I', str(SOURCE / 'include'), '-I', str(SOURCE / 'scripts/dtc/include-prefixes'),
         '-I', str(SOURCE / 'arch/arm64/boot/dts/qcom'), '-I', str(out),
         str(out / 'candidate.dts'), '-o', str(out / 'candidate.pre.dts')], 'cpp.log')
    run([str(DTC), '-I', 'dts', '-O', 'dtb', '-H', 'epapr', '-o', str(out / 'candidate.dtb'),
         str(out / 'candidate.pre.dts')], 'dtc.log')
    data = (out / 'candidate.dtb').read_bytes()
    enabled = flatten(data)
    assert enabled.keys() == right.keys()
    for path in right:
        properties = dict(enabled[path])
        if path in (CCI, SENSOR):
            assert properties['status'] == b'okay\0'.hex()
            properties['status'] = b'disabled\0'.hex()
        assert properties == right[path], path
    before, after = libfdt.Fdt(disabled.read_bytes()), libfdt.Fdt(data)
    assert before.num_mem_rsv() == after.num_mem_rsv()
    assert all(before.get_mem_rsv(n) == after.get_mem_rsv(n) for n in range(before.num_mem_rsv()))
    assert enabled[CCI]['assigned-clock-rates'] == (37500000).to_bytes(4, 'big').hex()
    for selection in ('ovti,ov13858', 'qcom,i2c-cci', 'qcom,spmi-regulator', 'qcom,sc8180x-tlmm'):
        log = selection.replace(',', '-') + '-schema.log'
        run([str(SCHEMA), '-s', str(V7 / 'schema'), '-l', selection,
             str(out / 'candidate.dtb')], log)
        text = (out / log).read_text()
        if selection == 'qcom,sc8180x-tlmm':
            assert text.replace(str(out / 'candidate.dtb'), '<DTB>') == (
                V7 / 'baseline-tlmm-schema.log').read_text().replace(
                    '/var/tmp/spx-touch-firmware-20261003/candidate.dtb', '<DTB>')
        else:
            assert not text.strip(), log
    (out / 'clock-summary-before.txt').write_text(Path('/sys/kernel/debug/clk/clk_summary').read_text())
    code = ('drivers/i2c/busses/i2c-qcom-cci.c', 'drivers/media/i2c/ov13858.c',
            'drivers/media/v4l2-core/v4l2-fwnode.c', 'drivers/clk/qcom/camcc-sc8180x.c',
            'include/dt-bindings/clock/qcom,sc8180x-camcc.h')
    source_hashes = {}
    for name in code:
        assert sha(REPO / name) == sha(SOURCE / name), name
        source_hashes[name] = sha(SOURCE / name)
        target = out / 'source-review' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / name, target)
    shutil.copy2(__file__, out / Path(__file__).name)
    report = {
        'parent_attempt': '20261003ar', 'parent_boot_id': bid,
        'parent_scoped_baseline_passed': True,
        'parent_result_manifest_sha256': sha(AR / 'final-result/sha256.json'),
        'parent_post_result_manifest_sha256': sha(AR / 'post-result-records/sha256.json'),
        'source_manifest_sha256': sha(SOURCE.parent / 'source-files.json'),
        'source_review_hashes': source_hashes,
        'v7_manifest_sha256': sha(V7 / 'sha256.json'),
        'candidate_dtb_sha256': sha(out / 'candidate.dtb'),
        'delta_from_v7_disabled': ['CCI status=okay', 'rear sensor status=okay'],
        'cci0_source_assigned_rate_hz': 37500000,
        'all_other_properties_and_reservations_exact': True,
        'no_camss_front_or_ir_added': True,
        'camera_functional_acceptance': False, 'hardware_actions': [],
        'boot_selected': False,
        'limits': ['Normal driver binding would show its built-in chip-ID check returned success; raw ID read is not logged.',
                   'AR has CONFIG_FTRACE disabled; no I2C trace is available.',
                   'No CSI receiver, capture, raw electrical or firmware-ownership validation.',
                   'Seven existing TLMM schema diagnostic groups remain; full board schema is not clean.']}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = manifest(out)
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    verify(out)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    os.sync()
    print(json.dumps(report | {'files_verified': len(hashes),
                              'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
