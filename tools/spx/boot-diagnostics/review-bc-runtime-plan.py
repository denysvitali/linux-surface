#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently review BC's offline helpers, timers and actual entry construction."""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bb_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004bc')
SRC = Path(__file__).resolve().parent
BOOT = 'e00a2d25-03f7-4265-b56e-0eac05b234d3'


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    parent = g.load()
    assert parent['state'] == 'BB terminal; scoped baseline and guarded return verified; PAS memory setup raw SCM error unresolved'
    assert not g.recovery(parent).get('next_entry', '')
    g.artifacts(parent)
    plan = STAGE / 'runtime-plan'
    expected = json.loads((plan / 'sha256.json').read_text())
    assert g.files(plan) == expected | {'sha256.json': g.sha(plan / 'sha256.json')}
    helpers = sorted(plan.glob('*.py'))
    assert len(helpers) == 15
    for path in helpers:
        assert g.sha(SRC / path.name) == expected[path.name]
        ast.parse(path.read_text())
    result = json.loads((plan / 'result.json').read_text())
    assert result['identity_positive_cases'] == 1 and result['identity_negative_cases'] == 14
    assert result['media_reference_pairs'] == 2 and result['media_negative_controls'] == 7
    assert not (plan / 'unit-verify.stderr').read_bytes()
    units = sorted(plan.glob('spx-bc-*.service')) + sorted(plan.glob('spx-bc-*.timer'))
    assert len(units) == 12
    checked = subprocess.run(['systemd-analyze', 'verify'] + [str(path) for path in units],
                             capture_output=True, timeout=60)
    assert checked.returncode == 0 and not checked.stderr.strip()
    out = STAGE / 'runtime-plan-review'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    (out / 'unit-verify.stdout').write_bytes(checked.stdout)
    (out / 'unit-verify.stderr').write_bytes(checked.stderr)
    tree = ast.parse((plan / 'deploy-bc.py').read_text())
    main_body = next(node.body for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    first = next(i for i, node in enumerate(main_body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'cmdline' for target in node.targets))
    last = next(i for i in range(first, len(main_body)) if isinstance(main_body[i], ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'prep' for target in main_body[i].targets))
    namespace = dict(parent=parent, old=g)
    exec(compile(ast.Module(body=main_body[first:last], type_ignores=[]),
                 'actual-deploy-bc-entry-body', 'exec'), namespace)
    cmdline, entry = namespace['cmdline'], namespace['entry']
    old_tokens, new_tokens = parent['cmdline'].split(), cmdline.split()
    assert new_tokens == [token.replace('spx_attempt=20261004bb', 'spx_attempt=20261004bc')
                          for token in old_tokens] + ['qcom_scm.spx_pas_area_diag=1']
    assert entry.count('qcom_scm.spx_pas_diag=1') == 1
    assert entry.count('qcom_scm.spx_pas_area_diag=1') == 1
    (out / 'entry.cfg').write_text(entry)
    subprocess.run(['grub-script-check', str(out / 'entry.cfg')], check=True, timeout=30)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(parent).get('next_entry', '')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                  helpers_exact_plan=15, units_verified=12,
                  actual_deployment_entry_body_exercised=True, grub_entry_syntax_passed=True,
                  cmdline_changes=['spx_attempt=20261004bc', 'qcom_scm.spx_pas_area_diag=1'],
                  identity_positive_cases=1, identity_negative_cases=14,
                  media_reference_pairs=2, media_negative_controls=7,
                  plan_manifest_sha256=g.sha(plan / 'sha256.json'),
                  persistent_default='spx-known-good', next_entry_empty=True,
                  installed=False, boot_selected=False, hardware_operations=0,
                  hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    os.sync()
    print(json.dumps(report | {'manifest_sha256': g.sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
