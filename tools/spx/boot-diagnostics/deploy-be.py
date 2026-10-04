#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install BE's sealed DT-only candidate while leaving boot selection empty."""
from datetime import datetime, timezone
import difflib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
SRC = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as old
sys.path.insert(0, str(SRC))
import be_boot_guard as guard

X, BASE, RUNTIME = guard.X, guard.BASE, guard.RUNTIME
BOOT = Path('/boot/spx-trial-20261004be')
BOOT_ID = '433a78d6-9748-422f-a1a7-aac43c784a7d'


def read(path):
    return json.loads(path.read_text())


def write(path, text, mode=0o600):
    with path.open('x') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(mode)


def write_json(path, value):
    write(path, json.dumps(value, indent=2) + '\n')


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    assert os.uname().release == '6.18.3-1-surface+'
    parent = old.load()
    assert parent['state'].startswith('BD terminal;')
    assert not old.recovery(parent).get('next_entry', '')
    old.artifacts(parent)
    assert not (X / 'attempt.json').exists() and not (X / 'deploy-started').exists() and not BOOT.exists()
    archive = read(X / 'archive-review.json')
    independent = read(X / 'independent-preparation-review.json')
    runtime_review = read(X / 'independent-runtime-preparation-review.json')
    assert independent['boot_id'] == runtime_review['boot_id'] == BOOT_ID
    assert independent['archive_review_sha256'] == runtime_review['compiled_candidate_archive_review_sha256'] == guard.sha(X / 'archive-review.json')
    assert archive['kernel_modules_initramfs_reused_exact_bc'] and archive['exactly_one_reserved_memory_node_changed']
    assert guard.files(X / 'build') == read(X / 'build-sha256.json')
    assert guard.links(X / 'build') == read(X / 'build-symlinks.json')
    assert guard.files(X / 'dtb-build') == read(X / 'dtb-sha256.json')
    assert guard.files(X / 'preparation') == read(X / 'preparation-sha256.json')
    assert guard.sha(X / 'preparation-sha256.json') == runtime_review['preparation_manifest_sha256']
    plan = X / 'preparation/runtime-plan'
    expected = read(plan / 'sha256.json')
    assert guard.files(plan) == expected | {'sha256.json': guard.sha(plan / 'sha256.json')}
    assert guard.sha(plan / 'sha256.json') == runtime_review['runtime_plan_manifest_sha256']
    spec = importlib.util.spec_from_file_location('be_frozen_runtime_plan', plan / 'prepare-be-runtime.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    for name in config.HELPERS:
        assert not (RUNTIME / name).exists()
        assert guard.sha(SRC / name) == expected[name]
    modules = read(X / 'build/module-sha256.json')
    assert len(modules) == 217 and guard.files(Path('/usr/lib/modules') / guard.RELEASE) == modules
    assert guard.links(Path('/usr/lib/modules') / guard.RELEASE) == read(X / 'build/module-links.json')
    assert guard.source() == 84669
    cmdline = (plan / 'cmdline').read_text().strip()
    assert cmdline == parent['cmdline'].replace('spx_attempt=20261004bd', 'spx_attempt=20261004be')
    entry = (plan / 'entry.cfg').read_text()
    subprocess.run(['grub-script-check', str(plan / 'entry.cfg')], check=True, timeout=30)
    units = sorted(plan.glob('spx-be-*.service')) + sorted(plan.glob('spx-be-*.timer'))
    assert len(units) == 12
    for path in units:
        assert not (Path('/etc/systemd/system') / path.name).exists()
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/124-be-exclude.conf')
    assert not exclude.exists()
    payloads = {Path('/boot/spx-trial-20261004bc/vmlinuz'): X / 'build/vmlinuz',
                Path('/boot/spx-trial-20261004bc/initramfs.img'): X / 'build/initramfs.img',
                BOOT / 'spx.dtb': X / 'dtb-build/spx.dtb'}
    for target, source in payloads.items():
        if target.parent != BOOT:
            assert guard.sha(target) == guard.sha(source)
    capacity = os.statvfs('/boot')
    assert capacity.f_bavail * capacity.f_frsize > (X / 'dtb-build/spx.dtb').stat().st_size + 1048576
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert guard.sha(firmware) == guard.sha(X / 'preparation/installed-00042.mbn') == runtime_review['firmware_sha256']
    prep = X / 'deployment-preparation'
    prep.mkdir(mode=0o700)
    shutil.copy2(__file__, prep / 'deploy-be.py')
    shutil.copy2(plan / 'entry.cfg', prep / 'entry.cfg')
    before = (X / 'dtb-build/source-before.dts').read_text().splitlines(True)
    after = (X / 'dtb-build/source-after.dts').read_text().splitlines(True)
    write(prep / 'allocation.diff', ''.join(difflib.unified_diff(before, after,
        fromfile='a/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts',
        tofile='b/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts')))
    for path in (BASE / 'attempt.json', Path('/boot/grub/custom.cfg'), Path('/boot/grub/grub.cfg')):
        shutil.copy2(path, prep / ('previous-' + path.name))
    write_json(prep / 'sha256.json', guard.files(prep))
    # From this point a repeat must inspect the preserved partial deployment.
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    assert not old.recovery(parent).get('next_entry', '')
    write(X / 'deploy-started', BOOT_ID + '\n')
    BOOT.mkdir(mode=0o700)
    shutil.copy2(X / 'dtb-build/spx.dtb', BOOT / 'spx.dtb')
    for target, source in payloads.items():
        assert guard.sha(target) == guard.sha(source)
    write(X / 'entry.cfg', entry)
    write(Path('/boot/grub/custom.cfg.be-new'), entry, 0o644)
    os.replace('/boot/grub/custom.cfg.be-new', '/boot/grub/custom.cfg')
    assert Path('/boot/grub/grub.cfg').read_bytes() == (prep / 'previous-grub.cfg').read_bytes()
    for name in config.HELPERS:
        shutil.copy2(plan / name, RUNTIME / name)
        (RUNTIME / name).chmod(0o755)
    for path in units:
        target = Path('/etc/systemd/system') / path.name
        shutil.copy2(path, target)
        target.chmod(0o644)
    shutil.copy2(plan / exclude.name, exclude)
    exclude.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    subprocess.run(['systemctl', 'enable'] + ['spx-be-' + name + '.timer' for name in config.ACTIONS], check=True, timeout=30)
    runtime_paths = [RUNTIME / name for name in config.HELPERS]
    runtime_paths += [Path('/etc/systemd/system') / p.name for p in units]
    runtime_paths += [exclude, RUNTIME / 'return.sh', RUNTIME / 'collect.sh']
    recovery = read(X / 'working-recovery.json')
    a = dict(attempt='20261004be', entry='spx-trial-20261004be', release=guard.RELEASE,
        utc=datetime.now(timezone.utc).isoformat(), parent_attempt='20261004bd',
        preboot_id=BOOT_ID, preboot_release=os.uname().release,
        preboot_cmdline=Path('/proc/cmdline').read_text().strip(), preboot_taint='4096',
        cmdline=cmdline, state='prepared BE; no boot selection',
        sha256={str(target): guard.sha(target) for target in payloads},
        recovery_sha256=recovery['payload_sha256'], recovery_definition_sha256=guard.sha(X / 'working-recovery.json'),
        runtime_sha256={str(path): guard.sha(path) for path in runtime_paths},
        runtime_plan_manifest_sha256=guard.sha(plan / 'sha256.json'),
        preparation_manifest_sha256=guard.sha(X / 'preparation-sha256.json'),
        build_manifest_sha256=guard.sha(X / 'build-sha256.json'),
        dtb_manifest_sha256=guard.sha(X / 'dtb-sha256.json'),
        archive_review_sha256=guard.sha(X / 'archive-review.json'),
        independent_preparation_review_sha256=guard.sha(X / 'independent-preparation-review.json'),
        independent_runtime_preparation_review_sha256=guard.sha(X / 'independent-runtime-preparation-review.json'),
        build_files_verified=archive['build_files_verified'], build_links_verified=archive['build_links_verified'],
        deployment_preparation_manifest_sha256=guard.sha(prep / 'sha256.json'),
        parent_return_manifest_sha256=archive['parent_return_manifest_sha256'],
        custom_cfg_sha256=guard.sha('/boot/grub/custom.cfg'), authorization=parent['authorization'],
        return_window_seconds=600, fallback_seconds=900, source_commit=parent['source_commit'],
        source_diff=str(prep / 'allocation.diff'), build_archive=str(X / 'build'),
        candidate_source_archive=str(X / 'dtb-build/candidate-source.tar.zst'),
        kernel_modules_initramfs_reused_exact_bc=True, external_dt_only_source_delta=archive['external_dt_only_source_delta'],
        camera_consumers_enabled=True, early_recovery_validated=False, hardware_acceptance_closed=False,
        playback_requested=False, media_short_requested=True, pas_diagnostics_requested=True,
        pas_area_query_requested=True, media_fixture_manifest_sha256=parent['media_fixture_manifest_sha256'])
    write_json(X / 'attempt.json', a)
    write_json(BASE / 'attempt-be.new.json', a)
    os.replace(BASE / 'attempt-be.new.json', BASE / 'attempt.json')
    state = guard.preboot(a)
    write_json(X / 'deployed-preboot-review.json', state)
    os.sync()
    print('BE installed and guarded; known-good remains default, no boot selected')


if __name__ == '__main__':
    main()
