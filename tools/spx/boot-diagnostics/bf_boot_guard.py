#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Tie BF's one-use trial to its sealed payloads and verified known-good recovery."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261004bf'
RELEASE = '7.3.0-rc2-spx-mainline-20261004bf+'
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
    assert a['attempt'] == '20261004bf' and a['release'] == RELEASE
    assert a['entry'] == 'spx-trial-20261004bf'
    for flag in ('qcom_scm.spx_pas_diag=1', 'qcom_scm.spx_pas_area_diag=1', 'venus_core.spx_hfi_startup_diag=1'):
        assert a['cmdline'].split().count(flag) == 1
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
    assert sha(X / 'preparation-sha256.json') == a['original_preparation_manifest_sha256']
    assert files(X / 'preparation') == json.loads((X / 'preparation-sha256.json').read_text())
    for path, digest in (a['sha256'] | a['runtime_sha256']).items():
        assert sha(path) == digest, path
    assert sha(X / 'preparation-reviewed-sha256.json') == a['preparation_manifest_sha256']
    assert files(X / 'preparation-reviewed') == json.loads((X / 'preparation-reviewed-sha256.json').read_text())
    plan = X / 'preparation-reviewed/runtime-plan'
    assert sha(plan / 'sha256.json') == a['runtime_plan_manifest_sha256']
    assert files(plan) == json.loads((plan / 'sha256.json').read_text()) | {'sha256.json': sha(plan / 'sha256.json')}
    assert sha(X / 'build-sha256.json') == a['build_manifest_sha256']
    assert files(X / 'build') == json.loads((X / 'build-sha256.json').read_text())
    assert sha(X / 'build-review.json') == a['build_review_sha256']
    assert sha(X / 'assembly-sha256.json') == a['assembly_manifest_sha256']
    assert files(X / 'assembly') == json.loads((X / 'assembly-sha256.json').read_text())
    assert sha(X / 'assembly-symlinks.json') == a['assembly_symlinks_sha256']
    assert links(X / 'assembly') == json.loads((X / 'assembly-symlinks.json').read_text())
    assert sha(X / 'assembly-review.json') == a['assembly_review_sha256']
    report = json.loads((X / 'assembly-review.json').read_text())
    assert report['module_count'] == 202 and report['embedded_modules'] == 55
    assert report['all_staged_module_bytes_exact_compiled'] and report['embedded_module_payloads_exact']
    assert report['raw_and_retained_dtb_exact_be'] and report['original_build_archive_unchanged']
    built = json.loads((X / 'build-review.json').read_text())
    assert built['source_records_verified'] == 96938 and built['source_archive_stream_verified']
    assert built['three_diagnostic_source_changes_relative_be'] and built['provider_contracts_verified']
    assert built['venus_shared_gate_link_resolved'] and built['venus_parameter_default_zero_verified']
    assert sha(X / 'assembly/source.tar.zst') == built['source_archive_sha256']
    assert sha(X / 'assembly/source-files.json') == built['source_manifest_sha256']
    module_rows = json.loads((X / 'assembly/module-sha256.json').read_text())
    assert len(module_rows) == 217 and files(Path('/usr/lib/modules') / RELEASE) == module_rows
    assert links(Path('/usr/lib/modules') / RELEASE) == json.loads((X / 'assembly/module-links.json').read_text())
    assert Path('/boot/grub/custom.cfg').read_bytes() == (X / 'entry.cfg').read_bytes()
    assert sha(X / 'independent-preparation-review.json') == a['independent_preparation_review_sha256']
    independent = json.loads((X / 'independent-preparation-review.json').read_text())
    assert independent['source_archive_stream_verified'] and independent['source_paths_checked'] == 84669
    assert independent['full_bf_executable_and_initramfs_verified']
    assert independent['assembly_review_sha256'] == sha(X / 'assembly-review.json')

def source():
    rows = json.loads((X / 'assembly/source-files.json').read_text())
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
    assert checked == 84669
    assert sha(REPO / '.config') == sha(X / 'assembly/live-config-before')
    return checked


def preboot(a, pending=''):
    current = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   release=os.uname().release, cmdline=Path('/proc/cmdline').read_text().strip(),
                   taint=Path('/proc/sys/kernel/tainted').read_text().strip())
    assert current['boot_id'] == a['preboot_id'] == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
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
        'BOOT_IMAGE=/spx-trial-20261004bf/vmlinuz'] + a['cmdline'].split()
    return boot
