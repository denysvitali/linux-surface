#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify AQ's full archived source, payloads and one-subtree DT delta."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

import libfdt

X = Path('/var/lib/spx-boot-diagnostics/attempts/20261003aq')
RELEASE = '7.3.0-rc2-spx-mainline-20261003aq+'
PROVIDER = '/soc@0/spmi@c440000/pmic@1/regulators'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def files(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def flatten(raw):
    fdt = libfdt.Fdt(raw)
    result = {}
    offset, depth = 0, 0
    while offset >= 0 and depth >= 0:
        path = fdt.get_path(offset)
        properties = {}
        p = fdt.first_property_offset(offset, quiet=(libfdt.NOTFOUND,))
        while p >= 0:
            value = fdt.get_property_by_offset(p)
            properties[value.name] = bytes(value).hex()
            p = fdt.next_property_offset(p, quiet=(libfdt.NOTFOUND,))
        result[path] = properties
        offset, depth = fdt.next_node(offset, depth, quiet=(libfdt.NOTFOUND,))
    return result


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not (X / 'independent-build-review.json').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == \
        '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'
    report = json.loads((X / 'archive-review.json').read_text())
    assert report['release'] == RELEASE
    for name, root in [('build-sha256.json', 'build'), ('dtb-sha256.json', 'dtb-build'),
                       ('source-review-sha256.json', 'source-review')]:
        assert files(X / root) == json.loads((X / name).read_text()), name
    build = X / 'build'
    assert gzip.decompress((build / 'vmlinuz').read_bytes()) == (build / 'artifacts/arch/arm64/boot/Image').read_bytes()
    assert (build / 'config-extracted').read_bytes() == (build / 'artifacts/.config').read_bytes()
    original = set((build / 'config-before').read_text().splitlines())
    current = set((build / 'artifacts/.config').read_text().splitlines())
    assert original - current == {'CONFIG_LOCALVERSION="-spx-mainline-20261001am"'}
    assert current - original == {'CONFIG_LOCALVERSION="-spx-mainline-20261003aq"'}
    expected = json.loads((build / 'source-files.json').read_text())
    actual = {}
    process = subprocess.Popen(['zstd', '-dc', str(build / 'source.tar.zst')], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                assert entry.name.startswith('source/')
                name = entry.name[len('source/'):]
                assert name in expected and name not in actual, name
                if entry.issym():
                    actual[name] = {'symlink': entry.linkname}
                else:
                    assert entry.isfile(), (name, entry.type)
                    digest = hashlib.sha256()
                    stream = archive.extractfile(entry)
                    for block in iter(lambda: stream.read(1048576), b''):
                        digest.update(block)
                    actual[name] = {'sha256': digest.hexdigest(), 'mode': entry.mode & 0o777}
        assert process.wait(timeout=30) == 0
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    assert actual == {name: data for name, data in expected.items() if not data.get('absent')}
    # These reviewed code inputs must match the actual archived build snapshot.
    repo = Path('/home/dvitali/Documents/git/linux-surface-next')
    for name in ('drivers/regulator/qcom_spmi-regulator.c', 'drivers/hid/spi-hid/spi-hid-core.c',
                 'drivers/media/i2c/ov13858.c', 'drivers/soundwire/qcom.c',
                 'sound/soc/codecs/wsa881x.c'):
        assert sha(repo / name) == actual[name]['sha256'], name
    before = flatten((build / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb').read_bytes())
    after = flatten((X / 'dtb-build/spx.dtb').read_bytes())
    new_nodes = set(after) - set(before)
    assert new_nodes == {PROVIDER, *(PROVIDER + '/' + name for name in ('l1', 'l14', 'l17'))}
    assert not set(before) - set(after)
    assert all(before[name] == after[name] for name in before)
    mods = json.loads((build / 'module-sha256.json').read_text())
    root = build / 'module-root/lib/modules' / RELEASE
    assert files(root) == mods and len(mods) == 202
    vermagic = {}
    for module in sorted(root.rglob('*.ko')):
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
        assert value.split()[0] == RELEASE
        vermagic[str(module.relative_to(root))] = value
    assert len(vermagic) == 187 and vermagic == json.loads((build / 'module-vermagic.json').read_text())
    extracted = build / 'initramfs-extracted'
    prefix = 'usr/lib/modules/' + RELEASE + '/'
    embedded = sorted(extracted.rglob('*.ko'))
    assert len(embedded) == 54
    for module in embedded:
        name = str(module.relative_to(extracted))
        assert name.startswith(prefix) and sha(module) == mods[name[len(prefix):]]
    result = {'release': RELEASE, 'full_source_archive_stream_verified': True,
              'archived_source_files_links_verified': len(actual),
              'source_manifest_records': len(expected), 'compressed_kernel_exact': True,
              'embedded_config_exact': True, 'config_delta_localversion_only': True,
              'new_dtb_nodes': sorted(new_nodes), 'all_existing_dtb_properties_exact': True,
              'module_files_verified': 202, 'module_vermagic_records_verified': 187,
              'embedded_modules_verified': 54, 'build_manifest_sha256': sha(X / 'build-sha256.json'),
              'full_source_archive_sha256': sha(build / 'source.tar.zst'),
              'boot_selected': False, 'deployed': False}
    (X / 'independent-build-review.json').write_text(json.dumps(result, indent=2) + '\n')
    os.sync()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
