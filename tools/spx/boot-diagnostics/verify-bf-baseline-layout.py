#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replay the real BF baseline reviewer and artifact contract before installation."""
import argparse
import ast
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
from types import ModuleType

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

BF = g.X.with_name('20261004bf')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    root = p.parse_args().out
    os.umask(0o077)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
    root.mkdir(mode=0o700)
    plan = BF / 'preparation-reviewed/runtime-plan'
    for name in ('verify-bf-baseline-layout.py', 'bf-baseline.py', 'review-bf-baseline.py', 'bf_boot_guard.py'):
        shutil.copy2(HERE / name, root / name)
    # Strip only the explicitly replaced provenance blocks and new report
    # fields. Every remaining collector/check predicate must remain identical.
    before = (BF / 'preparation/runtime-plan/bf-baseline.py').read_text()
    after = (plan / 'bf-baseline.py').read_text()
    def strip(text, start, end):
        i, j = text.index(start), text.index(end, text.index(start))
        return text[:i] + text[j:]
    left = strip(before, "    for name, digest in json.loads((RUN / 'build/dtb-build/sha256.json')", '\n    kernel = command(')
    right = strip(after, '    from bf_boot_guard import artifacts, recovery\n', '\n    kernel = command(')
    assert ast.dump(ast.parse(left), include_attributes=False) == ast.dump(ast.parse(right), include_attributes=False)
    before = (BF / 'preparation/runtime-plan/review-bf-baseline.py').read_text()
    after = (plan / 'review-bf-baseline.py').read_text()
    left = strip(before, "build = json.loads((X / 'build-sha256.json')", "for name, digest in (a['sha256']")
    right = strip(after, 'from bf_boot_guard import artifacts, recovery\n', "for name, digest in (a['sha256']")
    right = right.replace("          'assembly_files_verified': len(assembly),\n          'assembly_symlinks_verified': len(assembly_links),\n", '')
    lt, rt = ast.parse(left), ast.parse(right)
    lt.body.pop(0)
    rt.body.pop(0)
    assert ast.dump(lt, include_attributes=False) == ast.dump(rt, include_attributes=False)
    base = root / 'synthetic-base'
    x = base / 'attempts/20261004bf'
    x.mkdir(parents=True)
    for name in ('build', 'assembly', 'preparation', 'preparation-reviewed'):
        (x / name).symlink_to(BF / name)
    for name in ('build-sha256.json', 'build-review.json', 'assembly-sha256.json', 'assembly-symlinks.json',
                 'assembly-review.json', 'preparation-sha256.json', 'preparation-reviewed-sha256.json', 'working-recovery.json'):
        shutil.copy2(BF / name, x / name)
    (base / 'attempts/20261002ap').symlink_to(g.BASE / 'attempts/20261002ap')
    shutil.copy2(plan / 'entry.cfg', x / 'entry.cfg')
    # This is a contract fixture, never an independent review of the candidate.
    independent = dict(explicitly_synthetic_contract_fixture=True, source_archive_stream_verified=True,
        source_paths_checked=84669, full_bf_executable_and_initramfs_verified=True,
        assembly_review_sha256=g.sha(BF / 'assembly-review.json'))
    write(x / 'independent-preparation-review.json', independent)
    recovery = read(BF / 'working-recovery.json')
    a = dict(attempt='20261004bf', release=RELEASE, cmdline=(plan / 'cmdline').read_text().strip(),
        sha256={str(BF / 'assembly' / name): g.sha(BF / 'assembly' / name) for name in ('vmlinuz', 'initramfs.img', 'dtb-build/spx.dtb')},
        runtime_sha256={str(plan / name): g.sha(plan / name) for name in read(plan / 'sha256.json') if name.endswith('.py')},
        recovery_sha256=recovery['payload_sha256'], recovery_definition_sha256=g.sha(BF / 'working-recovery.json'),
        original_preparation_manifest_sha256=g.sha(BF / 'preparation-sha256.json'),
        preparation_manifest_sha256=g.sha(BF / 'preparation-reviewed-sha256.json'),
        runtime_plan_manifest_sha256=g.sha(plan / 'sha256.json'),
        build_manifest_sha256=g.sha(BF / 'build-sha256.json'), build_review_sha256=g.sha(BF / 'build-review.json'),
        assembly_manifest_sha256=g.sha(BF / 'assembly-sha256.json'),
        assembly_symlinks_sha256=g.sha(BF / 'assembly-symlinks.json'), assembly_review_sha256=g.sha(BF / 'assembly-review.json'),
        independent_preparation_review_sha256=g.sha(x / 'independent-preparation-review.json'))
    write(x / 'attempt.json', a)
    write(base / 'attempt.json', a)
    modules = BF / 'assembly/module-root/lib/modules' / RELEASE
    paths = {'/usr/lib/modules/' + RELEASE: modules, '/usr/lib/modules': modules.parent,
             '/boot/grub/custom.cfg': x / 'entry.cfg'}
    ns = dict(X=x, RELEASE=RELEASE, json=json, hashlib=hashlib, os=os, re=re, subprocess=subprocess,
              Path=lambda value: paths.get(str(value), Path(value)))
    bodies = [n for n in ast.parse((plan / 'bf_boot_guard.py').read_text()).body if isinstance(n, ast.FunctionDef) and
              n.name in ('sha', 'files', 'links', 'command', 'artifacts', 'recovery')]
    assert len(bodies) == 6
    exec(compile(ast.Module(body=bodies, type_ignores=[]), str(plan / 'bf_boot_guard.py'), 'exec'), ns)
    assert not ns['recovery'](a).get('next_entry', '')
    ns['artifacts'](a)
    rejected = []
    for name, field in [('build-manifest', 'build_manifest_sha256'), ('assembly-manifest', 'assembly_manifest_sha256'),
                        ('preparation-manifest', 'preparation_manifest_sha256'), ('independent-review-hash', 'independent_preparation_review_sha256')]:
        bad = a | {field: '0' * 64}
        try:
            ns['artifacts'](bad)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('Accepted invalid artifact contract: ' + name)
    write(root / 'contract-rejections.json', rejected)
    # Replay the entire top-level reviewer over the real BE strict result with
    # attempt/release/cmdline modeled for BF. Every physical assertion is real
    # code; the result remains explicitly synthetic BF evidence.
    shutil.copytree(g.X / 'final-result', x / 'final-result')
    final = x / 'final-result'
    result = read(final / 'result.json')
    result.update(attempt='20261004bf', release=RELEASE)
    write(final / 'result.json', result)
    (final / 'cmdline').write_text('BOOT_IMAGE=/spx-trial-20261004bf/vmlinuz ' + a['cmdline'] + '\n')
    identity = dict(boot_id=result['boot_id'], release=RELEASE, taint=result['kernel_taint'],
                    cmdline=(final / 'cmdline').read_text().strip())
    for name in ('camera-control-result', 'camera-control-final-result', 'camera-provider-result'):
        nested = final / name
        report = read(nested / 'report.json')
        report.update(identity_before=identity, identity_after=identity)
        write(nested / 'report.json', report)
        (nested / 'sha256.json').unlink()
        write(nested / 'sha256.json', g.files(nested))
    (final / 'sha256.json').unlink()
    write(final / 'sha256.json', g.files(final))
    action = read(g.X / 'finalizer-action.json')
    action.update(result_sha256=g.sha(final / 'result.json'), manifest_sha256=g.sha(final / 'sha256.json'),
                  files_verified=len(read(final / 'sha256.json')))
    write(x / 'finalizer-action.json', action)
    guard = ModuleType('bf_boot_guard')
    guard.artifacts, guard.recovery = ns['artifacts'], ns['recovery']
    previous = sys.modules.get('bf_boot_guard')
    sys.modules['bf_boot_guard'] = guard
    class Redirect(ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value == '/var/lib/spx-boot-diagnostics':
                return ast.copy_location(ast.Constant(str(base)), node)
            return node
    code = ast.fix_missing_locations(Redirect().visit(ast.parse((plan / 'review-bf-baseline.py').read_text())))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, str(plan / 'review-bf-baseline.py'), 'exec'), {'__name__': '__main__'})
    finally:
        if previous is None: sys.modules.pop('bf_boot_guard', None)
        else: sys.modules['bf_boot_guard'] = previous
    verdict = read(x / 'independent-result-review.json')
    assert verdict['scoped_passed'] and verdict['camera_trial_passed']
    assert verdict['build_files_verified'] == 243 and verdict['build_symlinks_verified'] == 0
    assert verdict['assembly_files_verified'] == 818 and verdict['assembly_symlinks_verified'] == 272
    write(root / 'synthetic-baseline-review.json', verdict)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), explicitly_synthetic=True,
        original_be_strict_result_sha256=g.sha(g.X / 'final-result/sha256.json'),
        full_top_level_baseline_reviewer_executed=True, actual_artifact_guard_body_executed=True,
        real_known_good_recovery_verified=True, artifact_contract_positive_cases=1,
        artifact_contract_negative_cases=len(rejected), physical_predicates_ast_exact_first_bf=True,
        baseline_collector_other_code_ast_exact_first_bf=True, fresh_build_and_assembly_counts_exact=True,
        installed_module_and_custom_entry_paths_redirected=True, independent_review_is_contract_fixture=True,
        actual_bf_hardware_result=False, hardware_acceptance_closed=False)
    write(root / 'report.json', report)
    write(root / 'symlinks.json', g.links(root))
    write(root / 'sha256.json', g.files(root))
    print(json.dumps(report | dict(manifest_sha256=g.sha(root / 'sha256.json'))), flush=True)


if __name__ == '__main__':
    main()
