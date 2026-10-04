#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install reviewed AR beside preserved AM/recovery; select no boot."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
SRC = REPO / 'tools/spx/boot-diagnostics'
BASE = Path('/var/lib/spx-boot-diagnostics')
PARENT = BASE / 'attempts/20261003aq'
X = BASE / 'attempts/20261003ar'
RELEASE = '7.3.0-rc2-spx-mainline-20261003ar+'
BOOT = Path('/boot/spx-trial-20261003ar')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def write(path, text, mode=0o600):
    with path.open('x') as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    path.chmod(mode)


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not BOOT.exists()
    assert not (Path('/usr/lib/modules') / RELEASE).exists()
    assert not (X / 'deploy-started').exists()
    sys.path.insert(0, str(SRC))
    import aq_boot_guard
    parent = aq_boot_guard.load()
    env = aq_boot_guard.recovery(parent)
    assert not env.get('next_entry', '')
    aq_boot_guard.artifacts(parent)
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '991a6fbd-2217-4f93-8185-287a223a13f6'
    assert os.uname().release == '6.18.3-1-surface+'
    review = json.loads((X / 'independent-build-review.json').read_text())
    archive = json.loads((X / 'archive-review.json').read_text())
    assert review['release'] == RELEASE and review['full_source_archive_stream_verified']
    assert review['all_existing_dtb_properties_exact'] and review['reviewed_config_delta_exact'] and review['only_touch_property_delta_from_aq']
    assert sha(X / 'build-sha256.json') == review['build_manifest_sha256'] == archive['build_manifest_sha256']
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert files(X / 'dtb-build') == json.loads((X / 'dtb-sha256.json').read_text())
    assert (REPO / '.config').read_bytes() == (X / 'build/config-before').read_bytes()
    staged = X / 'build/module-root/lib/modules' / RELEASE
    modules = json.loads((X / 'build/module-sha256.json').read_text())
    assert len(modules) == 208 and files(staged) == modules
    proof = X / 'embedded-config-review'
    h = json.loads((proof / 'sha256.json').read_text())
    assert files(proof) == h | {'sha256.json': sha(proof / 'sha256.json')}
    r = json.loads((proof / 'report.json').read_text())
    assert r['both_actual_payload_configs_exact'] and r['extractor_source_record_verified']
    assert r['config_sha256'] == sha(X / 'build/artifacts/.config')
    cmdline = parent['cmdline'].replace('spx_attempt=20261003aq', 'spx_attempt=20261003ar')
    assert set(cmdline.split()) - set(parent['cmdline'].split()) == {'spx_attempt=20261003ar'}
    entry = (PARENT / 'entry.cfg').read_text().replace('20261003aq', '20261003ar')
    entry = entry.replace('AQ camera provider ', 'AR touch timing ').replace('AQ camera provider', 'AR touch timing')
    assert entry.count('--id spx-trial-20261003ar') == 1
    assert (' ' + cmdline + '; then') in entry
    preview = X / 'entry.cfg.preview'
    write(preview, entry)
    subprocess.run(['grub-script-check', str(preview)], check=True, timeout=30)
    helpers = {n: Path('/usr/local/lib/spx-boot-diagnostics') / n for n in (
        'ar-finalize.py', 'ar-return.py', 'ar_boot_guard.py', 'ar-camera-provider.py')}
    helpers['ar-reboot-check.py'] = X / 'reboot-check.py'
    for name, target in helpers.items():
        assert not target.exists()
        ast.parse((SRC / name).read_text())
    units = {}
    for action, delay in (('finalize', 620), ('fallback', 900), ('camera-provider', 60)):
        executable = {'finalize': 'ar-finalize.py', 'fallback': 'ar-return.py',
                      'camera-provider': 'ar-camera-provider.py'}[action]
        units[f'spx-ar-{action}.service'] = (
            f'[Unit]\nDescription=AR camera provider trial {action}\n'
            'ConditionKernelCommandLine=spx_attempt=20261003ar\nAfter=local-fs.target\n'
            'RequiresMountsFor=/var/lib/spx-boot-diagnostics /boot\n\n[Service]\nType=oneshot\n'
            f'ExecStart=/usr/local/lib/spx-boot-diagnostics/{executable}\nTimeoutStartSec=180\n')
        units[f'spx-ar-{action}.timer'] = (
            f'[Unit]\nDescription=AR {action} timer\nConditionKernelCommandLine=spx_attempt=20261003ar\n\n'
            f'[Timer]\nOnBootSec={delay}\nAccuracySec=1\nUnit=spx-ar-{action}.service\n\n'
            '[Install]\nWantedBy=timers.target\n')
    for name in units:
        assert not (Path('/etc/systemd/system') / name).exists()
    exclude = Path('/etc/systemd/system/spx-diag-long-return.timer.d/115-ar-exclude.conf')
    assert not exclude.exists()
    payloads = {'vmlinuz': X / 'build/vmlinuz', 'initramfs.img': X / 'build/initramfs.img',
                'spx.dtb': X / 'dtb-build/spx.dtb'}
    need = sum(p.stat().st_size for p in payloads.values()) + 1048576
    capacity = os.statvfs('/boot')
    assert capacity.f_bavail * capacity.f_frsize > need
    # Save the old live selection/menu before any reversible installation change.
    prior = X / 'preinstall-state'
    prior.mkdir(mode=0o700)
    for name, path in [('active-attempt.json', BASE / 'attempt.json'),
                       ('custom.cfg', Path('/boot/grub/custom.cfg')),
                       ('grub.cfg', Path('/boot/grub/grub.cfg'))]:
        shutil.copy2(path, prior / name)
    (prior / 'sha256.json').write_text(json.dumps(files(prior), indent=2) + '\n')
    write(X / 'deploy-started', bid + '\n')
    shutil.copytree(staged, Path('/usr/lib/modules') / RELEASE, symlinks=True)
    assert files(Path('/usr/lib/modules') / RELEASE) == modules
    BOOT.mkdir(mode=0o700)
    for name, source in payloads.items():
        shutil.copy2(source, BOOT / name)
        assert sha(BOOT / name) == sha(source)
    write(X / 'entry.cfg', entry)
    temporary = Path('/boot/grub/custom.cfg.ar-new')
    write(temporary, entry, 0o644)
    os.replace(temporary, '/boot/grub/custom.cfg')
    assert Path('/boot/grub/grub.cfg').read_bytes() == (prior / 'grub.cfg').read_bytes()
    for name, target in helpers.items():
        shutil.copy2(SRC / name, target)
        target.chmod(0o755)
    for name, text in units.items():
        write(Path('/etc/systemd/system') / name, text, 0o644)
    write(exclude, '[Unit]\nConditionKernelCommandLine=!spx_attempt=20261003ar\n', 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    timers = ['spx-ar-' + action + '.timer' for action in ('finalize', 'fallback', 'camera-provider')]
    subprocess.run(['systemctl', 'enable'] + timers, check=True, timeout=30)
    for timer in timers:
        assert subprocess.check_output(['systemctl', 'is-enabled', timer], text=True).strip() == 'enabled'
        assert subprocess.check_output(['systemctl', 'show', timer, '-p', 'ActiveState', '--value'], text=True).strip() != 'active'
    runtime_paths = list(helpers.values()) + [exclude,
        Path('/usr/local/lib/spx-boot-diagnostics/return.sh'),
        Path('/usr/local/lib/spx-boot-diagnostics/collect.sh')]
    runtime_paths += [Path('/etc/systemd/system') / name for name in units]
    recovery = json.loads((X / 'working-recovery.json').read_text())
    a = {'attempt': '20261003ar', 'entry': 'spx-trial-20261003ar', 'release': RELEASE,
         'preboot_id': bid, 'preboot_release': os.uname().release,
         'preboot_cmdline': Path('/proc/cmdline').read_text().strip(), 'cmdline': cmdline,
         'state': 'prepared AR; no boot selection', 'parent_attempt': '20261003aq',
         'parent_result_review_sha256': sha(PARENT / 'independent-result-review.json'),
         'parent_recovery_return_manifest_sha256': sha(PARENT / 'recovery-return/sha256.json'),
         'sha256': {str(BOOT / name): sha(BOOT / name) for name in payloads},
         'recovery_sha256': recovery['payload_sha256'],
         'recovery_definition_sha256': sha(X / 'working-recovery.json'),
         'runtime_sha256': {str(path): sha(path) for path in runtime_paths},
         'build_manifest_sha256': sha(X / 'build-sha256.json'),
         'independent_build_review_sha256': sha(X / 'independent-build-review.json'),
         'embedded_config_manifest_sha256': sha(X / 'embedded-config-review/sha256.json'),
         'authorization': parent['authorization'], 'return_window_seconds': 600,
         'source_commit': (X / 'build/source-commit.txt').read_text().strip(),
         'source_diff': str(X / 'build/source.diff'), 'build_archive': str(X / 'build'),
         'playback_requested': False, 'camera_consumers_enabled': False,
         'early_recovery_validated': False,
         'comparison': 'Touch rail delay only DT delta from AQ; rear/CCI framework modules compiled, camera consumers disabled; strict inherited baseline620/900.'}
    write(X / 'attempt.json', json.dumps(a, indent=2) + '\n')
    temporary = BASE / 'attempt-aq.new.json'
    write(temporary, json.dumps(a, indent=2) + '\n')
    os.replace(temporary, BASE / 'attempt.json')
    import ar_boot_guard
    ar_boot_guard.preboot(a)
    os.sync()
    print('AR installed with new modules/private payloads; known-good remains default, no boot selected')


if __name__ == '__main__':
    main()
