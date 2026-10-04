#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Tie BB's one-use trial to its sealed payloads and verified known-good recovery."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261004bb'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bb+'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
RUNTIME = Path('/usr/local/lib/spx-boot-diagnostics')
CODE_DIRS = {'arch', 'block', 'certs', 'crypto', 'drivers', 'fs', 'include', 'init',
             'io_uring', 'ipc', 'kernel', 'lib', 'mm', 'net', 'rust', 'samples',
             'scripts', 'security', 'sound', 'usr', 'virt'}
CODE_TOP = {'Makefile', 'Kbuild', 'Kconfig'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def files(root):
    return {str(path.relative_to(root)): sha(path) for path in sorted(root.rglob('*'))
            if path.is_file() and not path.is_symlink()}


def links(root):
    return {str(path.relative_to(root)): os.readlink(path) for path in sorted(root.rglob('*'))
            if path.is_symlink()}


def command(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def load():
    assert os.geteuid() == 0
    a = json.loads((X / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20261004bb' and a['release'] == RELEASE
    assert a['entry'] == 'spx-trial-20261004bb'
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
            actual[name] = dict(symlink=os.readlink(path))
        elif path.is_file():
            actual[name] = dict(sha256=sha(path), bytes=path.stat().st_size)
    assert actual == r['module_files_links'] and len(actual) == 5183
    cfg = Path('/boot/grub/grub.cfg').read_text()
    match = re.search(r'^menuentry [^\n]*--id spx-known-good \{\n(?:[^\n]*\n)*?^\}\n', cfg, re.M)
    assert match and match.group() == r['entry']
    assert 'set default="spx-known-good"' in cfg
    for path, digest in r['efi_sha256'].items():
        assert sha(path) == digest, path
    env = dict(line.split('=', 1) for line in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines())
    assert env.get('saved_entry') == 'spx-known-good'
    assert 'BootNext:' not in command('efibootmgr')
    return env


def artifacts(a):
    for path, digest in (a['sha256'] | a['runtime_sha256']).items():
        assert sha(path) == digest, path
    assert sha(X / 'build-sha256.json') == a['build_manifest_sha256']
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert links(X / 'build') == json.loads((X / 'build-symlinks.json').read_text())
    assert sha(X / 'archive-review.json') == a['archive_review_sha256']
    review = json.loads((X / 'archive-review.json').read_text())
    assert sha(X / 'preparation-sha256.json') == review['preparation_manifest_sha256']
    assert files(X / 'preparation') == json.loads((X / 'preparation-sha256.json').read_text())
    assert review['source_archive_stream_verified'] and review['source_files_verified'] == 96938
    assert review['full_kernel_and_modules_linked'] and review['module_count'] == 202
    assert review['embedded_config_exact'] and review['private_initramfs_verified']
    assert review['boot_dtb_exact_parent_ba'] and review['pas_diagnostic_native_checks'] == 91 and review['pas_diagnostic_negative_controls'] == 5
    assert review['videocc_provider_module_verified'] and review['actual_of_fallback_alias_resolves']
    alias = json.loads((X / 'build/videocc-alias-resolution.json').read_text())
    assert alias['modules'] == ['videocc_sm8150'] and alias['hardware_probe_performed'] is False
    modules = Path('/usr/lib/modules') / RELEASE
    assert files(modules) == json.loads((X / 'build/module-sha256.json').read_text())
    assert len(files(modules)) == 217
    assert links(modules) == json.loads((X / 'build/module-links.json').read_text())
    assert sha(Path('/boot/grub/custom.cfg')) == a['custom_cfg_sha256']
    return review


def source():
    rows = json.loads((X / 'build/source-files.json').read_text())
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
    assert checked > 80000
    assert sha(REPO / '.config') == sha(X / 'build/live-config-before')
    return checked


def preboot(a, pending=''):
    current = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   release=os.uname().release, cmdline=Path('/proc/cmdline').read_text().strip(),
                   taint=Path('/proc/sys/kernel/tainted').read_text().strip())
    assert current['boot_id'] == a['preboot_id'] == 'a824008e-cf43-4287-84f8-4e930fa41a06'
    assert current['release'] == a['preboot_release'] == '6.18.3-1-surface+'
    assert current['cmdline'] == a['preboot_cmdline'] and 'spx_boot=known-good' in current['cmdline'].split()
    assert current['taint'] == a['preboot_taint'] == '4096'
    # Record the actual legacy recovery-kernel touch state. The fresh
    # mainline trial still requires clean touch startup in its strict baseline.
    current['known_good_touch_state'] = {
        name: (Path('/sys/bus/spi/devices/spi0.0') / name).read_text().strip()
        for name in ('ready', 'bus_error_count', 'logic_error_count',
                     'regulator_error_count', 'device_initiated_reset_count')}
    current['known_good_touch_ready'] = current['known_good_touch_state']['ready'] == 'ready'
    assert 'wlan0:wifi:connected:' in command('nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status')
    env = recovery(a)
    assert env.get('next_entry', '') == pending
    artifacts(a)
    current['compiled_source_paths_verified'] = source()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == current['boot_id']
    assert dict(line.split('=', 1) for line in command('grub-editenv', '/boot/grub/grubenv', 'list').splitlines()).get('next_entry', '') == pending
    return current


def trial_identity(a):
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot != a['preboot_id'] and os.uname().release == RELEASE
    assert Path('/proc/cmdline').read_text().split() == [
        'BOOT_IMAGE=/spx-trial-20261004bb/vmlinuz'] + a['cmdline'].split()
    return boot
