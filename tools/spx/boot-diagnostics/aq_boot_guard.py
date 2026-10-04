#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind AQ's isolated full build and one-shot boot to verified known-good recovery."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261003aq'
RELEASE = '7.3.0-rc2-spx-mainline-20261003aq+'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
CODE_DIRS = {'arch', 'block', 'certs', 'crypto', 'drivers', 'fs', 'include', 'init',
             'io_uring', 'ipc', 'kernel', 'lib', 'mm', 'net', 'rust', 'samples',
             'scripts', 'security', 'sound', 'usr', 'virt'}
CODE_TOP = {'Makefile', 'Kbuild', 'Kconfig'}
DT_INPUTS = {
    'tools/spx/boot-diagnostics/camera-power-20261003/spx-camera-regulators-disabled.dtsi',
    'Documentation/devicetree/bindings/regulator/qcom,spmi-regulator.yaml',
    'Documentation/devicetree/bindings/i2c/qcom,i2c-cci.yaml',
}


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
    return subprocess.check_output(args, text=True, timeout=90).strip()


def entry(text):
    match = re.search(r'^menuentry [^\n]*--id spx-known-good \{\n(?:[^\n]*\n)*?^\}\n', text, re.M)
    assert match
    return match.group()


def load():
    assert os.geteuid() == 0
    a = json.loads((X / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20261003aq' and a['release'] == RELEASE
    assert a['entry'] == 'spx-trial-20261003aq'
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
    assert entry(cfg) == r['entry'] and 'set default="spx-known-good"' in cfg
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
    assert files(X / 'dtb-build') == json.loads((X / 'dtb-sha256.json').read_text())
    assert files(Path('/usr/lib/modules') / RELEASE) == json.loads((X / 'build/module-sha256.json').read_text())
    assert Path('/boot/grub/custom.cfg').read_text() == (X / 'entry.cfg').read_text()
    review = json.loads((X / 'independent-build-review.json').read_text())
    assert sha(X / 'independent-build-review.json') == a['independent_build_review_sha256']
    assert review['full_source_archive_stream_verified'] and review['all_existing_dtb_properties_exact']


def source():
    """Check all compiled kernel paths against the frozen isolated build inputs.

    Full source, including documentation and helpers, is preserved in the verified
    source archive. Session prose/helper updates do not change that frozen build.
    The explicit input set below also checks the live kernel tree and trial DT inputs.
    """
    records = json.loads((X / 'build/source-files.json').read_text())
    checked = 0
    for name, record in records.items():
        parts = Path(name).parts
        if not (parts[0] in CODE_DIRS or name in CODE_TOP or name.startswith('localversion') or name in DT_INPUTS or
                (parts[0] == 'tools' and not name.startswith('tools/spx/boot-diagnostics/'))):
            continue
        path = REPO / name
        if 'sha256' in record:
            assert sha(path) == record['sha256'], name
        elif 'symlink' in record:
            assert path.is_symlink() and os.readlink(path) == record['symlink'], name
        else:
            assert not path.exists(), name
        checked += 1
    assert checked > 80000
    assert sha(REPO / '.config') == sha(X / 'build/config-before')
    return checked


def check_state(a, current, env, pending):
    """Pure immediate-boot policy, also exercised with negative identity cases."""
    assert current['boot_id'] == a['preboot_id']
    assert current['release'] == a['preboot_release']
    assert current['cmdline'] == a['preboot_cmdline']
    assert current['uptime'] >= 620 and current['taint'] == '0'
    assert current['touch'] == 'ready' and current['wifi_connected']
    assert env.get('saved_entry') == 'spx-known-good'
    assert env.get('next_entry', '') == pending


def preboot(a, pending=''):
    current = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'release': os.uname().release, 'cmdline': Path('/proc/cmdline').read_text().strip(),
               'uptime': float(Path('/proc/uptime').read_text().split()[0]),
               'taint': Path('/proc/sys/kernel/tainted').read_text().strip(),
               'touch': Path('/sys/bus/spi/devices/spi0.0/ready').read_text().strip(),
               'wifi_connected': 'wlan0:wifi:connected:' in command(
                   'nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status')}
    env = recovery(a)
    check_state(a, current, env, pending)
    artifacts(a)
    source()
    parent = BASE / 'attempts/20261002ap'
    assert sha(parent / 'independent-result-review.json') == a['parent_result_review_sha256']
    result = json.loads((parent / 'independent-result-review.json').read_text())
    assert result['boot_id'] == a['preboot_id'] and result['scoped_passed'] and result['fallback_stopped']
    assert command('systemctl', 'show', 'spx-ap-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
    for name in ('finalize', 'fallback', 'camera-provider'):
        timer = 'spx-aq-' + name + '.timer'
        assert command('systemctl', 'is-enabled', timer) == 'enabled'
        assert command('systemctl', 'show', timer, '-p', 'ActiveState', '--value') != 'active'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
    latest = dict(line.split('=', 1) for line in
                  command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert latest.get('saved_entry') == 'spx-known-good' and latest.get('next_entry', '') == pending
    return latest


def frozen_prequeue(a):
    root = X / 'prequeue-records'
    h = json.loads((root / 'sha256.json').read_text())
    assert files(root) == h | {'sha256.json': sha(root / 'sha256.json')}
    required = {'attempt.json', 'installed-review.json', 'service-context-review.json',
                'native-continuation-review.json', 'working-recovery.json', 'entry.cfg',
                'PORT-CHECKLIST.md', 'LOCAL-PROGRESS.md', 'freeze-complete.json'}
    assert required <= set(h)
    original = json.loads((root / 'attempt.json').read_text())
    assert original['state'] == 'prepared AQ; no boot selection'
    for key in ('attempt', 'entry', 'release', 'preboot_id', 'preboot_release', 'preboot_cmdline',
                'cmdline', 'sha256', 'recovery_sha256', 'runtime_sha256', 'build_manifest_sha256'):
        assert a[key] == original[key], key
    for name in ('installed-review.json', 'service-context-review.json',
                 'native-continuation-review.json', 'working-recovery.json', 'entry.cfg'):
        assert sha(X / name) == h[name], name
    service = json.loads((root / 'service-context-review.json').read_text())
    assert service['full_preboot_passed'] and service['sudo_uid_absent']
    assert service['boot_id'] == a['preboot_id']
    assert service['guard_sha256'] == sha('/usr/local/lib/spx-boot-diagnostics/aq_boot_guard.py')
    done = json.loads((root / 'freeze-complete.json').read_text())
    assert done['inputs_validated_before_creation'] and done['preboot_checked_after_copy']
    assert done['boot_id'] == a['preboot_id']
