#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify only the measured PIL aperture changes in source and retained boot DTBs."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import traceback

import libfdt

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bc_boot_guard as g

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_aq_dtb_delta_ar import flatten

BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'
MEM = '/reserved-memory/video-firmware'
OLD = '\t\t\talloc-ranges = <0 0x80000000 0 0x80000000>;'
NEW = '\t\t\talloc-ranges = <0 0x8b700000 0 0x0f400000>;'


def compare(before, after):
    left, right = flatten(before), flatten(after)
    assert left.keys() == right.keys()
    delta = []
    for path in left:
        for prop in set(left[path]) | set(right[path]):
            if left[path].get(prop) != right[path].get(prop):
                delta.append(dict(path=path, property=prop,
                    before=left[path].get(prop), after=right[path].get(prop)))
    assert delta == [dict(path=MEM, property='alloc-ranges',
        before=struct.pack('>4I', 0, 0x80000000, 0, 0x80000000).hex(),
        after=struct.pack('>4I', 0, 0x8b700000, 0, 0x0f400000).hex())], delta
    a, b = libfdt.Fdt(before), libfdt.Fdt(after)
    assert a.num_mem_rsv() == b.num_mem_rsv()
    assert all(a.get_mem_rsv(i) == b.get_mem_rsv(i) for i in range(a.num_mem_rsv()))
    return dict(nodes_verified=len(left), delta=delta, all_other_property_values_exact=True,
                explicit_memory_reservations_exact=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    out = p.parse_args().out
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(Path(__file__).with_name('review_aq_dtb_delta_ar.py'), out / 'fdt_compare.py')
    try:
        a = g.load()
        assert a['state'].startswith('BC terminal;')
        bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        assert bid == a['returned_boot_id'] and os.uname().release == '6.18.3-1-surface+'
        assert not g.recovery(a).get('next_entry', '')
        correlation = g.X / 'offline-pil-response-20261004'
        assert g.sha(correlation / 'sha256.json') == 'e0404039eab2daa54769841f30c0fb45ff82e18ebce0f272a5be6ef289246b57'
        expected = json.loads((correlation / 'sha256.json').read_text())
        assert g.files(correlation) == expected | {'sha256.json': g.sha(correlation / 'sha256.json')}
        original = correlation / 'board-before-allocation-correction.dts'
        before = original.read_text()
        after = (g.REPO / BOARD).read_text()
        assert before.count(OLD) == 1 and after == before.replace(OLD, NEW)
        rows = json.loads((g.X / 'build/source-files.json').read_text())
        assert g.sha(original) == rows[BOARD]['sha256']
        checked = 0
        for name, row in rows.items():
            top = Path(name).parts[0]
            if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or
                    (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                    name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
                continue
            path = g.REPO / name
            if name != BOARD:
                if 'sha256' in row:
                    assert g.sha(path) == row['sha256'], name
                else:
                    assert path.is_symlink() and os.readlink(path) == row['symlink'], name
            checked += 1
        assert checked == 84669
        assert g.sha(g.REPO / '.config') == g.sha(g.X / 'build/live-config-before')
        shutil.copy2(original, out / 'source-before.dts')
        shutil.copy2(g.REPO / BOARD, out / 'source-after.dts')
        shutil.copy2(g.REPO / '.config', out / 'live-config')
        shutil.copy2(correlation / 'v3/report.json', out / 'response-correlation.json')
        commands = []

        def run(name, argv):
            result = subprocess.run(argv, capture_output=True, timeout=90)
            (out / (name + '.stdout')).write_bytes(result.stdout)
            (out / (name + '.stderr')).write_bytes(result.stderr)
            commands.append(dict(name=name, argv=argv, exit_code=result.returncode))
            assert result.returncode == 0, name

        for phase in ('before', 'after'):
            run('cpp-' + phase, ['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__',
                '-x', 'assembler-with-cpp', '-I', str(g.REPO / 'include'),
                '-I', str(g.REPO / 'arch/arm64/boot/dts/qcom'),
                str(out / ('source-' + phase + '.dts')), '-o', str(out / ('raw-' + phase + '.pre.dts'))])
            run('dtc-' + phase, ['dtc', '-I', 'dts', '-O', 'dtb', '-H', 'epapr',
                '-o', str(out / ('raw-' + phase + '.dtb')), str(out / ('raw-' + phase + '.pre.dts'))])
        raw_parent = g.X / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'
        assert g.sha(raw_parent) == '8f68dbfea9d04f9c3ba27125eefa4e77e02cf2a190830b6b2b015f226585a958'
        assert flatten((out / 'raw-before.dtb').read_bytes()) == flatten(raw_parent.read_bytes())
        raw_comparison = compare((out / 'raw-before.dtb').read_bytes(), (out / 'raw-after.dtb').read_bytes())
        retained = g.X / 'build/dtb-build'
        parent = retained / 'spx.dtb'
        assert g.sha(parent) == '4d96be24498f39afc10db917d7be155ee4b0d8314bfdfec924ddf1131594f4a9'
        shutil.copy2(parent, out / 'boot-before.dtb')
        shutil.copy2(retained / 'candidate.pre.dts', out / 'boot-before.pre.dts')
        # Extract the corrected allocation property from the verified board;
        # preserve the exact historical camera/LED/phandle tree as the base.
        (out / 'boot-after.pre.dts').write_text((out / 'boot-before.pre.dts').read_text() +
            '\n&{' + MEM + '} {\n' + NEW.strip() + '\n};\n')
        for phase in ('before', 'after'):
            run('dtc-boot-' + phase, ['dtc', '-I', 'dts', '-O', 'dtb', '-H', 'epapr',
                '-o', str(out / ('boot-recompiled-' + phase + '.dtb')),
                str(out / ('boot-' + phase + '.pre.dts'))])
        assert (out / 'boot-recompiled-before.dtb').read_bytes() == parent.read_bytes()
        boot_comparison = compare(parent.read_bytes(), (out / 'boot-recompiled-after.dtb').read_bytes())
        helper = retained / 'video_dt_contract.py'
        shutil.copy2(helper, out / helper.name)
        spec = importlib.util.spec_from_file_location('allocation_dt_contract', helper)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)
        provider = contract.validate((out / 'boot-recompiled-after.dtb').read_bytes())
        (out / 'provider-contracts.json').write_text(json.dumps(provider, indent=2) + '\n')
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
        assert not g.recovery(a).get('next_entry', '')
        report = dict(boot_id=bid, compiled_source_paths_checked=checked,
            source_delta=[BOARD], live_config_exact_bc_prebuild=True,
            raw_comparison=raw_comparison, boot_comparison=boot_comparison,
            raw_candidate_sha256=g.sha(out / 'raw-after.dtb'),
            retained_candidate_sha256=g.sha(out / 'boot-recompiled-after.dtb'),
            inclusive_start='0x8b700000', exclusive_end='0x9ab00000',
            window_bytes=0x0f400000, firmware_size_bytes=0x500000,
            alignment_bytes=0x100000, no_map_unchanged=True,
            dynamic_allocation_preserved=True, provider_contracts_verified=True,
            deployed=False, boot_selected=False, pas_memory_acceptance_established=False,
            hardware_acceptance_closed=False, commands=commands)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        expected = g.files(out)
        (out / 'sha256.json').write_text(json.dumps(expected, indent=2) + '\n')
        assert g.files(out) == expected | {'sha256.json': g.sha(out / 'sha256.json')}
        os.sync()
        print(json.dumps(report | {'manifest_sha256': g.sha(out / 'sha256.json')}, indent=2))
    except BaseException:
        (out / 'failure.txt').write_text(traceback.format_exc())
        (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
        os.sync()
        raise


if __name__ == '__main__':
    main()
