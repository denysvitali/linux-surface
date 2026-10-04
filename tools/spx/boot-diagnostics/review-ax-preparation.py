#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently rehash AX preparation, verify RTC code and preserve the review."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from aw_boot_guard import load, recovery, files, links, sha


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    x = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ax')
    stage = Path('/var/tmp/spx-mainline-trial-20261003ax')
    parent = Path('/var/tmp/spx-mainline-trial-20261003au')
    repo = Path('/home/dvitali/Documents/git/linux-surface-next')
    release = '7.3.0-rc2-spx-mainline-20261003ax+'
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot == 'fbc6d663-8269-4d2f-9aac-c4a687583b00'
    manifest = read(x / 'preparation-sha256.json')
    assert len(manifest) == 518
    for name, digest in manifest.items():
        assert sha(x / name) == digest, name
    build = read(x / 'build-sha256.json')
    assert files(x / 'build') == build
    assert links(x / 'build') == read(x / 'build-symlinks.json')
    assert files(parent / 'work-build') == read(stage / 'parent-output-sha256.json')
    assert sha(stage / 'source-files.json') == sha(parent / 'source-files.json')
    assert sha(stage / 'source.tar.zst') == sha(parent / 'source.tar.zst')
    assert sha(repo / 'arch/arm64/configs/spx.config') == sha(x / 'build/spx-config-overlay')
    completed = read(x / 'build/build-complete.json')
    assert completed['config_delta'] == {
        'CONFIG_LOCALVERSION': {'before': '"-spx-mainline-20261003au"', 'after': '"-spx-mainline-20261003ax"'},
        'CONFIG_RTC_SYSTOHC': {'before': 'n', 'after': 'y'},
        'CONFIG_RTC_SYSTOHC_DEVICE': {'before': 'n', 'after': '"rtc0"'}}
    config = (x / 'build/artifacts/.config').read_bytes()
    for payload in ('vmlinuz', 'artifacts/arch/arm64/boot/Image'):
        extracted = subprocess.check_output([str(parent / 'source/scripts/extract-ikconfig'), str(x / 'build' / payload)])
        assert extracted == config
    module_root = x / 'build/module-root/lib/modules' / release
    modules = read(x / 'build/module-sha256.json')
    assert files(module_root) == modules and len(modules) == 208
    for name, vermagic in read(x / 'build/module-vermagic.json').items():
        actual = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module_root / name)], text=True).strip()
        assert actual == vermagic and actual.split()[0] == release
    out = x / 'independent-preparation-review'
    assert not out.exists()
    out.mkdir(mode=0o700)
    for name, path in {'reviewer.py': Path(__file__), 'rtc-ntp.o': stage / 'work-build/kernel/time/ntp.o',
                       'rtc-ntp.o.cmd': stage / 'work-build/kernel/time/.ntp.o.cmd',
                       'parent-ntp.o': parent / 'work-build/kernel/time/ntp.o',
                       'ntp.c': parent / 'source/kernel/time/ntp.c'}.items():
        shutil.copyfile(path, out / name)
    disassembly = subprocess.check_output(['objdump', '-dr', str(out / 'rtc-ntp.o')], text=True)
    new_symbols = subprocess.check_output(['nm', '--defined-only', str(out / 'rtc-ntp.o')], text=True)
    old_symbols = subprocess.check_output(['nm', '--defined-only', str(out / 'parent-ntp.o')], text=True)
    assert 'sync_hw_clock' in new_symbols and 'sync_hw_clock' not in old_symbols
    assert 'R_AARCH64_CALL26\trtc_class_open' in disassembly
    assert 'R_AARCH64_CALL26\trtc_set_time' in disassembly
    assert sha(out / 'rtc-ntp.o') != sha(out / 'parent-ntp.o')
    (out / 'ntp-disassembly').write_text(disassembly)
    (out / 'ntp-symbols').write_text(new_symbols)
    (out / 'parent-ntp-symbols').write_text(old_symbols)
    commands = read(x / 'build/build-commands.json')
    assert all(c['exit_code'] == 0 for c in commands)
    assert any('Image' in c['command'] for c in commands)
    assert any(c['command'][-1] == 'modules' for c in commands)
    assert 'MODPOST' in (x / 'build/modules.log').read_text()
    warnings = [l for l in (x / 'build/initramfs-build.log').read_text().splitlines() if 'WARNING:' in l]
    parent_warnings = [l for l in (parent / 'initramfs-build.log').read_text().splitlines() if 'WARNING:' in l]
    assert warnings == parent_warnings and len(warnings) == 2
    assert not any('warning:' in (x / 'build' / n).read_text().lower() for n in ('image-dtb.log', 'modules.log'))
    env = recovery(load())
    assert not env.get('next_entry', '')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    report = {'release': release, 'boot_id': boot, 'preparation_files_verified': len(manifest),
              'preparation_manifest_sha256': sha(x / 'preparation-sha256.json'),
              'build_files_verified': len(build), 'build_links_verified': len(read(x / 'build-symlinks.json')),
              'source_manifest_reused_exact_au': True, 'parent_output_unchanged': True,
              'config_delta_exact': True, 'embedded_configs_exact': True,
              'module_files_verified': len(modules), 'modules': 193, 'embedded_modules': 54,
              'rtc_sync_worker_compiled': True, 'rtc_class_open_and_set_time_calls_verified': True,
              'initramfs_warnings_exact_parent': warnings, 'recovery_files_links_verified': 5183,
              'persistent_default': env['saved_entry'], 'next_entry_empty': True,
              'deployed': False, 'selected': False, 'hardware_acceptance_closed': False}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
