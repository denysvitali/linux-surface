#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Review completed constituents after correcting a module-prefix check."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('startup_verify', HERE / 'verify.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
g = v.g
WORK = Path('/var/tmp/spx-venus-startup-diag-20261004')
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    native = WORK / 'native-v2'
    digest = g.sha(native / 'sha256.json')
    assert digest == '761a8949c20e7e2e2e779d217e39237dfcd21b7dea5e5290d4b9ac7130d3919a'
    assert g.files(native) == v.read(native / 'sha256.json') | {'sha256.json': digest}
    n = v.read(native / 'report.json')
    root = WORK / 'aarch64'
    assert not (root / 'report.json').exists() and not (root / 'sha256.json').exists()
    steps = v.read(root / 'commands.json')
    assert [r['label'] for r in steps] == ['snapshot', 'olddefconfig', 'prepare', 'objects',
                                         'relocatable-link', 'headers', 'symbols', 'sections', 'strings']
    assert all(r['exit_code'] == 0 for r in steps)
    assert '-j6' in steps[3]['argv']
    # ld -r -o <output> <first object> ...: constituents begin at argv[4].
    objects = [Path(x) for x in steps[4]['argv'][4:]]
    assert len(objects) == 14 and len(set(objects)) == 14
    for obj in objects:
        assert obj.parent == root
        assert g.sha(obj) == g.sha(root / 'output' / v.VENUS / obj.name)
        assert (root / ('.' + obj.name + '.cmd')).read_bytes() == (root / 'output' / v.VENUS / ('.' + obj.name + '.cmd')).read_bytes()
    assert 'AArch64' in (root / 'headers.stdout').read_text()
    strings = (root / 'strings.stdout').read_text().splitlines()
    assert 'spx_hfi_startup_diag' in strings and 'parmtype=spx_hfi_startup_diag:bool' in strings
    assert 'venus_core.spx_hfi_startup_diag' not in strings
    cmd = (root / '.hfi_venus.o.cmd').read_text().splitlines()[0]
    assert '-DMODULE' in cmd and '-D__KBUILD_MODNAME=venus_core' in cmd
    for word in ('poll', 'buffers', 'remote-state', 'auth-reset'):
        assert any('SPX Venus startup ' + word in line for line in strings)
    symbols = [line.split() for line in (root / 'symbols.stdout').read_text().splitlines()
               if line.strip().endswith('venus_hfi_startup_diag')]
    assert len(symbols) == 1 and symbols[0][3] == 'FUNC' and symbols[0][6] != 'UND'
    rows = v.read(g.X / 'dtb-build/candidate-source-files.json')
    changes = n['exact_three_source_changes']
    source = root / 'source'
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
    assert actual == set(rows) and len(actual) == 96938
    final = {}
    for name, row in rows.items():
        path = source / name
        if 'sha256' in row:
            expected = changes[name]['after_sha256'] if name in changes else row['sha256']
            assert not path.is_symlink() and g.sha(path) == expected
            assert stat.S_IMODE(path.stat().st_mode) == row['mode']
            final[name] = dict(sha256=expected, bytes=path.stat().st_size, mode=row['mode'])
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink']
            final[name] = row
    config = g.X / 'build/config-extracted'
    assert g.sha(root / 'config') == g.sha(root / 'output/.config') == g.sha(config)
    checked = v.live(rows, changes)
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    shutil.copy2(__file__, root / Path(__file__).name)
    shutil.copy2(HERE / 'build_venus.py', root / 'build_venus-corrected.py')
    (root / 'candidate-source-files.json').write_text(json.dumps(final, indent=2) + '\n')
    failure = dict(original_producer_sha256=g.sha(root / 'build_venus.py'),
        failure='Final prefix assertion expected a built-in namespaced string for a loadable module.',
        all_14_constituents_compiled_and_linked=True, original_compile_commands_preserved=True,
        corrected_check='Actual -DMODULE / KBUILD_MODNAME venus_core and unprefixed __param string verified.',
        kernel_source_changed=False, compilation_repeated=False)
    (root / 'compile-check-failure.json').write_text(json.dumps(failure, indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
        native_manifest_sha256=digest, native_comparisons=79296,
        parent_and_final_private_records_verified=96938, live_source_paths_verified=checked,
        exact_three_source_changes=changes, parent_manifest_sha256=g.sha(g.X / 'dtb-build/candidate-source-files.json'),
        config_sha256=g.sha(config), private_and_live_config_unchanged=True,
        actual_kbuild_aarch64_constituent_objects=14, independent_relocatable_link_sha256=g.sha(root / 'venus-core.o'),
        parameter_prefix_verified='venus_core.spx_hfi_startup_diag',
        loadable_module_identity_and_unprefixed_parameter_verified=True,
        original_incorrect_prefix_check_preserved=failure,
        internal_diagnostic_gate_link_resolved=True, known_good_recovery_rehashed=True,
        pending_selection_empty=True, full_kernel_linked=False, deployed=False,
        boot_selected=False, hardware_operations=0, hardware_acceptance_closed=False)
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {p.name: g.sha(p) for p in sorted(root.iterdir()) if p.is_file() and not p.is_symlink()}
    (root / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    os.sync()
    print(json.dumps(dict(manifest_sha256=g.sha(root / 'sha256.json'), report=report)), flush=True)


if __name__ == '__main__':
    main()
