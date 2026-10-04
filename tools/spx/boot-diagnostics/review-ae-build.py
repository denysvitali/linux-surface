#!/usr/bin/python3
"""Independently verify the AE build and isolated change against AD's snapshot."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ae')
OLD = RUN.parent / '20260930ad/post-result-records'
OUT = RUN / 'independent-build-review.json'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}

def chunks(blob):
    return {part.split(b'\n', 1)[0]: part for part in re.split(b'(?=^diff --git )', blob, flags=re.M)
            if part.startswith(b'diff --git ')}

assert os.geteuid() == 0 and not OUT.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == '86c3ff68-09a9-480c-9288-be9443254378'
assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()
archive = json.loads((RUN / 'archive-review.json').read_text())
build = RUN / 'build'
hashes = json.loads((RUN / 'build-sha256.json').read_text())
assert files(build) == hashes and sha(RUN / 'build-sha256.json') == archive['build_manifest_sha256']
links = {str(p.relative_to(build)): os.readlink(p) for p in build.rglob('*') if p.is_symlink()}
assert links == json.loads((RUN / 'build-symlinks.json').read_text())
old = (OLD / 'spi-hid-core.c').read_text()
new = (REPO / 'drivers/hid/spi-hid/spi-hid-core.c').read_text()
assert new == old.replace('#define SPI_HID_DIAG_WINDOWS\t4', '#define SPI_HID_DIAG_WINDOWS\t8')
assert old.count('#define SPI_HID_DIAG_WINDOWS\t4') == 1
assert (REPO / 'drivers/hid/spi-hid/spi-hid-core.h').read_bytes() == (OLD / 'spi-hid-core.h').read_bytes()
current = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO)
assert current == (build / 'source.diff').read_bytes()
core = b'diff --git a/drivers/hid/spi-hid/spi-hid-core.c b/drivers/hid/spi-hid/spi-hid-core.c'
before_chunks = chunks((OLD / 'source-before.diff').read_bytes())
after_chunks = chunks(current)
assert {k: v for k, v in before_chunks.items() if k != core} == {k: v for k, v in after_chunks.items() if k != core}
before = set((OLD / 'config-before').read_text().splitlines())
after = set((REPO / '.config').read_text().splitlines())
assert before - after == {'CONFIG_LOCALVERSION="-spx-mainline-20260930aa"'}
assert after - before == {'CONFIG_LOCALVERSION="-spx-mainline-20260930ae"'}
assert (build / 'config-extracted').read_bytes() == (REPO / '.config').read_bytes() == (build / 'artifacts/.config').read_bytes()
assert sha(build / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb') == '97983ecc8fc9a940787e6550071b03d1d8b63ccee00e75f2d10f452f82d7a187'
modules = json.loads((build / 'module-sha256.json').read_text())
root = build / 'module-root/lib/modules/7.3.0-rc2-spx-mainline-20260930ae+'
assert files(root) == modules and len(modules) == 202
assert len(list(root.rglob('*.ko'))) == 187
vermagic = json.loads((build / 'module-vermagic.json').read_text())
assert len(vermagic) == 187 and all(v.split()[0] == '7.3.0-rc2-spx-mainline-20260930ae+' for v in vermagic.values())
for name, digest in archive['boot_payload_sha256'].items():
    assert sha(build / name) == digest, name
assert sha(build / 'initramfs-extracted/usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == sha(build / 'logging/initrd-log.sh')
for n, d in json.loads((RUN / 'dtb-sha256.json').read_text()).items():
    assert sha(RUN / 'dtb-build' / n) == d, n
report = {'attempt': '20260930ae', 'preboot_id': archive['preboot_id'],
          'build_files_verified': len(hashes), 'build_symlinks_verified': len(links),
          'module_tree_files_verified': len(modules), 'module_vermagic_records_verified': len(vermagic),
          'driver_delta': 'SPI_HID_DIAG_WINDOWS4->8 only', 'config_delta': 'LOCALVERSION only',
          'other_source_diff_chunks_unchanged': True, 'dtb_exact_ab': True,
          'embedded_config_exact': True, 'private_initramfs_logger_exact': True,
          'functional_driver_policy_unchanged': True, 'diagnostic_record_ceiling': 384,
          'build_manifest_sha256': sha(RUN / 'build-sha256.json'),
          'driver_sha256': sha(REPO / 'drivers/hid/spi-hid/spi-hid-core.c'),
          'boot_payload_sha256': archive['boot_payload_sha256'],
          'boot_selected': False, 'deployed': False, 'playback_requested': False}
OUT.write_text(json.dumps(report, indent=2) + '\n')
os.sync()
print(json.dumps(report, indent=2))
