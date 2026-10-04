#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile only the reviewed PGCM static video reservation and prove DT scope."""
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
HERE = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g
sys.path.insert(0, str(HERE))
from review_aq_dtb_delta_ar import flatten

BOARD = 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'
OLD = '/reserved-memory/video-firmware'
NEW = OLD + '@8d300000'


def compare(before, after):
    left, right = flatten(before), flatten(after)
    assert OLD in left and NEW not in left and NEW in right and OLD not in right
    moved = right.pop(NEW)
    right[OLD] = moved
    assert left.keys() == right.keys()
    expected = dict(left[OLD])
    for name in ('size', 'alignment', 'alloc-ranges'):
        assert name in expected
        del expected[name]
    expected['reg'] = struct.pack('>4I', 0, 0x8d300000, 0, 0x500000).hex()
    assert moved == expected
    assert not moved['no-map']
    assert moved['phandle'] == left[OLD]['phandle']
    for path in left:
        if path != OLD:
            assert left[path] == right[path], path
    a, b = libfdt.Fdt(before), libfdt.Fdt(after)
    assert a.num_mem_rsv() == b.num_mem_rsv()
    assert all(a.get_mem_rsv(i) == b.get_mem_rsv(i) for i in range(a.num_mem_rsv()))
    return dict(nodes_verified=len(left), renamed_node=dict(before=OLD, after=NEW),
        removed=['size', 'alignment', 'alloc-ranges'], added=dict(reg=expected['reg']),
        all_other_nodes_properties_exact=True, all_phandles_exact=True,
        explicit_fdt_memory_reservations_exact=True, no_map_preserved=True)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    out = g.X / 'offline-video-static-reservation'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(HERE / 'review_aq_dtb_delta_ar.py', out / 'fdt_compare.py')
    try:
        a = g.load()
        assert a['state'].startswith('BD terminal;')
        bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        assert bid == a['returned_boot_id'] and os.uname().release == '6.18.3-1-surface+'
        assert not g.recovery(a).get('next_entry', '')
        policy = g.X / 'offline-pil-reservation-policy'
        assert g.sha(policy / 'sha256.json') == 'cd27a2636b9e3c86d20aae50d39dcecde044ab75f5e9beb6105ced45e9dbf687'
        assert g.files(policy) == json.loads((policy / 'sha256.json').read_text()) | {'sha256.json': g.sha(policy / 'sha256.json')}
        before = (policy / 'board-before.dts').read_text()
        after = (policy / 'board-candidate.dts').read_text()
        assert (g.REPO / BOARD).read_text() == after
        rows = json.loads((g.X / 'dtb-build/candidate-source-files.json').read_text())
        assert g.sha(policy / 'board-before.dts') == rows[BOARD]['sha256']
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
        assert g.sha(g.REPO / '.config') == g.sha(g.X / 'dtb-build/live-config-before')
        (out / 'source-before.dts').write_text(before)
        (out / 'source-after.dts').write_text(after)
        shutil.copy2(g.REPO / '.config', out / 'live-config')
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
        parent = g.X / 'dtb-build'
        assert (out / 'raw-before.dtb').read_bytes() == (parent / 'raw-after.dtb').read_bytes()
        raw_comparison = compare((out / 'raw-before.dtb').read_bytes(), (out / 'raw-after.dtb').read_bytes())
        pre = (parent / 'boot-after.pre.dts').read_text()
        (out / 'boot-before.pre.dts').write_text(pre)
        declaration = 'venus_mem: video-firmware {\n   size = <0 0x500000>;\n   alignment = <0 0x100000>;\n   alloc-ranges = <0 0x80000000 0 0x80000000>;\n   no-map;\n  };'
        overlay = '\n&{/reserved-memory/video-firmware} {\nalloc-ranges = <0 0x8b700000 0 0x0f400000>;\n};\n'
        assert pre.count(declaration) == 1 and pre.count(overlay) == 1
        next_pre = pre.replace(declaration,
            'venus_mem: video-firmware@8d300000 {\n   reg = <0 0x8d300000 0 0x500000>;\n   no-map;\n  };').replace(overlay, '\n')
        (out / 'boot-after.pre.dts').write_text(next_pre)
        for phase in ('before', 'after'):
            run('dtc-boot-' + phase, ['dtc', '-I', 'dts', '-O', 'dtb', '-H', 'epapr',
                '-o', str(out / ('boot-' + phase + '.dtb')), str(out / ('boot-' + phase + '.pre.dts'))])
        assert (out / 'boot-before.dtb').read_bytes() == (parent / 'spx.dtb').read_bytes()
        boot_comparison = compare((out / 'boot-before.dtb').read_bytes(), (out / 'boot-after.dtb').read_bytes())
        shutil.copy2(parent / 'video_dt_contract.py', out / 'video_dt_contract.py')
        spec = importlib.util.spec_from_file_location('static_video_contract', out / 'video_dt_contract.py')
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)
        assert contract.EXPECTED['memory-region'] == [(OLD, [])]
        contract.EXPECTED['memory-region'] = [(NEW, [])]
        provider = contract.validate((out / 'boot-after.dtb').read_bytes())
        (out / 'provider-contracts.json').write_text(json.dumps(provider, indent=2) + '\n')
        # Static reg is the standard OF path; leave the entire existing pool NOMAP.
        schema_root = Path('/var/tmp/spx-reserved-memory-schema-20261004')
        schema = schema_root / 'reserved-memory.yaml'
        reference = json.loads((schema_root / 'reference.json').read_text())
        assert reference['commit'] == '5687115902ba74c1cd80bdab4772cc2cdfa75778'
        assert reference['sha256'] == g.sha(schema) == 'da75f617ff6bba7a193a442666f732673b4301458280fb47a03c89ea82512d43'
        shutil.copy2(schema, out / schema.name)
        shutil.copy2(schema_root / 'reference.json', out / 'schema-reference.json')
        assert 'reg:' in schema.read_text() and 'no-map:' in schema.read_text()
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
        assert not g.recovery(a).get('next_entry', '')
        report = dict(boot_id=bid, compiled_source_paths_checked=checked, source_delta=[BOARD],
            board_sha256=g.sha(g.REPO / BOARD), live_config_exact_bd_prebuild=True,
            raw_comparison=raw_comparison, retained_comparison=boot_comparison,
            raw_candidate_sha256=g.sha(out / 'raw-after.dtb'),
            retained_candidate_sha256=g.sha(out / 'boot-after.dtb'), provider_contracts_verified=True,
            policy_manifest_sha256=g.sha(policy / 'sha256.json'),
            base='0x8d300000', bytes=0x500000, static_nomap=True, commands=commands,
            deployed=False, boot_selected=False, pas_acceptance_observed=False, hardware_acceptance_closed=False)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
        assert g.files(out) == json.loads((out / 'sha256.json').read_text()) | {'sha256.json': g.sha(out / 'sha256.json')}
        os.sync()
        print(json.dumps(report | dict(manifest_sha256=g.sha(out / 'sha256.json')), indent=2))
    except BaseException:
        (out / 'failure.txt').write_text(traceback.format_exc())
        (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
        os.sync()
        raise


if __name__ == '__main__':
    main()
