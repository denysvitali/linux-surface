#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install the archived full AU candidate and bounded GPU collection; select nothing."""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess

from au_boot_guard import BASE, X, RELEASE, REPO, RUNTIME, FIXTURE, TIMERS, sha, files, links, source, recovery, preboot

SRC = REPO / 'tools/spx/boot-diagnostics'
GPU = BASE / 'gpu-workloads/20261003au'
PARENT = BASE / 'attempts/20261003at'
BOOT = Path('/boot/spx-trial-20261003au')
HELPERS = ('au-baseline.py', 'au-return.py', 'au_boot_guard.py', 'au-camera-provider.py',
           'au-camera-control.py', 'au_camera_core.py', 'review-au-baseline.py',
           'au-gpu.py', 'au-finalize.py', 'au_gpu_core.py')


def write(path, text, mode=0o600):
    with path.open('x') as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    path.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-fixture-permissions', action='store_true')
    resume = parser.parse_args().resume_fixture_permissions
    os.umask(0o077)
    assert os.geteuid() == 0
    assert not FIXTURE.exists() and not (X / 'attempt.json').exists()
    if resume:
        failure = json.loads((X / 'deployment-initial-failure/result.json').read_text())
        assert failure['active_attempt'] == '20261003at' and not failure['au_attempt_exists']
        assert failure['no_boot_selected'] and not failure['fixture_exists']
        assert (X / 'deploy-started').is_file()
    else:
        assert not BOOT.exists() and not (Path('/usr/lib/modules') / RELEASE).exists()
        assert not (X / 'deploy-started').exists()
    parent = json.loads((PARENT / 'attempt.json').read_text())
    # Working recovery is unchanged from AT; source/artifact guards below use AU.
    env = recovery(parent)
    assert not env.get('next_entry', '')
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    review = json.loads((X / 'archive-review.json').read_text())
    assert bid == review['preboot_id'] == '74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b'
    assert os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/tainted').read_text().strip() == '4096'
    assert sha(X / 'preparation-sha256.json') == 'c1d80ae71c5814b881a97a04dfd8d3365540e6448b24dcfeb9caadd07d3b582c'
    for name, digest in json.loads((X / 'preparation-sha256.json').read_text()).items():
        assert sha(X / name) == digest, name
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert links(X / 'build') == json.loads((X / 'build-symlinks.json').read_text())
    assert sha(X / 'build-sha256.json') == review['build_manifest_sha256']
    assert review['source_archive_stream_verified'] and review['current_exports_full_build']
    assert review['both_payload_configs_exact'] and review['config_delta_exact']
    source_count = source()
    assert sha(GPU / 'sha256.json') == review['gpu_preparation_manifest_sha256']
    assert files(GPU) == json.loads((GPU / 'sha256.json').read_text()) | {'sha256.json': sha(GPU / 'sha256.json')}
    staged = X / 'build/module-root/lib/modules' / RELEASE
    modules = json.loads((X / 'build/module-sha256.json').read_text())
    assert len(modules) == 208 and files(staged) == modules
    binaries = sorted(staged.rglob('*.ko'))
    assert len(binaries) == 193
    for path in binaries:
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).split()[0] == RELEASE
    cmdline = parent['cmdline'].replace('spx_attempt=20261003at', 'spx_attempt=20261003au')
    assert set(cmdline.split()) - set(parent['cmdline'].split()) == {'spx_attempt=20261003au'}
    entry = (PARENT / 'entry.cfg').read_text().replace('20261003at', '20261003au')
    entry = entry.replace('AT rear privacy ramoops persistence', 'AU sustained GPU')
    assert entry.count('--id spx-trial-20261003au') == 1 and (' ' + cmdline + '; then') in entry
    if resume:
        assert (X / 'entry.cfg.preview').read_text() == entry
    else:
        write(X / 'entry.cfg.preview', entry)
    subprocess.run(['grub-script-check', str(X / 'entry.cfg.preview')], check=True, timeout=30)
    helpers = {name: RUNTIME / name for name in HELPERS}
    helpers['au-reboot-check.py'] = X / 'reboot-check.py'
    for name, target in helpers.items():
        if resume:
            assert sha(target) == sha(SRC / name), name
        else:
            assert not target.exists()
        ast.parse((SRC / name).read_text())
    gpu_runtime = RUNTIME / 'gpu-workload-20261003'
    assert gpu_runtime.is_dir() if resume else not gpu_runtime.exists()
    actions = {'camera-provider': 'au-camera-provider.py', 'camera-control': 'au-camera-control.py',
               'baseline': 'au-baseline.py', 'gpu': 'au-gpu.py',
               'finalize': 'au-finalize.py', 'fallback': 'au-return.py'}
    units = {}
    for action, delay in TIMERS.items():
        timeout = 2400 if action == 'gpu' else 180
        units[f'spx-au-{action}.service'] = (
            f'[Unit]\nDescription=AU sustained GPU trial {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261003au\nAfter=local-fs.target\n'
            'RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot /var/tmp\n\n'
            f'[Service]\nType=oneshot\nExecStart={RUNTIME / actions[action]}\n'
            f'TimeoutStartSec={timeout}\nKillMode=control-group\n')
        units[f'spx-au-{action}.timer'] = (
            f'[Unit]\nDescription=AU {action} timer\nConditionKernelCommandLine=spx_attempt=20261003au\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-au-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
    for name in units:
        assert not (Path('/etc/systemd/system') / name).exists()
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/120-au-exclude.conf')
    assert not exclude.exists()
    payloads = {'vmlinuz': X / 'build/vmlinuz', 'initramfs.img': X / 'build/initramfs.img',
                'spx.dtb': X / 'build/dtb-build/spx.dtb'}
    capacity = os.statvfs('/boot')
    assert capacity.f_bavail * capacity.f_frsize > sum(p.stat().st_size for p in payloads.values()) + 1048576
    if not resume:
        prior = X / 'preinstall-state'
        prior.mkdir(mode=0o700)
        for name, path in [('active-attempt.json', BASE / 'attempt.json'),
                           ('custom.cfg', Path('/boot/grub/custom.cfg')), ('grub.cfg', Path('/boot/grub/grub.cfg'))]:
            shutil.copy2(path, prior / name)
        # Freeze the 24 original AT helpers independently; do not edit them.
        original = json.loads((PARENT / 'deployment-sources-sha256.json').read_text())
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
        write(Path('/boot/grub/custom.cfg.au-new'), entry, 0o644)
        os.replace('/boot/grub/custom.cfg.au-new', '/boot/grub/custom.cfg')
        assert Path('/boot/grub/grub.cfg').read_bytes() == (prior / 'grub.cfg').read_bytes()
        for name, target in helpers.items():
            shutil.copy2(SRC / name, target)
            target.chmod(0o755)
        gpu_runtime.mkdir(mode=0o755)
        for name in ('collect.py', 'plan.json'):
            shutil.copy2(SRC / 'gpu-workload-20261003' / name, gpu_runtime / name)
            (gpu_runtime / name).chmod(0o755 if name.endswith('.py') else 0o644)
    else:
        assert (X / 'deploy-started').read_text().strip() == bid
        assert files(Path('/usr/lib/modules') / RELEASE) == modules
        assert links(Path('/usr/lib/modules') / RELEASE) == links(staged)
        assert (X / 'entry.cfg').read_text() == entry
        assert Path('/boot/grub/custom.cfg').read_text() == entry
        assert Path('/boot/grub/grub.cfg').read_bytes() == (X / 'preinstall-state/grub.cfg').read_bytes()
        for name, path in payloads.items():
            assert sha(BOOT / name) == sha(path)
        for name in ('collect.py', 'plan.json'):
            assert sha(gpu_runtime / name) == sha(SRC / 'gpu-workload-20261003' / name)
        original = json.loads((X / 'preinstall-state/original-at-helpers-sha256.json').read_text())
        assert len(original) == 24
        for name, digest in original.items():
            assert sha(SRC / name) == digest
    gpu_runtime.chmod(0o755)
    FIXTURE.parent.mkdir(mode=0o755, exist_ok=True)
    if resume:
        assert FIXTURE.parent.stat().st_mode & 0o777 == 0o700
    assert FIXTURE.parent.stat().st_uid == 0
    FIXTURE.parent.chmod(0o755)
    assert FIXTURE.parent.stat().st_uid == 0 and FIXTURE.parent.stat().st_mode & 0o005 == 0o005
    shutil.copytree(GPU / 'fixture', FIXTURE)
    for path in [FIXTURE] + list(FIXTURE.rglob('*')):
        assert not path.is_symlink()
        path.chmod(0o755 if path.is_dir() or path.parent.name == 'bin' else 0o644)
        assert path.stat().st_uid == 0
    for name, text in units.items():
        write(Path('/etc/systemd/system') / name, text, 0o644)
    write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20261003au\n', 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    subprocess.run(['systemctl', 'enable'] + ['spx-au-' + n + '.timer' for n in TIMERS], check=True, timeout=30)
    runtime = list(helpers.values()) + [exclude, RUNTIME / 'return.sh', RUNTIME / 'collect.sh']
    runtime += [Path('/etc/systemd/system') / n for n in units]
    runtime += [gpu_runtime / name for name in ('collect.py', 'plan.json')]
    r = json.loads((X / 'working-recovery.json').read_text())
    a = {'attempt': '20261003au', 'entry': 'spx-trial-20261003au', 'release': RELEASE,
         'preboot_id': bid, 'preboot_release': os.uname().release,
         'preboot_cmdline': Path('/proc/cmdline').read_text().strip(), 'preboot_taint': '4096',
         'cmdline': cmdline, 'state': 'prepared AU; no boot selection', 'parent_attempt': '20261003at',
         'sha256': {str(BOOT / n): sha(BOOT / n) for n in payloads},
         'recovery_sha256': r['payload_sha256'], 'recovery_definition_sha256': sha(X / 'working-recovery.json'),
         'runtime_sha256': {str(p): sha(p) for p in runtime},
         'build_manifest_sha256': sha(X / 'build-sha256.json'), 'archive_review_sha256': sha(X / 'archive-review.json'),
         'build_files_verified': len(json.loads((X / 'build-sha256.json').read_text())),
         'build_links_verified': len(json.loads((X / 'build-symlinks.json').read_text())),
         'gpu_fixture_manifest_sha256': sha(FIXTURE / 'sha256.json'),
         'parent_result_manifest_sha256': sha(PARENT / 'final-result/sha256.json'),
         'parent_post_result_manifest_sha256': sha(PARENT / 'post-result-records/sha256.json'),
         'authorization': parent['authorization'], 'return_window_seconds': 600,
         'fallback_seconds': 3300, 'planned_gpu_render_seconds': 1800, 'planned_gpu_idle_seconds': 180,
         'source_commit': (X / 'build/source-commit.txt').read_text().strip(),
         'source_diff': str(X / 'build/source.diff'), 'build_archive': str(X / 'build'),
         'compiled_live_source_paths_verified': source_count,
         'playback_requested': False, 'camera_consumers_enabled': True,
         'early_recovery_validated': False, 'hardware_acceptance_closed': False,
         'comparison': 'Full current AU image/modules with rear stream/privacy ordering fixes and unchanged AT rear/LED DTB; strict baseline620, sustained GL/GLES660, GPU review2800, unconditional recovery3300.'}
    write(X / 'attempt.json', json.dumps(a, indent=2) + '\n')
    write(BASE / 'attempt-au.new.json', json.dumps(a, indent=2) + '\n')
    os.replace(BASE / 'attempt-au.new.json', BASE / 'attempt.json')
    preboot(a)
    os.sync()
    print('AU installed and fully guarded; persistent known-good default, no boot selected')


if __name__ == '__main__':
    main()
