#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive BF's reviewed runtime from the immutable first preparation."""
import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

HERE = Path(__file__).resolve().parent
X = g.X.with_name('20261004bf')
PARENT = X / 'preparation/runtime-plan'
BOOT = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


def replace(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--update-workspace', action='store_true')
    args = p.parse_args()
    os.umask(0o077)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert g.sha(X / 'preparation-sha256.json') == '0971bec8bcfcf5aba6d725420d3a4ef38feff6ac239a145880e53d47cc55b953'
    assert g.files(X / 'preparation') == json.loads((X / 'preparation-sha256.json').read_text())
    original = json.loads((PARENT / 'sha256.json').read_text())
    assert g.sha(PARENT / 'sha256.json') == '4f2fd603627a52dc649191403712c54eeee57245c6731ce8b9939f2f751b211f'
    assert g.files(PARENT) == original | {'sha256.json': g.sha(PARENT / 'sha256.json')}
    args.out.mkdir(mode=0o700)
    changes = {}
    names = sorted(name for name in original if name.endswith('.py') and
                   name not in ('prepare-bf-runtime.py', 'prepare-bf-helpers.py', 'verify-bf-venus-startup.py'))
    assert len(names) == 14
    for name in names:
        text = (PARENT / name).read_text()
        text = text.replace("'preparation", "'preparation-reviewed")
        if name == 'bf_boot_guard.py':
            marker = '    for path, digest in (a[\'sha256\'] | a[\'runtime_sha256\']).items():\n'
            text = replace(text, marker,
                "    assert sha(X / 'preparation-sha256.json') == a['original_preparation_manifest_sha256']\n"
                "    assert files(X / 'preparation') == json.loads((X / 'preparation-sha256.json').read_text())\n" + marker)
            text = replace(text, "a['preparation-reviewed_manifest_sha256']", "a['preparation_manifest_sha256']") if "a['preparation-reviewed_manifest_sha256']" in text else text
        if name == 'bf-baseline.py':
            start = text.index("    for name, digest in json.loads((RUN / 'build/dtb-build/sha256.json')")
            end = text.index("\n    kernel = command(", start)
            text = text[:start] + "    from bf_boot_guard import artifacts, recovery\n    assert not recovery(a).get('next_entry', '')\n    artifacts(a)\n" + text[end:]
        if name == 'review-bf-baseline.py':
            text = replace(text, '"""Rehash BF result; v2 uses the explicit-reuse archive build_links_verified key."""',
                           '"""Review BF strict baseline against its fresh build and assembly."""')
            start = text.index("build = json.loads((X / 'build-sha256.json')")
            end = text.index("for name, digest in (a['sha256']", start)
            text = text[:start] + """from bf_boot_guard import artifacts, recovery
assert not recovery(a).get('next_entry', '')
artifacts(a)
build = json.loads((X / 'build-sha256.json').read_text())
build_links = links(X / 'build')
assembly = json.loads((X / 'assembly-sha256.json').read_text())
assembly_links = json.loads((X / 'assembly-symlinks.json').read_text())
modules = json.loads((X / 'assembly/module-sha256.json').read_text())
assert len(build) == 243 and len(assembly) == 818 and len(assembly_links) == 272
assert len(modules) == 217
""" + text[end:]
            marker = "          'build_symlinks_verified': len(build_links),\n"
            text = replace(text, marker, marker + "          'assembly_files_verified': len(assembly),\n          'assembly_symlinks_verified': len(assembly_links),\n")
        if name == 'review-bf-result.py':
            text = replace(text, "        archive = read(X / 'archive-review.json')\n",
                "        built = read(X / 'build-review.json')\n        archive = read(X / 'assembly-review.json')\n")
            text = replace(text, "build_files_verified=archive['build_files_verified'],\n                      build_links_verified=archive['build_links_verified'],",
                "build_files_verified=built['build_files'],\n                      build_links_verified=len(links(X / 'build')),\n                      assembly_files_verified=archive['assembly_files'],\n                      assembly_links_verified=archive['assembly_links'],")
            text = replace(text, 'artifacts, files, sha, trial_identity', 'artifacts, files, links, sha, trial_identity')
        ast.parse(text)
        target = args.out / name
        target.write_text(text)
        changes[name] = dict(before_sha256=original[name], after_sha256=g.sha(target),
                             changed=original[name] != g.sha(target))
        if args.update_workspace:
            assert g.sha(HERE / name) == original[name], name
            shutil.copy2(target, HERE / name)
    shutil.copy2(__file__, args.out / Path(__file__).name)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), parent_manifest_sha256=g.sha(PARENT / 'sha256.json'),
        parent_preparation_manifest_sha256=g.sha(X / 'preparation-sha256.json'), changes=changes,
        kernel_module_dtb_initramfs_unchanged=True, physical_checks_and_delays_unchanged=True,
        original_preparation_preserved=True, deployed=False, boot_selected=False)
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.out / 'sha256.json').write_text(json.dumps(g.files(args.out), indent=2) + '\n')
    print(json.dumps(dict(helpers=14, changed=[n for n, row in changes.items() if row['changed']],
                         manifest_sha256=g.sha(args.out / 'sha256.json'))), flush=True)


if __name__ == '__main__':
    main()
