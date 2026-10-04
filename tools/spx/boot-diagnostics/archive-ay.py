#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify and durably archive AY's full private startup candidate."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ax_boot_guard as g

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
STAGE = Path('/var/tmp/spx-mainline-trial-20261003ay')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ay')
BOOT = 'b6b4f20b-376f-4577-b282-677ad4ae0ec8'
RELEASE = '7.3.0-rc2-spx-mainline-20261003ay+'
SRC = REPO / 'tools/spx/boot-diagnostics'


def verified_copy(source, target):
    expected, symlinks = g.files(source), g.links(source)
    shutil.copytree(source, target, symlinks=True)
    assert g.files(target) == expected and g.links(target) == symlinks
    return dict(files=len(expected), links=len(symlinks))


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    source = json.loads((STAGE / 'source-files.json').read_text())
    assert len(source) == 96938
    for name, row in source.items():
        path = STAGE / 'source' / name
        if 'sha256' in row:
            assert g.sha(path) == row['sha256'] and path.stat().st_size == row['bytes'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
    changed = json.loads((STAGE / 'compiled-source-delta.json').read_text())
    assert len(changed) == 13
    assert all(g.sha(REPO / name) == row['after_sha256'] for name, row in changed.items())
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 201
    assert built['full_kernel_linked'] and built['loadable_modules_linked']
    assert built['embedded_config_exact'] and built['source_snapshot_unchanged']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    assembled = json.loads((STAGE / 'build-verification.json').read_text())
    assert assembled['release'] == RELEASE and assembled['modules'] == 201
    assert assembled['module_tree_files'] == 216 and assembled['embedded_modules'] == 54
    assert assembled['embedded_module_payloads_exact'] and assembled['private_logger_exact']
    for name, digest in assembled['artifacts'].items():
        assert g.sha(STAGE / name) == digest, name
    archive = json.loads((STAGE / 'source-tar.json').read_text())
    assert archive['source_archive_stream_verified'] and archive['records_verified'] == len(source)
    assert g.sha(STAGE / 'source.tar.zst') == archive['sha256']
    assert (REPO / '.config').read_bytes() == (STAGE / 'live-config-before').read_bytes()
    parent = g.X / 'return-result'
    assert g.files(parent) == json.loads((parent / 'sha256.json').read_text()) | {'sha256.json': g.sha(parent / 'sha256.json')}
    result = json.loads((parent / 'result.json').read_text())
    assert result['returned_boot_id'] == BOOT and result['baseline_recomputed_exact']
    X.mkdir(mode=0o700)
    build = X / 'build'
    shutil.copytree(STAGE, build, symlinks=True,
                    ignore=lambda path, names: {'source', 'work-build'} if Path(path) == STAGE else set())
    # The source tar is self-contained; the live source/work-build remain private
    # immutable stage paths. Their installed module symlinks are recorded below.
    staged = build / 'module-root/lib/modules' / RELEASE
    assert g.files(staged) == json.loads((build / 'module-sha256.json').read_text())
    (build / 'module-links.json').write_text(json.dumps(g.links(staged), indent=2) + '\n')
    for name in ('source-commit.txt', 'source-status.txt', 'source.diff'):
        shutil.copy2(g.X / 'build' / name, build / ('parent-' + name))
    shutil.copy2(g.X / 'working-recovery.json', X / 'working-recovery.json')
    preparation = X / 'preparation'
    preparation.mkdir(mode=0o700)
    helpers = preparation / 'helpers'
    helpers.mkdir(mode=0o700)
    for name in ('build-ay.py', 'assemble-ay.py', 'archive-ay.py', 'ay_boot_guard.py', 'ay-video.py', 'ay-return.py'):
        shutil.copy2(SRC / name, helpers / name)
    for name in ('verify_integration.py', 'prepare_dtb.py', 'INTEGRATION.md'):
        shutil.copy2(SRC / 'video-power-20261003' / name, helpers / name)
    inputs = {}
    for version in range(1, 6):
        path = Path(f'/var/tmp/spx-video-integrated-review-20261003-v{version}')
        inputs[f'integration-v{version}'] = verified_copy(path, preparation / f'integration-v{version}')
        for suffix in ('stdout', 'stderr'):
            external = Path(str(path) + '.' + suffix)
            if external.exists():
                shutil.copy2(external, preparation / f'integration-v{version}.{suffix}')
    # Preserve the manually captured first failure and the independent rejection
    # comparison along with their exact source/logs, rather than hiding them.
    native = json.loads((preparation / 'integration-v5/result.json').read_text())
    assert native['native'] == dict(resume_cases=10, sys_init_cases=12, firmware_cases=16)
    assert len(native['binding_negative_controls']) == 4 and len(native['native_negative_controls']) == 3
    for name in ('spx-ay-runtime-review.json', 'spx-ay-document-review.json', 'spx-ay-code.patch', 'spx-ay-binding.patch',
                 'spx-ay-checkpatch.stdout', 'spx-ay-checkpatch.stderr',
                 'spx-ay-code-checkpatch.stdout', 'spx-ay-code-checkpatch.stderr',
                 'spx-ay-binding-checkpatch.stdout', 'spx-ay-binding-checkpatch.stderr',
                 'spx-ay-provider-dtb.stdout', 'spx-ay-provider-dtb.stderr',
                 'spx-ay-provider-dtb-v2.stdout', 'spx-ay-provider-dtb-v2.stderr'):
        shutil.copy2(Path('/var/tmp') / name, preparation / name)
    for name in ('spx-ay-code-checkpatch.stdout', 'spx-ay-binding-checkpatch.stdout'):
        assert 'total: 0 errors, 0 warnings, 0 checks' in (preparation / name).read_text()
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert g.sha(firmware) == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    shutil.copy2(firmware, preparation / 'installed-00042.mbn')
    (X / 'build-sha256.json').write_text(json.dumps(g.files(build), indent=2) + '\n')
    (X / 'build-symlinks.json').write_text(json.dumps(g.links(build), indent=2) + '\n')
    (X / 'preparation-sha256.json').write_text(json.dumps(g.files(preparation), indent=2) + '\n')
    review = dict(utc=datetime.now(timezone.utc).isoformat(), release=RELEASE, boot_id=BOOT,
        source_archive_stream_verified=True, source_files_verified=96938,
        source_delta_files=13, embedded_config_exact=True, full_kernel_and_modules_linked=True,
        module_count=201, module_tree_files=216, private_initramfs_verified=True,
        embedded_modules=54, prior_boot_tree_property_values_exact=True,
        native_cases=38, native_negative_controls=3, binding_negative_controls=4,
        build_files=len(g.files(build)), build_links=len(g.links(build)), preparation_inputs=inputs,
        parent_attempt='20261003ax', parent_return_manifest_sha256=g.sha(parent / 'sha256.json'),
        build_manifest_sha256=g.sha(X / 'build-sha256.json'),
        preparation_manifest_sha256=g.sha(X / 'preparation-sha256.json'),
        recovery_definition_sha256=g.sha(X / 'working-recovery.json'),
        boot_selected=False, installed=False, hardware_acceptance_closed=False)
    (X / 'archive-review.json').write_text(json.dumps(review, indent=2) + '\n')
    assert g.files(build) == json.loads((X / 'build-sha256.json').read_text())
    assert g.files(preparation) == json.loads((X / 'preparation-sha256.json').read_text())
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    os.sync()
    print(json.dumps(review))


if __name__ == '__main__':
    main()
