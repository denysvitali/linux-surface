#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install AY's sealed startup candidate and helpers; leave boot selection empty."""
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
import ax_boot_guard as old

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
SRC = REPO / 'tools/spx/boot-diagnostics'
BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261003ay'
RUNTIME = Path('/usr/local/lib/spx-boot-diagnostics')
RELEASE = '7.3.0-rc2-spx-mainline-20261003ay+'
BOOT_ID = 'b6b4f20b-376f-4577-b282-677ad4ae0ec8'
BOOT = Path('/boot/spx-trial-20261003ay')
HELPERS = ('ay_boot_guard.py', 'ay-video.py', 'ay-return.py', 'ay-baseline.py',
           'ay-camera-provider.py', 'ay-camera-control.py', 'ay_camera_core.py',
           'review-ay-baseline.py')
TIMERS = {'camera-provider': 60, 'video': 90, 'camera-control': 120,
          'baseline': 620, 'fallback': 900}


def write(path, value, mode=0o600):
    with path.open('x') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(mode)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID
    assert os.uname().release == '6.18.3-1-surface+'
    parent = old.load()
    assert not old.recovery(parent).get('next_entry', '')
    old.artifacts(parent)
    assert not (X / 'attempt.json').exists() and not BOOT.exists()
    assert not (Path('/usr/lib/modules') / RELEASE).exists() and not (X / 'deploy-started').exists()
    review = json.loads((X / 'archive-review.json').read_text())
    assert old.files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert old.links(X / 'build') == json.loads((X / 'build-symlinks.json').read_text())
    assert old.files(X / 'preparation') == json.loads((X / 'preparation-sha256.json').read_text())
    assert old.sha(X / 'build-sha256.json') == review['build_manifest_sha256']
    assert old.sha(X / 'preparation-sha256.json') == review['preparation_manifest_sha256']
    checked = json.loads((X / 'independent-preparation-review.json').read_text())
    assert checked['source_paths_checked'] == 84669 and checked['boot_id'] == BOOT_ID
    assert checked['archive_review_sha256'] == old.sha(X / 'archive-review.json')
    assert review['full_kernel_and_modules_linked'] and review['source_archive_stream_verified']
    staged = X / 'build/module-root/lib/modules' / RELEASE
    modules = json.loads((X / 'build/module-sha256.json').read_text())
    assert len(modules) == 216 and old.files(staged) == modules
    assert old.links(staged) == json.loads((X / 'build/module-links.json').read_text())
    for path in staged.rglob('*.ko'):
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).split()[0] == RELEASE
    cmdline = parent['cmdline'].replace('spx_attempt=20261003ax', 'spx_attempt=20261003ay')
    cmdline += ' venus_core.dyndbg=+p of_reserved_mem.dyndbg=+p'
    assert set(cmdline.split()) - set(parent['cmdline'].split()) == {
        'spx_attempt=20261003ay', 'venus_core.dyndbg=+p', 'of_reserved_mem.dyndbg=+p'}
    entry = (old.X / 'entry.cfg').read_text().replace('20261003ax', '20261003ay')
    entry = entry.replace('AX RTC and GPU', 'AY Iris1 startup')
    entry = entry.replace(parent['cmdline'].replace('20261003ax', '20261003ay') + '; then', cmdline + '; then')
    assert entry.count('--id spx-trial-20261003ay') == 1 and (' ' + cmdline + '; then') in entry
    prep = X / 'deployment-preparation'
    prep.mkdir(mode=0o700)
    write(prep / 'entry.cfg', entry)
    subprocess.run(['grub-script-check', str(prep / 'entry.cfg')], check=True, timeout=30)
    for name in HELPERS:
        assert not (RUNTIME / name).exists()
        ast.parse((SRC / name).read_text())
        shutil.copy2(SRC / name, prep / name)
    shutil.copy2(__file__, prep / 'deploy-ay.py')
    actions = {'camera-provider': 'ay-camera-provider.py', 'video': 'ay-video.py',
               'camera-control': 'ay-camera-control.py', 'baseline': 'ay-baseline.py',
               'fallback': 'ay-return.py'}
    units = {}
    for action, delay in TIMERS.items():
        units[f'spx-ay-{action}.service'] = (
            f'[Unit]\nDescription=AY Iris1 startup {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261003ay\nAfter=local-fs.target\n'
            'RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot /var/tmp\n\n'
            f'[Service]\nType=oneshot\nExecStart={RUNTIME / actions[action]}\n'
            'TimeoutStartSec=180\nKillMode=control-group\n')
        units[f'spx-ay-{action}.timer'] = (
            f'[Unit]\nDescription=AY {action} timer\nConditionKernelCommandLine=spx_attempt=20261003ay\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ay-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
    for name, value in units.items():
        assert not (Path('/etc/systemd/system') / name).exists()
        write(prep / name, value, 0o644)
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/121-ay-exclude.conf')
    assert not exclude.exists()
    write(prep / exclude.name, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20261003ay\n', 0o644)
    payloads = {'vmlinuz': X / 'build/vmlinuz', 'initramfs.img': X / 'build/initramfs.img',
                'spx.dtb': X / 'build/dtb-build/spx.dtb'}
    capacity = os.statvfs('/boot')
    assert capacity.f_bavail * capacity.f_frsize > sum(path.stat().st_size for path in payloads.values()) + 1048576
    for path in (BASE / 'attempt.json', Path('/boot/grub/custom.cfg'), Path('/boot/grub/grub.cfg')):
        shutil.copy2(path, prep / ('previous-' + path.name))
    write(prep / 'sha256.json', json.dumps(old.files(prep), indent=2) + '\n')
    write(X / 'deploy-started', BOOT_ID + '\n')
    shutil.copytree(staged, Path('/usr/lib/modules') / RELEASE, symlinks=True)
    assert old.files(Path('/usr/lib/modules') / RELEASE) == modules
    assert old.links(Path('/usr/lib/modules') / RELEASE) == old.links(staged)
    BOOT.mkdir(mode=0o700)
    for name, path in payloads.items():
        shutil.copy2(path, BOOT / name)
        assert old.sha(BOOT / name) == old.sha(path)
    write(X / 'entry.cfg', entry)
    write(Path('/boot/grub/custom.cfg.ay-new'), entry, 0o644)
    os.replace('/boot/grub/custom.cfg.ay-new', '/boot/grub/custom.cfg')
    assert Path('/boot/grub/grub.cfg').read_bytes() == (prep / 'previous-grub.cfg').read_bytes()
    for name in HELPERS:
        shutil.copy2(prep / name, RUNTIME / name)
        (RUNTIME / name).chmod(0o755)
    for name in units:
        shutil.copy2(prep / name, Path('/etc/systemd/system') / name)
    shutil.copy2(prep / exclude.name, exclude)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    subprocess.run(['systemctl', 'enable'] + ['spx-ay-' + name + '.timer' for name in TIMERS], check=True, timeout=30)
    runtime = [RUNTIME / name for name in HELPERS]
    runtime += [Path('/etc/systemd/system') / name for name in units]
    runtime += [exclude, RUNTIME / 'return.sh', RUNTIME / 'collect.sh']
    r = json.loads((X / 'working-recovery.json').read_text())
    a = dict(attempt='20261003ay', entry='spx-trial-20261003ay', release=RELEASE,
        utc=datetime.now(timezone.utc).isoformat(), parent_attempt='20261003ax',
        preboot_id=BOOT_ID, preboot_release=os.uname().release,
        preboot_cmdline=Path('/proc/cmdline').read_text().strip(), preboot_taint='4096',
        cmdline=cmdline, state='prepared AY; no boot selection',
        sha256={str(BOOT / name): old.sha(BOOT / name) for name in payloads},
        recovery_sha256=r['payload_sha256'], recovery_definition_sha256=old.sha(X / 'working-recovery.json'),
        runtime_sha256={str(path): old.sha(path) for path in runtime},
        build_manifest_sha256=old.sha(X / 'build-sha256.json'), archive_review_sha256=old.sha(X / 'archive-review.json'),
        build_files_verified=review['build_files'], build_links_verified=review['build_links'],
        deployment_preparation_manifest_sha256=old.sha(prep / 'sha256.json'),
        parent_return_manifest_sha256=review['parent_return_manifest_sha256'],
        custom_cfg_sha256=old.sha('/boot/grub/custom.cfg'), authorization=parent['authorization'],
        return_window_seconds=600, fallback_seconds=900, source_commit=(X / 'build/parent-source-commit.txt').read_text().strip(),
        source_diff=str(X / 'build/source.diff'), build_archive=str(X / 'build'),
        camera_consumers_enabled=True, early_recovery_validated=False,
        hardware_acceptance_closed=False, playback_requested=False)
    write(X / 'attempt.json', json.dumps(a, indent=2) + '\n')
    write(BASE / 'attempt-ay.new.json', json.dumps(a, indent=2) + '\n')
    os.replace(BASE / 'attempt-ay.new.json', BASE / 'attempt.json')
    import ay_boot_guard as guard
    state = guard.preboot(a)
    write(X / 'deployed-preboot-review.json', json.dumps(state, indent=2) + '\n')
    os.sync()
    print('AY installed and guarded; known-good remains default, no boot selected')


if __name__ == '__main__':
    main()
