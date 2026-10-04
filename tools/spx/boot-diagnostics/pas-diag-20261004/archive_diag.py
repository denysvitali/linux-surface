#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal offline PAS diagnostic proofs and independently rehash their durable copy."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ba_boot_guard as g

STAGE = Path('/var/tmp/spx-pas-diag-20261004')
OUT = g.X / 'offline-pas-diag-20261004'
CODE = g.REPO / 'tools/spx/boot-diagnostics/pas-diag-20261004'


def sealed(root):
    expected = json.loads((root / 'sha256.json').read_text())
    assert g.files(root) == expected | {'sha256.json': g.sha(root / 'sha256.json')}, root
    return g.sha(root / 'sha256.json')


def main():
    os.umask(0o077)
    a = g.load()
    assert a['state'] == 'BA terminal; guarded return verified'
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot == 'a824008e-cf43-4287-84f8-4e930fa41a06'
    assert os.uname().release == '6.18.3-1-surface+'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    native, link, style = (STAGE / name for name in ('native-v4', 'object-link-v2', 'style-source'))
    assert sealed(native) == 'b1d8690ad0cf638de889d6746507a9c860daecf0ec7c86f6a17522564e833969'
    assert sealed(link) == 'fd5ed74e557931542646a370a60f4003ad2e29ae61d1a815ab445ee91e59c745'
    assert sealed(style) == 'e48023bff009a5464fbd7b29769d2dda2b7b251cff5f60b6a93cac753e5e51c4'
    n = json.loads((native / 'report.json').read_text())
    b = json.loads((link / 'report.json').read_text())
    assert n['positive']['checks'] == 91 and n['positive']['before_after_cases'] == 80
    assert len(n['rejected_controls']) == 5 and all(row['exit_code'] == -6 for row in n['rejected_controls'])
    assert b['private_source_records_verified'] == 96938
    assert b['actual_kbuild_aarch64_constituent_objects'] == 3
    assert b['internal_diagnostic_gate_link_resolved'] and b['private_and_live_config_unchanged']
    changes = b['exact_three_source_changes']
    assert len(changes) == 3
    rows = json.loads((g.X / 'build/source-files.json').read_text())
    checked = 0
    for name, row in rows.items():
        top = Path(name).parts[0]
        if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or
                (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
            continue
        path = g.REPO / name
        if name in changes:
            assert g.sha(path) == changes[name]['after_sha256']
            assert row['sha256'] == changes[name]['before_sha256']
        elif 'sha256' in row:
            assert g.sha(path) == row['sha256'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
        checked += 1
    assert checked == 84669
    assert g.sha(g.REPO / '.config') == g.sha(g.X / 'build/live-config-before')
    for name in changes:
        filename = Path(name).name
        assert g.sha(native / filename) == g.sha(link / filename) == changes[name]['after_sha256']
        assert g.sha(native / (filename + '.before')) == changes[name]['before_sha256']
    assert (style / 'checkpatch.stderr').read_bytes() == b''
    assert b'0 errors, 0 warnings, 0 checks' in (style / 'checkpatch.stdout').read_bytes()
    OUT.mkdir(mode=0o700)
    for name in ('native-v1', 'native-v2', 'native-v3', 'native-v4', 'object-link-v2', 'style', 'style-source'):
        shutil.copytree(STAGE / name, OUT / name)
    old = OUT / 'failed-object-target'
    old.mkdir()
    for path in (STAGE / 'object-build').iterdir():
        if path.is_file():
            shutil.copy2(path, old / path.name)
    before = OUT / 'before'
    before.mkdir()
    for path in STAGE.iterdir():
        if path.is_file():
            shutil.copy2(path, before / path.name)
    shutil.copytree(CODE, OUT / 'helpers')
    for name in ('LOCAL-PROGRESS.md', 'PORT-CHECKLIST.md',
                 'tools/spx/boot-diagnostics/RESULT-20261004ba.md'):
        shutil.copy2(g.REPO / name, OUT / Path(name).name)
    shutil.copy2(g.X / 'return-review/report.json', OUT / 'parent-terminal-return.json')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=boot,
                  compiled_source_paths_verified=checked, exact_three_source_changes=changes,
                  native_manifest_sha256=sealed(native), native_actual_body_checks=91,
                  native_before_after_cases=80, rejected_candidate_controls=5,
                  aarch64_build_manifest_sha256=sealed(link),
                  private_source_records_verified=96938,
                  aarch64_constituent_objects_compiled=3,
                  relocatable_link_verified=True, full_kernel_linked=False,
                  parent_terminal_return_manifest_sha256=g.sha(g.X / 'return-review/sha256.json'),
                  source_style_checks_passed=True, commit_metadata_checks_excluded=True,
                  known_good_recovery_reverified=True, persistent_default='spx-known-good',
                  next_entry_empty=True, early_recovery_validated=False,
                  deployed=False, boot_selected=False, hardware_acceptance_closed=False)
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (OUT / 'sha256.json').write_text(json.dumps(g.files(OUT), indent=2) + '\n')
    os.sync()
    digest = sealed(OUT)
    assert sealed(OUT / 'native-v4') == report['native_manifest_sha256']
    assert sealed(OUT / 'object-link-v2') == report['aarch64_build_manifest_sha256']
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    print(json.dumps(report | {'files_verified': len(g.files(OUT)) - 1,
                              'durable_manifest_sha256': digest}, indent=2))


if __name__ == '__main__':
    main()
