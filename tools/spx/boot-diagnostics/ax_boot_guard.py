#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind AX's full candidate and one-use reboot to verified known-good recovery."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261003ax'
RELEASE = '7.3.0-rc2-spx-mainline-20261003ax+'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
RUNTIME = Path('/usr/local/lib/spx-boot-diagnostics')
CODE_DIRS = {'arch', 'block', 'certs', 'crypto', 'drivers', 'fs', 'include', 'init',
             'io_uring', 'ipc', 'kernel', 'lib', 'mm', 'net', 'rust', 'samples',
             'scripts', 'security', 'sound', 'usr', 'virt'}
CODE_TOP = {'Makefile', 'Kbuild', 'Kconfig'}
TIMERS = {'rtc': 30, 'camera-provider': 60, 'camera-control': 120, 'baseline': 620,
          'gpu': 660, 'finalize': 2800, 'fallback': 3300}
FIXTURE = Path('/usr/local/lib/spx-gpu-workload/20261003au')
RESULT = Path('/var/tmp/spx-gpu-result-20261003ax')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def links(root):
    return {str(p.relative_to(root)): os.readlink(p) for p in sorted(root.rglob('*'))
            if p.is_symlink()}


def command(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def load():
    assert os.geteuid() == 0
    a = json.loads((X / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20261003ax' and a['release'] == RELEASE
    assert a['entry'] == 'spx-trial-20261003ax'
    return a


def recovery(a):
    assert sha(X / 'working-recovery.json') == a['recovery_definition_sha256']
    r = json.loads((X / 'working-recovery.json').read_text())
    assert r['payload_sha256'] == a['recovery_sha256']
    for path, digest in r['payload_sha256'].items():
        assert sha(path) == digest, path
    root = Path('/usr/lib/modules/6.18.3-1-surface+')
    actual = {}
    for path in root.rglob('*'):
        name = str(path.relative_to(root))
        if path.is_symlink():
            actual[name] = {'symlink': os.readlink(path)}
        elif path.is_file():
            actual[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    assert actual == r['module_files_links'] and len(actual) == 5183
    cfg = Path('/boot/grub/grub.cfg').read_text()
    match = re.search(r'^menuentry [^\n]*--id spx-known-good \{\n(?:[^\n]*\n)*?^\}\n', cfg, re.M)
    assert match and match.group() == r['entry']
    assert 'set default="spx-known-good"' in cfg
    for path, digest in r['efi_sha256'].items():
        assert sha(path) == digest, path
    env = dict(line.split('=', 1) for line in
               command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert env.get('saved_entry') == 'spx-known-good'
    assert 'BootNext:' not in command('efibootmgr')
    return env


def artifacts(a):
    for path, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
        assert sha(path) == digest, path
    assert sha(X / 'build-sha256.json') == a['build_manifest_sha256']
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert links(X / 'build') == json.loads((X / 'build-symlinks.json').read_text())
    assert sha(X / 'archive-review.json') == a['archive_review_sha256']
    review = json.loads((X / 'archive-review.json').read_text())
    assert review['source_archive_stream_verified'] and review['source_files_links_verified'] == 96937
    assert review['config_delta_exact'] and review['both_payload_configs_exact']
    assert review['current_exports_full_build'] and review['module_count'] == 193
    assert review['embedded_modules'] == 54
    assert review['at_dtb_sha256'] == '50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c'
    assert a['rtc_config_candidate'] and not a['kernel_reused_exact_au']
    assert review['source_code_reused_exact_au'] and review['private_parent_output_clone']
    preparation = json.loads((X / 'preparation-sha256.json').read_text())
    assert len(preparation) == 518 and sha(X / 'preparation-sha256.json') == a['preparation_manifest_sha256']
    for name, digest in preparation.items():
        assert sha(X / name) == digest, name
    independent = X / 'independent-preparation-review'
    expected = json.loads((independent / 'sha256.json').read_text())
    assert files(independent) == expected | {'sha256.json': sha(independent / 'sha256.json')}
    independent_review = json.loads((independent / 'result.json').read_text())
    assert independent_review['rtc_sync_worker_compiled'] and independent_review['config_delta_exact']
    assert independent_review['parent_output_unchanged'] and independent_review['embedded_configs_exact']
    rtc = X / 'rtc-observer-preparation'
    expected = json.loads((rtc / 'sha256.json').read_text())
    assert files(rtc) == expected | {'sha256.json': sha(rtc / 'sha256.json')}
    assert sha(rtc / 'sha256.json') == a['rtc_preparation_manifest_sha256']
    assert sha(RUNTIME / 'rtc-readonly-20261003ax') == a['rtc_probe_sha256'] == sha(rtc / 'rtc-readonly')
    assert sha(X / 'gpu-preparation/sha256.json') == a['gpu_preparation_manifest_sha256']
    prep = json.loads((X / 'gpu-preparation/sha256.json').read_text())
    assert files(X / 'gpu-preparation') == prep | {'sha256.json': sha(X / 'gpu-preparation/sha256.json')}
    modules = json.loads((X / 'build/module-sha256.json').read_text())
    assert len(modules) == 208 and files(Path('/usr/lib/modules') / RELEASE) == modules
    assert links(Path('/usr/lib/modules') / RELEASE) == links(X / 'build/module-root/lib/modules' / RELEASE)
    fixture = json.loads((FIXTURE / 'sha256.json').read_text())
    assert files(FIXTURE) == fixture | {'sha256.json': sha(FIXTURE / 'sha256.json')}
    assert sha(FIXTURE / 'sha256.json') == a['gpu_fixture_manifest_sha256']
    for path in [FIXTURE] + list(FIXTURE.rglob('*')):
        assert not path.is_symlink() and path.stat().st_uid == 0
        assert not path.stat().st_mode & 0o022
    assert Path('/boot/grub/custom.cfg').read_bytes() == (X / 'entry.cfg').read_bytes()


def source():
    records = json.loads((X / 'build/source-files.json').read_text())
    checked = 0
    for name, record in records.items():
        top = Path(name).parts[0]
        if not (top in CODE_DIRS or name in CODE_TOP or name.startswith('localversion') or
                (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/'))):
            continue
        path = REPO / name
        if name == 'arch/arm64/configs/spx.config':
            # The frozen AU code uses the explicit AX effective configuration;
            # this board-fragment overlay is separately archived, not a C delta.
            assert sha(path) == sha(X / 'build/spx-config-overlay'), name
            checked += 1
            continue
        if 'sha256' in record:
            assert sha(path) == record['sha256'], name
        elif 'symlink' in record:
            assert path.is_symlink() and os.readlink(path) == record['symlink'], name
        else:
            assert not path.exists(), name
        checked += 1
    assert checked > 80000
    assert sha(REPO / '.config') == sha(X / 'build/live-config-before')
    for name, digest in json.loads((X / 'build/dt-input-files-sha256.json').read_text()).items():
        assert sha(REPO / name) == digest, name
    return checked


def check_state(a, current, env, pending):
    assert current['boot_id'] == a['preboot_id']
    assert current['release'] == a['preboot_release'] == '6.18.3-1-surface+'
    assert current['cmdline'] == a['preboot_cmdline']
    assert 'spx_boot=known-good' in current['cmdline'].split()
    assert current['taint'] == a['preboot_taint'] == '4096'
    assert current['touch'] == 'ready' and current['wifi_connected']
    assert env.get('saved_entry') == 'spx-known-good'
    assert env.get('next_entry', '') == pending


def preboot(a, pending=''):
    current = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'release': os.uname().release, 'cmdline': Path('/proc/cmdline').read_text().strip(),
               'taint': Path('/proc/sys/kernel/tainted').read_text().strip(),
               'touch': Path('/sys/bus/spi/devices/spi0.0/ready').read_text().strip(),
               'wifi_connected': 'wlan0:wifi:connected:' in command(
                   'nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status')}
    env = recovery(a)
    check_state(a, current, env, pending)
    artifacts(a)
    source()
    assert not RESULT.exists()
    assert not (X / 'rtc-result').exists() and not (X / 'rtc-result.partial').exists()
    for name in TIMERS:
        timer = 'spx-ax-' + name + '.timer'
        assert command('systemctl', 'is-enabled', timer) == 'enabled'
        assert command('systemctl', 'show', timer, '-p', 'ActiveState', '--value') != 'active'
    for timer in ('spx-diag-long-return.timer', 'spx-diag-return.timer', 'spx-at-fallback.timer',
                  'spx-au-fallback.timer', 'spx-trial-20261003au-reboot.timer',
                  'spx-av-fallback.timer', 'spx-av-early-return.timer', 'spx-trial-20261003av-reboot.timer',
                  'spx-aw-fallback.timer', 'spx-trial-20261003aw-reboot.timer'):
        assert command('systemctl', 'show', timer, '-p', 'ActiveState', '--value') != 'active'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    latest = dict(line.split('=', 1) for line in
                  command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert latest.get('saved_entry') == 'spx-known-good' and latest.get('next_entry', '') == pending
    return latest


def trial_identity(a):
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid != a['preboot_id'] and os.uname().release == RELEASE
    assert Path('/proc/cmdline').read_text().split() == [
        'BOOT_IMAGE=/spx-trial-20261003ax/vmlinuz'] + a['cmdline'].split()
    return bid


def frozen_prequeue(a):
    root = X / 'prequeue-records'
    h = json.loads((root / 'sha256.json').read_text())
    assert files(root) == h | {'sha256.json': sha(root / 'sha256.json')}
    required = {'attempt.json', 'installed-review.json', 'service-context-review.json',
                'native-continuation-review.json', 'working-recovery.json', 'entry.cfg',
                'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md', 'freeze-complete.json'}
    assert required <= set(h)
    original = json.loads((root / 'attempt.json').read_text())
    assert original['state'] == 'prepared AX; no boot selection'
    for key, value in original.items():
        if key != 'state':
            assert a[key] == value, key
    for name in ('installed-review.json', 'service-context-review.json',
                 'native-continuation-review.json', 'working-recovery.json', 'entry.cfg'):
        assert sha(X / name) == h[name], name
    service = json.loads((root / 'service-context-review.json').read_text())
    assert service['full_preboot_passed'] and service['sudo_uid_absent']
    assert service['boot_id'] == a['preboot_id']
    assert service['guard_sha256'] == sha(RUNTIME / 'ax_boot_guard.py')
    done = json.loads((root / 'freeze-complete.json').read_text())
    assert done['inputs_validated_before_creation'] and done['preboot_checked_after_copy']
    assert done['boot_id'] == a['preboot_id']
