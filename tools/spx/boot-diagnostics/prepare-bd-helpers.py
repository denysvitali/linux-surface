#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive BD collectors from frozen BC, preserving the exact executable release."""
import ast
import hashlib
import json
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bc/build/runtime-plan')
RELEASE = '7.3.0-rc2-spx-mainline-20261004bc+'
IMAGE = 'BOOT_IMAGE=/spx-trial-20261004bc/vmlinuz'
NAMES = ('bc_boot_guard.py', 'bc-video.py', 'bc-return.py', 'bc-baseline.py',
         'bc-camera-provider.py', 'bc-camera-control.py', 'bc_camera_core.py',
         'review-bc-baseline.py', 'bc-media.py', 'bc-media-run.py', 'bc-reboot-check.py')


def function(text, name, replacement):
    tree = ast.parse(text)
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1
    node = found[0]
    lines = text.splitlines(True)
    return ''.join(lines[:node.lineno-1]) + replacement.strip() + '\n' + ''.join(lines[node.end_lineno:])


ARTIFACTS = '''
def artifacts(a):
    for path, digest in (a['sha256'] | a['runtime_sha256']).items():
        assert sha(path) == digest, path
    assert sha(X / 'build-sha256.json') == a['build_manifest_sha256']
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert links(X / 'build') == json.loads((X / 'build-symlinks.json').read_text())
    assert sha(X / 'dtb-sha256.json') == a['dtb_manifest_sha256']
    assert files(X / 'dtb-build') == json.loads((X / 'dtb-sha256.json').read_text())
    assert sha(X / 'archive-review.json') == a['archive_review_sha256']
    report = json.loads((X / 'archive-review.json').read_text())
    assert report['kernel_modules_initramfs_reused_exact_bc']
    assert report['kernel_executable_sources_exact_bc']
    assert report['external_dt_only_source_delta'] == ['arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts']
    assert report['full_candidate_source_records_verified'] == 96938
    assert report['candidate_source_archive_stream_verified']
    assert report['exactly_one_dt_property_changed'] and report['provider_contracts_verified']
    assert report['module_count'] == 202 and report['embedded_modules'] == 55
    assert sha(X / 'dtb-build/candidate-source.tar.zst') == report['candidate_source_archive_sha256']
    assert sha(X / 'dtb-build/candidate-source-files.json') == report['candidate_source_manifest_sha256']
    module_rows = json.loads((X / 'build/module-sha256.json').read_text())
    assert len(module_rows) == 217 and files(Path('/usr/lib/modules') / RELEASE) == module_rows
    assert links(Path('/usr/lib/modules') / RELEASE) == json.loads((X / 'build/module-links.json').read_text())
    assert Path('/boot/grub/custom.cfg').read_bytes() == (X / 'entry.cfg').read_bytes()
    assert sha(X / 'independent-preparation-review.json') == a['independent_preparation_review_sha256']
    independent = json.loads((X / 'independent-preparation-review.json').read_text())
    assert independent['source_archive_stream_verified'] and independent['source_paths_checked'] == 84669
    assert independent['exactly_one_raw_and_boot_property_delta'] and independent['kernel_modules_initramfs_reused_exact_bc']
    assert independent['archive_review_sha256'] == sha(X / 'archive-review.json')
'''

SOURCE = '''
def source():
    rows = json.loads((X / 'dtb-build/candidate-source-files.json').read_text())
    assert len(rows) == 96938
    checked = 0
    for name, row in rows.items():
        top = Path(name).parts[0]
        if not (top in CODE_DIRS or name in CODE_TOP or name.startswith('localversion') or
                (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
            continue
        path = REPO / name
        if 'sha256' in row:
            assert sha(path) == row['sha256'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
        checked += 1
    assert checked == 84669
    assert sha(REPO / '.config') == sha(X / 'dtb-build/live-config-before')
    expected = json.loads((X / 'dt-input-files-sha256.json').read_text())
    assert set(expected) == {'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'}
    for name, digest in expected.items():
        assert sha(REPO / name) == digest, name
    return checked
'''


def main():
    manifest = json.loads((PARENT / 'sha256.json').read_text())
    assert hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest() == \
        'a890f8eeee8f879eb5e821de5e35cf3413f6d7451e28f66781f554ac2d5ece21'
    outputs, changes = {}, {}
    for name in NAMES:
        origin = PARENT / name
        assert hashlib.sha256(origin.read_bytes()).hexdigest() == manifest[name]
        text = origin.read_text().replace(RELEASE, '__BD_EXACT_PARENT_RELEASE__').replace(IMAGE, '__BD_PARENT_IMAGE__')
        text = text.replace('20261004bc', '20261004bd').replace('e00a2d25-03f7-4265-b56e-0eac05b234d3',
                    '78d60cce-ef40-4cea-93e1-42727db4a851')
        text = re.sub(r'\bbc(?=[-_.])', 'bd', text).replace('BC', 'BD')
        text = text.replace('__BD_EXACT_PARENT_RELEASE__', RELEASE).replace('__BD_PARENT_IMAGE__', IMAGE)
        target = re.sub(r'\bbc(?=[-_.])', 'bd', name)
        if target == 'bd_boot_guard.py':
            text = function(text, 'artifacts', ARTIFACTS)
            text = function(text, 'source', SOURCE)
        if target == 'review-bd-baseline.py':
            old = "for name, digest in (a['sha256'] | a['recovery_sha256'] |"
            assert text.count(old) == 1
            text = text.replace(old, "assert files(X / 'dtb-build') == json.loads((X / 'dtb-sha256.json').read_text())\n" + old)
        ast.parse(text)
        assert not (SRC / target).exists(), target
        outputs[target] = text
        changes[target] = dict(parent_name=name, parent_sha256=manifest[name],
                              collector_logic_exact_except_identity=target not in ('bd_boot_guard.py', 'review-bd-baseline.py'))
    for name, text in outputs.items():
        with (SRC / name).open('x') as stream:
            stream.write(text)
        changes[name]['sha256'] = hashlib.sha256((SRC / name).read_bytes()).hexdigest()
    print(json.dumps(dict(helpers=len(outputs), release=RELEASE,
        expected_kernel_image=IMAGE, parent_runtime_manifest_sha256=hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest(),
        changes=changes, installed=False, boot_selected=False), indent=2))


if __name__ == '__main__':
    main()
