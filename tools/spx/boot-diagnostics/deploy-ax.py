#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install the archived full AX candidate and bounded GPU collection; select nothing."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess

from ax_boot_guard import BASE, X, RELEASE, REPO, RUNTIME, FIXTURE, TIMERS, sha, files, links, source, recovery, preboot

SRC = REPO / 'tools/spx/boot-diagnostics'
GPU = BASE / 'gpu-workloads/20261003au'
PARENT = BASE / 'attempts/20261003aw'
BOOT = Path('/boot/spx-trial-20261003ax')
HELPERS = ('ax-baseline.py', 'ax-return.py', 'ax_boot_guard.py', 'ax-camera-provider.py',
           'ax-camera-control.py', 'ax_camera_core.py', 'review-ax-baseline.py',
           'ax-gpu.py', 'ax-finalize.py', 'ax_gpu_core.py',
           'ax-rtc.py', 'ax_rtc_core.py', 'ax_rtc_review.py')


def write(path, text, mode=0o600):
    with path.open('x') as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    path.chmod(mode)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert FIXTURE.is_dir() and not (Path('/usr/lib/modules') / RELEASE).exists()
    assert not (X / 'attempt.json').exists() and not BOOT.exists()
    assert not (X / 'deploy-started').exists()
    parent_return = json.loads((PARENT / 'return-result/result.json').read_text())
    for name in ('return-result', 'final-result', 'gpu-final-result'):
        root = PARENT / name
        manifest = json.loads((root / 'sha256.json').read_text())
        assert files(root) == manifest | {'sha256.json': sha(root / 'sha256.json')}
    assert parent_return['returned_boot_id'] == 'fbc6d663-8269-4d2f-9aac-c4a687583b00'
    assert parent_return['baseline_recomputed_exact'] and parent_return['original_workload_exact']
    assert parent_return['gpu_verdict']['planned_render_seconds_completed'] == 1800
    assert parent_return['persistent_default'] == 'spx-known-good' and parent_return['next_entry_empty']
    parent = json.loads((PARENT / 'attempt.json').read_text())
    # Working recovery is unchanged from AT; source/artifact guards below use AX.
    env = recovery(parent)
    assert not env.get('next_entry', '')
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    review = json.loads((X / 'archive-review.json').read_text())
    assert bid == parent_return['returned_boot_id'] == 'fbc6d663-8269-4d2f-9aac-c4a687583b00'
    assert os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '4096'
    assert sha(X / 'preparation-sha256.json') == '5fc5c3e4860a375cc14cd6e40da0f8ec113a844cd3737ea1816499cb38f5576a'
    for name, digest in json.loads((X / 'preparation-sha256.json').read_text()).items():
        assert sha(X / name) == digest, name
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert links(X / 'build') == json.loads((X / 'build-symlinks.json').read_text())
    assert sha(X / 'build-sha256.json') == review['build_manifest_sha256']
    assert review['source_archive_stream_verified'] and review['current_exports_full_build']
    assert review['both_payload_configs_exact'] and review['config_delta_exact']
    source_count = source()
    rtc = X / 'rtc-observer-preparation'
    manifest = json.loads((rtc / 'sha256.json').read_text())
    assert files(rtc) == manifest | {'sha256.json': sha(rtc / 'sha256.json')}
    assert sha(rtc / 'sha256.json') == '9b94591a004a6989f69d8aa87fbc5bac4be2a6c5e888e1dd523b3bdc563dfaf3'
    assert (SRC / 'ax-rtc.py').read_bytes() == (rtc / 'ax-rtc.py').read_bytes()
    assert (SRC / 'ax_rtc_core.py').read_bytes() == (rtc / 'ax_rtc_core.py').read_bytes()
    assert sha(GPU / 'sha256.json') == review['gpu_preparation_manifest_sha256']
    assert files(GPU) == json.loads((GPU / 'sha256.json').read_text()) | {'sha256.json': sha(GPU / 'sha256.json')}
    staged = X / 'build/module-root/lib/modules' / RELEASE
    modules = json.loads((X / 'build/module-sha256.json').read_text())
    assert len(modules) == 208 and files(staged) == modules
    binaries = sorted(staged.rglob('*.ko'))
    assert len(binaries) == 193
    for path in binaries:
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).split()[0] == RELEASE
    cmdline = parent['cmdline'].replace('spx_attempt=20261003aw', 'spx_attempt=20261003ax')
    assert set(cmdline.split()) - set(parent['cmdline'].split()) == {'spx_attempt=20261003ax'}
    entry = (PARENT / 'entry.cfg').read_text().replace('20261003aw', '20261003ax')
    entry = entry.replace('AW sustained GPU', 'AX RTC and GPU')
    assert entry.count('--id spx-trial-20261003ax') == 1 and (' ' + cmdline + '; then') in entry
    write(X / 'entry.cfg.preview', entry)
    subprocess.run(['grub-script-check', str(X / 'entry.cfg.preview')], check=True, timeout=30)
    helpers = {name: RUNTIME / name for name in HELPERS}
    helpers['ax-reboot-check.py'] = X / 'reboot-check.py'
    for name, target in helpers.items():
        assert not target.exists()
        ast.parse((SRC / name).read_text())
    gpu_runtime = RUNTIME / 'gpu-workload-20261003ax'
    assert not gpu_runtime.exists()
    actions = {'rtc': 'ax-rtc.py', 'camera-provider': 'ax-camera-provider.py', 'camera-control': 'ax-camera-control.py',
               'baseline': 'ax-baseline.py', 'gpu': 'ax-gpu.py',
               'finalize': 'ax-finalize.py', 'fallback': 'ax-return.py'}
    units = {}
    for action, delay in TIMERS.items():
        timeout = 2750 if action == 'rtc' else (2400 if action == 'gpu' else 180)
        units[f'spx-ax-{action}.service'] = (
            f'[Unit]\nDescription=AX sustained GPU trial {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261003ax\nAfter=local-fs.target\n'
            'RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot /var/tmp\n\n'
            f'[Service]\nType=oneshot\nExecStart={RUNTIME / actions[action]}\n'
            f'TimeoutStartSec={timeout}\nKillMode=control-group\n')
        units[f'spx-ax-{action}.timer'] = (
            f'[Unit]\nDescription=AX {action} timer\nConditionKernelCommandLine=spx_attempt=20261003ax\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ax-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
    for name in units:
        assert not (Path('/etc/systemd/system') / name).exists()
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/120-ax-exclude.conf')
    assert not exclude.exists()
    payloads = {'vmlinuz': X / 'build/vmlinuz', 'initramfs.img': X / 'build/initramfs.img',
                'spx.dtb': X / 'build/dtb-build/spx.dtb'}
    capacity = os.statvfs('/boot')
    assert capacity.f_bavail * capacity.f_frsize > sum(p.stat().st_size for p in payloads.values()) + 1048576
    prior = X / 'preinstall-state'
    prior.mkdir(mode=0o700)
    for name, path in [('active-attempt.json', BASE / 'attempt.json'),
                       ('custom.cfg', Path('/boot/grub/custom.cfg')), ('grub.cfg', Path('/boot/grub/grub.cfg'))]:
        shutil.copy2(path, prior / name)
    # Freeze the 24 original AT helpers independently; do not edit them.
    original = json.loads((BASE / 'attempts/20261003at/deployment-sources-sha256.json').read_text())
    assert len(original) == 24
    for name, digest in original.items():
        assert sha(SRC / name) == digest, name
    write(prior / 'original-at-helpers-sha256.json', json.dumps(original, indent=2) + '\n')
    write(prior / 'sha256.json', json.dumps(files(prior), indent=2) + '\n')
    write(X / 'deploy-started', bid + '\n')
    shutil.copytree(staged, Path('/usr/lib/modules') / RELEASE, symlinks=True)
    assert files(Path('/usr/lib/modules') / RELEASE) == modules
    assert links(Path('/usr/lib/modules') / RELEASE) == links(staged)
    BOOT.mkdir(mode=0o700)
    for name, path in payloads.items():
        shutil.copy2(path, BOOT / name)
        assert sha(BOOT / name) == sha(path)
    write(X / 'entry.cfg', entry)
    write(Path('/boot/grub/custom.cfg.ax-new'), entry, 0o644)
    os.replace('/boot/grub/custom.cfg.ax-new', '/boot/grub/custom.cfg')
    assert Path('/boot/grub/grub.cfg').read_bytes() == (prior / 'grub.cfg').read_bytes()
    for name, target in helpers.items():
        shutil.copy2(SRC / name, target)
        target.chmod(0o755)
    probe_target = RUNTIME / 'rtc-readonly-20261003ax'
    assert not probe_target.exists()
    shutil.copy2(X / 'rtc-observer-preparation/rtc-readonly', probe_target)
    probe_target.chmod(0o755)
    gpu_runtime.mkdir(mode=0o755)
    for name in ('collect.py', 'plan.json'):
        shutil.copy2(SRC / 'gpu-workload-20261003ax' / name, gpu_runtime / name)
        (gpu_runtime / name).chmod(0o755 if name.endswith('.py') else 0o644)
    gpu_runtime.chmod(0o755)
    assert FIXTURE.parent.stat().st_uid == 0 and FIXTURE.parent.stat().st_mode & 0o777 == 0o755
    fixture = json.loads((FIXTURE / 'sha256.json').read_text())
    assert files(FIXTURE) == fixture | {'sha256.json': sha(FIXTURE / 'sha256.json')}
    assert sha(FIXTURE / 'sha256.json') == sha(GPU / 'fixture/sha256.json')
    for path in [FIXTURE] + list(FIXTURE.rglob('*')):
        assert not path.is_symlink() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o022
    for name, text in units.items():
        write(Path('/etc/systemd/system') / name, text, 0o644)
    write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20261003ax\n', 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    subprocess.run(['systemctl', 'enable'] + ['spx-ax-' + n + '.timer' for n in TIMERS], check=True, timeout=30)
    runtime = list(helpers.values()) + [probe_target, exclude, RUNTIME / 'return.sh', RUNTIME / 'collect.sh']
    runtime += [Path('/etc/systemd/system') / n for n in units]
    runtime += [gpu_runtime / name for name in ('collect.py', 'plan.json')]
    r = json.loads((X / 'working-recovery.json').read_text())
    a = {'attempt': '20261003ax', 'entry': 'spx-trial-20261003ax', 'release': RELEASE,
         'preboot_id': bid, 'preboot_release': os.uname().release,
         'preboot_cmdline': Path('/proc/cmdline').read_text().strip(), 'preboot_taint': '4096',
         'cmdline': cmdline, 'state': 'prepared AX; no boot selection', 'parent_attempt': '20261003aw',
         'sha256': {str(BOOT / n): sha(BOOT / n) for n in payloads},
         'recovery_sha256': r['payload_sha256'], 'recovery_definition_sha256': sha(X / 'working-recovery.json'),
         'runtime_sha256': {str(p): sha(p) for p in runtime},
         'build_manifest_sha256': sha(X / 'build-sha256.json'), 'archive_review_sha256': sha(X / 'archive-review.json'),
         'build_files_verified': len(json.loads((X / 'build-sha256.json').read_text())),
         'build_links_verified': len(json.loads((X / 'build-symlinks.json').read_text())),
         'gpu_fixture_manifest_sha256': sha(FIXTURE / 'sha256.json'),
         'parent_result_manifest_sha256': sha(PARENT / 'final-result/sha256.json'),
         'parent_post_result_manifest_sha256': sha(PARENT / 'post-result-records/sha256.json'),
         'parent_return_manifest_sha256': sha(PARENT / 'return-result/sha256.json'),
         'parent_gpu_final_manifest_sha256': sha(PARENT / 'gpu-final-result/sha256.json'),
         'gpu_preparation_manifest_sha256': sha(X / 'gpu-preparation/sha256.json'),
         'authorization': parent['authorization'], 'return_window_seconds': 600,
         'fallback_seconds': 3300, 'planned_gpu_render_seconds': 1800, 'planned_gpu_idle_seconds': 180,
         'source_commit': (X / 'build/source-commit.txt').read_text().strip(),
         'source_diff': str(X / 'build/source.diff'), 'build_archive': str(X / 'build'),
         'compiled_live_source_paths_verified': source_count,
         'playback_requested': False, 'camera_consumers_enabled': True,
         'early_recovery_validated': False, 'hardware_acceptance_closed': False,
         'kernel_reused_exact_au': False, 'rtc_config_candidate': True,
         'preparation_manifest_sha256': sha(X / 'preparation-sha256.json'),
         'rtc_preparation_manifest_sha256': sha(X / 'rtc-observer-preparation/sha256.json'),
         'rtc_probe_sha256': sha(probe_target),
         'comparison': 'Distinct AX image/modules/private initramfs add RTC synchronization to unchanged AU code and AT camera DTB. Read-only RTC30 through2600, strict baseline620/GPU660/combined review2800/unconditional recovery3300. No retention or physical feature acceptance.'}
    write(X / 'attempt.json', json.dumps(a, indent=2) + '\n')
    write(BASE / 'attempt-ax.new.json', json.dumps(a, indent=2) + '\n')
    os.replace(BASE / 'attempt-ax.new.json', BASE / 'attempt.json')
    preboot(a)
    os.sync()
    print('AX installed and fully guarded; persistent known-good default, no boot selected')


if __name__ == '__main__':
    main()
