#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal area-query offline evidence and independently verify the durable copy."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bb_boot_guard as g
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_log import parse
from parse_pas import parse as parse_bb

STAGE = Path('/var/tmp/spx-pas-area-diag-20261004')
OUT = g.X / 'offline-pas-area-diag-20261004'
CODE = g.REPO / 'tools/spx/boot-diagnostics/pas-area-diag-20261004'
BOOT = 'e00a2d25-03f7-4265-b56e-0eac05b234d3'


def sealed(root, top=False):
    expected = json.loads((root / 'sha256.json').read_text())
    actual = ({p.name: g.sha(p) for p in root.iterdir() if p.is_file()} if top else g.files(root))
    assert actual == expected | {'sha256.json': g.sha(root / 'sha256.json')}, root
    return g.sha(root / 'sha256.json')


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    a = g.load()
    assert a['state'] == 'BB terminal; scoped baseline and guarded return verified; PAS memory setup raw SCM error unresolved'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert os.uname().release == '6.18.3-1-surface+'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    native, build, style, log = (STAGE / name for name in
                               ('native-v3', 'object-build-v3', 'style-v2', 'log-v1'))
    manifests = dict(native=sealed(native), build=sealed(build, True),
                     style=sealed(style), log=sealed(log))
    assert manifests['native'] == '9da84ad665d61cf17c1cfec65dc5db7739d5e065073f02d2dbb11965404d1175'
    assert manifests['log'] == 'c9b5432d841c0cc5270786dc14d3eb3260215f81fbd0f29690131ba536b5e8d7'
    n = json.loads((native / 'report.json').read_text())
    b = json.loads((build / 'report.json').read_text())
    l = json.loads((log / 'report.json').read_text())
    assert n['positive']['checks'] == 436 and n['positive']['before_after_cases'] == 416
    assert len(n['rejected_controls']) == 9 and all(r['exit_code'] == -6 for r in n['rejected_controls'])
    assert b['parent_and_final_private_records_verified'] == 96938
    assert b['actual_kbuild_aarch64_constituent_objects'] == 3
    assert b['internal_diagnostic_gate_link_resolved'] and b['private_and_live_config_unchanged']
    assert l['bb_positive_traces_replayed'] == 52 and l['synthetic_area_traces'] == 17
    assert len(l['corrupt_traces_rejected']) == 33
    changes = b['exact_two_source_changes']
    assert set(changes) == {'drivers/firmware/qcom/qcom_scm.c', 'drivers/firmware/qcom/qcom_scm.h'}
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
        assert g.sha(native / filename) == g.sha(build / filename) == changes[name]['after_sha256']
        assert g.sha(native / (filename + '.before')) == changes[name]['before_sha256']
    assert (style / 'checkpatch.stderr').read_bytes() == b''
    assert b'0 errors, 0 warnings, 0 checks' in (style / 'checkpatch.stdout').read_bytes()
    assert (style / 'source.patch').read_bytes() == (build / 'source.patch').read_bytes()
    actual_kernel = (g.X / 'video-startup/kernel.stdout').read_text()
    actual = parse(actual_kernel)
    assert actual['pas'] == parse_bb(actual_kernel) and actual['diagnostic_lines'] == 8
    assert not actual['area_query_observed']
    assert actual['pas']['calls'][1]['smc_done']['raw_registers'] == [0xffcfffba, 0, 0, 0]
    OUT.mkdir(mode=0o700)
    for name in ('native-v1', 'native-v2', 'native-v3', 'object-build-v1', 'object-build-v2',
                 'style-v1', 'style-v2', 'log-v1', 'original'):
        shutil.copytree(STAGE / name, OUT / name)
    dest = OUT / 'object-build-v3'
    dest.mkdir()
    for path in build.iterdir():
        if path.is_file():
            shutil.copy2(path, dest / path.name)
    shutil.copytree(CODE, OUT / 'helpers')
    for name in ('LOCAL-PROGRESS.md', 'PORT-CHECKLIST.md',
                 'tools/spx/boot-diagnostics/RESULT-20261004bb.md'):
        shutil.copy2(g.REPO / name, OUT / Path(name).name)
    shutil.copy2(g.X / 'return-review/report.json', OUT / 'parent-terminal-return.json')
    (OUT / 'actual-bb-diagnostic-replay.json').write_text(json.dumps(actual, indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                  compiled_source_paths_verified=checked, exact_two_source_changes=changes,
                  scm_smc_source_exact_bb=True, native_manifest_sha256=manifests['native'],
                  native_actual_body_checks=436, native_before_after_cases=416,
                  rejected_candidate_controls=9, aarch64_build_manifest_sha256=manifests['build'],
                  private_source_records_verified=96938, aarch64_constituent_objects_compiled=3,
                  relocatable_link_verified=True, full_kernel_linked=False,
                  source_style_manifest_sha256=manifests['style'], source_style_checks_passed=True,
                  commit_metadata_checks_excluded=True, log_manifest_sha256=manifests['log'],
                  parser_bb_positive_replays=52, parser_area_positive_traces=17,
                  parser_corruptions_rejected=33, actual_bb_replay_exact=True,
                  raw_area_results_uninterpreted=True,
                  parent_terminal_return_manifest_sha256=g.sha(g.X / 'return-review/sha256.json'),
                  known_good_recovery_reverified=True, persistent_default='spx-known-good',
                  next_entry_empty=True, early_recovery_validated=False,
                  deployed=False, boot_selected=False, hardware_acceptance_closed=False)
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (OUT / 'sha256.json').write_text(json.dumps(g.files(OUT), indent=2) + '\n')
    os.sync()
    digest = sealed(OUT)
    assert sealed(OUT / 'native-v3') == manifests['native']
    assert sealed(OUT / 'object-build-v3') == manifests['build']
    assert sealed(OUT / 'log-v1') == manifests['log']
    assert not g.recovery(a).get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    print(json.dumps(report | {'files_verified': len(g.files(OUT)) - 1,
                              'durable_manifest_sha256': digest}, indent=2), flush=True)


if __name__ == '__main__':
    main()
