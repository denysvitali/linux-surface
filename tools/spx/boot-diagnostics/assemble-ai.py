#!/usr/bin/python3
"""Stage AI modules and build its private, logged initramfs once."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
STAGE = Path('/var/tmp/spx-mainline-trial-20260930ai')
RELEASE = '7.3.0-rc2-spx-mainline-20260930ai+'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def run(args, log, cwd=REPO):
    start = time.monotonic()
    with (STAGE / log).open('wb') as stream:
        result = subprocess.run(args, cwd=cwd, stdout=stream,
                                stderr=subprocess.STDOUT)
    records.append({'command': args, 'exit_code': result.returncode,
                    'seconds': round(time.monotonic() - start, 2), 'log': log})
    (STAGE / 'assembly-commands.json').write_text(json.dumps(records, indent=2) + '\n')
    assert result.returncode == 0, log
    print(log, 'passed', flush=True)


assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
    'b1485998-0a40-46b7-bd77-88796fa99a89'
assert 'spx_attempt=20260930ah' in Path('/proc/cmdline').read_text().split()
assert not (STAGE / 'assembly-started').exists()
build = json.loads((STAGE / 'build-complete.json').read_text())
assert build['release'] == RELEASE and build['modules'] == 187
assert build['embedded_config_exact'] and build['source_unchanged_during_build']
assert sha(STAGE / 'artifacts/.config') == sha(REPO / '.config')
assert (STAGE / 'logging/initrd-log.sh').is_file()
assert str(STAGE / 'logging') in (STAGE / 'initcpio/install/spx_diagnostics').read_text()
for name, digest in build['source_sha256'].items():
    assert sha(REPO / name) == digest, name
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO) == (
    STAGE / 'source.diff').read_bytes()
(STAGE / 'assembly-started').write_text(RELEASE + '\n')
records = []
run(['make', '-j4', f'INSTALL_MOD_PATH={STAGE / "module-root"}',
     'DEPMOD=true', 'modules_install'], 'modules-stage.log')
root = STAGE / 'module-root/lib/modules' / RELEASE
assert root.is_dir()
run(['depmod', '-b', str(STAGE / 'module-root'), '-ae', '-F',
     str(STAGE / 'artifacts/System.map'), RELEASE], 'depmod.log')
# mkinitcpio expects the uncompressed Image beside the staged module metadata.
shutil.copy2(STAGE / 'artifacts/arch/arm64/boot/Image', root / 'vmlinuz')
files = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
         if p.is_file() and not p.is_symlink()}
assert len(files) == 202, len(files)
(STAGE / 'module-sha256.json').write_text(json.dumps(files, indent=2) + '\n')
modules = sorted(root.rglob('*.ko'))
assert len(modules) == 187
vermagic = {}
for module in modules:
    value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)],
                                    text=True).strip()
    assert value.split()[0] == RELEASE, module
    vermagic[str(module.relative_to(root))] = value
(STAGE / 'module-vermagic.json').write_text(json.dumps(vermagic, indent=2) + '\n')
run(['mkinitcpio', '-k', RELEASE, '-r', str(STAGE / 'module-root'),
     '-c', str(STAGE / 'mkinitcpio.conf'),
     '-D', str(STAGE / 'initcpio'), '-D', '/etc/initcpio',
     '-D', '/usr/lib/initcpio', '-g', str(STAGE / 'initramfs.img'),
     '--nopost'], 'initramfs-build.log')
run(['lsinitcpio', '-l', str(STAGE / 'initramfs.img')],
    'initramfs-contents.txt')
assert 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh' in (
    STAGE / 'initramfs-contents.txt').read_text()
extract = STAGE / 'initramfs-extracted'
extract.mkdir()
run(['lsinitcpio', '-x', str(STAGE / 'initramfs.img')],
    'initramfs-extract.log', cwd=extract)
logger = extract / 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh'
assert sha(logger) == sha(STAGE / 'logging/initrd-log.sh')
for module in modules:
    name = str(module.relative_to(root))
    assert sha(module) == files[name], name
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
    'b1485998-0a40-46b7-bd77-88796fa99a89'
verification = {'release': RELEASE, 'modules': len(modules),
                'module_tree_files': len(files),
                'module_manifest_sha256': sha(STAGE / 'module-sha256.json'),
                'embedded_config_exact': True,
                'private_logger_exact': True,
                'artifacts': {
                    'vmlinuz': sha(STAGE / 'vmlinuz'),
                    'initramfs.img': sha(STAGE / 'initramfs.img'),
                    'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb':
                        sha(STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb'),
                    'artifacts/.config': sha(STAGE / 'artifacts/.config')},
                'source_diff_sha256': sha(STAGE / 'source.diff')}
(STAGE / 'build-verification.json').write_text(json.dumps(verification, indent=2) + '\n')
shutil.copy2(__file__, STAGE / 'assemble.py')
os.sync()
print(json.dumps(verification, indent=2), flush=True)
