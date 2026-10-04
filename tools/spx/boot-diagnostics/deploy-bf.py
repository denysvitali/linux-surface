#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install BF's reviewed fresh executable and runtime with no boot selection."""
import ast
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as old
sys.path.insert(0, str(HERE))
import bf_boot_guard as guard

X, BASE, RUNTIME = guard.X, guard.BASE, guard.RUNTIME
BOOT = Path('/boot/spx-trial-20261004bf')
BOOT_ID = 'c1cea488-ecf7-403e-9581-127ff365fb1e'


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
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    parent = old.load()
    assert parent['state'].startswith('BE terminal;') and not old.recovery(parent).get('next_entry', '')
    old.artifacts(parent)
    module_target = Path('/usr/lib/modules') / guard.RELEASE
    for path in (X / 'attempt.json', X / 'deploy-started', BOOT, module_target): assert not path.exists(), path
    independent = read(X / 'independent-preparation-review.json')
    assert guard.sha(X / 'independent-preparation-review.json') == 'cf799de05795c37cd94d7289255a896a80ae685fb518478cec7d3bd99279d4a8'
    assert independent['boot_id'] == BOOT_ID and independent['source_paths_checked'] == 84669
    assert independent['full_bf_executable_and_initramfs_verified'] and independent['source_archive_stream_verified']
    assert independent['assembly_review_sha256'] == guard.sha(X / 'assembly-review.json')
    assert guard.files(X / 'build') == read(X / 'build-sha256.json')
    assert guard.files(X / 'assembly') == read(X / 'assembly-sha256.json')
    assert guard.links(X / 'assembly') == read(X / 'assembly-symlinks.json')
    assert guard.files(X / 'preparation') == read(X / 'preparation-sha256.json')
    assert guard.files(X / 'preparation-reviewed') == read(X / 'preparation-reviewed-sha256.json')
    assert guard.sha(X / 'preparation-reviewed-sha256.json') == independent['preparation_manifest_sha256']
    plan = X / 'preparation-reviewed/runtime-plan'
    expected = read(plan / 'sha256.json')
    assert guard.files(plan) == expected | {'sha256.json': guard.sha(plan / 'sha256.json')}
    assert guard.sha(plan / 'sha256.json') == independent['runtime_plan_manifest_sha256']
    spec = importlib.util.spec_from_file_location('bf_frozen_plan', plan / 'prepare-bf-runtime.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    assert len(config.HELPERS) == 14 and len(config.ACTIONS) == 6
    for name in config.HELPERS:
        assert not (RUNTIME / name).exists()
        assert guard.sha(HERE / name) == expected[name]
        ast.parse((plan / name).read_text())
    staged = X / 'assembly/module-root/lib/modules' / guard.RELEASE
    modules = read(X / 'assembly/module-sha256.json')
    assert len(modules) == 217 and guard.files(staged) == modules
    assert guard.links(staged) == read(X / 'assembly/module-links.json')
    assert guard.source() == 84669
    cmdline = (plan / 'cmdline').read_text().strip()
    assert cmdline == parent['cmdline'].replace('spx_attempt=20261004be', 'spx_attempt=20261004bf') + ' venus_core.spx_hfi_startup_diag=1'
    for flag in ('qcom_scm.spx_pas_diag=1', 'qcom_scm.spx_pas_area_diag=1', 'venus_core.spx_hfi_startup_diag=1'):
        assert cmdline.split().count(flag) == 1
    entry = (plan / 'entry.cfg').read_text()
    subprocess.run(['grub-script-check', str(plan / 'entry.cfg')], check=True, timeout=30)
    units = sorted(plan.glob('spx-bf-*.service')) + sorted(plan.glob('spx-bf-*.timer'))
    assert len(units) == 12
    for path in units: assert not (Path('/etc/systemd/system') / path.name).exists()
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/125-bf-exclude.conf')
    assert not exclude.exists()
    payloads = {BOOT / 'vmlinuz': X / 'assembly/vmlinuz', BOOT / 'initramfs.img': X / 'assembly/initramfs.img',
                BOOT / 'spx.dtb': X / 'assembly/dtb-build/spx.dtb'}
    capacity = os.statvfs('/boot')
    assert capacity.f_bavail * capacity.f_frsize > sum(p.stat().st_size for p in payloads.values()) + 1048576
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert guard.sha(firmware) == guard.sha(X / 'preparation-reviewed/installed-00042.mbn') == independent['firmware_sha256']
    prep = X / 'deployment-preparation'
    prep.mkdir(mode=0o700)
    for name in ('deploy-bf.py', 'review-bf-deployment.py', 'PREPARED-20261004bf.md'):
        shutil.copy2(HERE / name, prep / name)
    shutil.copy2(plan / 'entry.cfg', prep / 'entry.cfg')
    for path in (BASE / 'attempt.json', Path('/boot/grub/custom.cfg'), Path('/boot/grub/grub.cfg')):
        shutil.copy2(path, prep / ('previous-' + path.name))
    write_json(prep / 'sha256.json', guard.files(prep))
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    assert not old.recovery(parent).get('next_entry', '')
    write(X / 'deploy-started', BOOT_ID + '\n')
    shutil.copytree(staged, module_target, symlinks=True)
    assert guard.files(module_target) == modules and guard.links(module_target) == read(X / 'assembly/module-links.json')
    BOOT.mkdir(mode=0o700)
    for target, source in payloads.items():
        shutil.copy2(source, target)
        assert guard.sha(target) == guard.sha(source)
    write(X / 'entry.cfg', entry)
    write(Path('/boot/grub/custom.cfg.bf-new'), entry, 0o644)
    os.replace('/boot/grub/custom.cfg.bf-new', '/boot/grub/custom.cfg')
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
    subprocess.run(['systemctl', 'enable'] + ['spx-bf-' + name + '.timer' for name in config.ACTIONS], check=True, timeout=30)
    runtime = [RUNTIME / name for name in config.HELPERS] + [Path('/etc/systemd/system') / p.name for p in units]
    runtime += [exclude, RUNTIME / 'return.sh', RUNTIME / 'collect.sh']
    recovery = read(X / 'working-recovery.json')
    a = dict(attempt='20261004bf', entry='spx-trial-20261004bf', release=guard.RELEASE,
        utc=datetime.now(timezone.utc).isoformat(), parent_attempt='20261004be',
        preboot_id=BOOT_ID, preboot_release=os.uname().release,
        preboot_cmdline=Path('/proc/cmdline').read_text().strip(), preboot_taint='4096',
        cmdline=cmdline, state='prepared BF; no boot selection',
        sha256={str(target): guard.sha(target) for target in payloads},
        runtime_sha256={str(path): guard.sha(path) for path in runtime},
        recovery_sha256=recovery['payload_sha256'], recovery_definition_sha256=guard.sha(X / 'working-recovery.json'),
        original_preparation_manifest_sha256=guard.sha(X / 'preparation-sha256.json'),
        preparation_manifest_sha256=guard.sha(X / 'preparation-reviewed-sha256.json'),
        runtime_plan_manifest_sha256=guard.sha(plan / 'sha256.json'),
        build_manifest_sha256=guard.sha(X / 'build-sha256.json'), build_review_sha256=guard.sha(X / 'build-review.json'),
        assembly_manifest_sha256=guard.sha(X / 'assembly-sha256.json'),
        assembly_symlinks_sha256=guard.sha(X / 'assembly-symlinks.json'), assembly_review_sha256=guard.sha(X / 'assembly-review.json'),
        independent_preparation_review_sha256=guard.sha(X / 'independent-preparation-review.json'),
        build_files_verified=243, build_links_verified=0, assembly_files_verified=818, assembly_links_verified=272,
        deployment_preparation_manifest_sha256=guard.sha(prep / 'sha256.json'),
        parent_return_manifest_sha256=guard.sha(old.X / 'return-review/sha256.json'),
        custom_cfg_sha256=guard.sha('/boot/grub/custom.cfg'), authorization=parent['authorization'],
        return_window_seconds=600, fallback_seconds=900, source_commit=parent['source_commit'],
        source_diff=str(X / 'assembly/source.diff'), build_archive=str(X / 'build'), assembly_archive=str(X / 'assembly'),
        candidate_source_archive=str(X / 'assembly/source.tar.zst'),
        full_fresh_bf_executable=True, camera_consumers_enabled=True, early_recovery_validated=False,
        hardware_acceptance_closed=False, playback_requested=False, media_short_requested=True,
        pas_diagnostics_requested=True, pas_area_query_requested=True, venus_startup_diagnostics_requested=True,
        media_fixture_manifest_sha256=parent['media_fixture_manifest_sha256'])
    write_json(X / 'attempt.json', a)
    write_json(BASE / 'attempt-bf.new.json', a)
    os.replace(BASE / 'attempt-bf.new.json', BASE / 'attempt.json')
    state = guard.preboot(a)
    write_json(X / 'deployed-preboot-review.json', state)
    os.sync()
    print('BF full candidate installed and guarded; known-good remains default, no boot selected', flush=True)


if __name__ == '__main__':
    main()
