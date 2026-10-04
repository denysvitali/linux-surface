#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive and retire only terminal AV's unreferenced ESP payloads for fresh BA."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from az_boot_guard import X, load, recovery, artifacts, files, sha, command


def main():
    os.umask(0o077)
    a = load()
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == '19cfd105-9780-4c85-995f-625bb1eb0529'
    assert os.uname().release == '6.18.3-1-surface+'
    assert not recovery(a).get('next_entry', '')
    artifacts(a)
    old = X.parent / '20261003av'
    returned = old / 'return-result'
    assert sha(returned / 'sha256.json') == '7a6b738d3f4225214819c5af306fab28a68461ed8a4ca6f9f22a918f77bc2ae4'
    assert files(returned) == json.loads((returned / 'sha256.json').read_text()) | {
        'sha256.json': sha(returned / 'sha256.json')}
    result = json.loads((returned / 'result.json').read_text())
    assert result['authorized_early_return_after_terminal_collection_failure']
    assert result['GPU_collection_failed'] and result['return_release'] == '6.18.3-1-surface+'
    slot = Path('/boot/spx-trial-20261003av')
    aq = json.loads((old / 'attempt.json').read_text())
    names = {'vmlinuz', 'initramfs.img', 'spx.dtb'}
    assert set(p.name for p in slot.iterdir()) == names
    assert set(aq['sha256']) == {str(slot / name) for name in names}
    for name in names:
        assert not (slot / name).is_symlink() and sha(slot / name) == aq['sha256'][str(slot / name)]
    grub = {name: Path('/boot/grub', name).read_bytes() for name in ('grub.cfg', 'custom.cfg', 'grubenv')}
    efi = command('efibootmgr', '-v')
    assert '20261003av' not in efi and all(b'20261003av' not in data for data in grub.values())
    out = X / 'retired-av-boot-slot'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copytree(slot, out / 'payloads')
    assert files(slot) == files(out / 'payloads')
    for name, data in grub.items():
        (out / name).write_bytes(data)
    (out / 'efibootmgr').write_text(efi)
    shutil.copy2(old / 'attempt.json', out / 'av-attempt.json')
    shutil.copy2(returned / 'result.json', out / 'av-return-report.json')
    (out / 'payload-sha256.json').write_text(json.dumps(files(out / 'payloads'), indent=2) + '\n')
    os.sync()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert not recovery(a).get('next_entry', '')
    for name in names:
        assert sha(slot / name) == sha(out / 'payloads' / name)
    before = os.statvfs('/boot')
    freed = sum((slot / name).stat().st_size for name in names)
    for name in sorted(names):
        (slot / name).unlink()
    slot.rmdir()
    os.sync()
    after = os.statvfs('/boot')
    assert not slot.exists() and after.f_bavail > before.f_bavail
    assert all(Path('/boot/grub', name).read_bytes() == data for name, data in grub.items())
    assert command('efibootmgr', '-v') == efi
    assert not recovery(a).get('next_entry', '')
    artifacts(a)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    report = dict(boot_id=bid, retired_attempt='20261003av', payload_files=3,
                  payload_bytes=freed, archived_payloads_exact=True,
                  terminal_return_archive_verified=True, menu_efi_bytes_unchanged=True,
                  known_good_recovery_verified=True, next_entry_empty=True,
                  boot_free_bytes=after.f_bavail * after.f_frsize,
                  restore_directory=str(out / 'payloads'),
                  candidate_az_payloads_and_modules_preserved=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
    os.sync()
    print(json.dumps(report | {'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
