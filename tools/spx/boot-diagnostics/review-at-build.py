#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify AT's reused full source, payloads and enabled rear-only DT delta."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

import libfdt

X = Path('/var/lib/spx-boot-diagnostics/attempts/20261003at')
RELEASE = '7.3.0-rc2-spx-mainline-20261003ar+'
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
        '29748fff-2312-42c5-982e-04bbd2304b52'
    report = json.loads((X / 'archive-review.json').read_text())
    assert report['release'] == RELEASE
    for name, root in [('build-sha256.json', 'build'), ('dtb-sha256.json', 'dtb-build')]:
        assert files(X / root) == json.loads((X / name).read_text()), name
    build = X / 'build'
    assert gzip.decompress((build / 'vmlinuz').read_bytes()) == (build / 'artifacts/arch/arm64/boot/Image').read_bytes()
    assert (build / 'config-extracted').read_bytes() == (build / 'artifacts/.config').read_bytes()
    from build_ar_config_review import verify_config
    verify_config(build / 'config-before', build / 'artifacts/.config', build / 'config-delta.json')
    prepared = json.loads((build / 'prepared.json').read_text())
    assert sha(build / 'artifacts/.config') == prepared['config_sha256']
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
                 'sound/soc/codecs/wsa881x.c', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):
        assert sha(repo / name) == actual[name]['sha256'], name
    parent = Path('/var/lib/spx-boot-diagnostics/attempts/20261003as')
    assert sha(X / 'build-sha256.json') == sha(parent / 'build-sha256.json')
    for payload in ('vmlinuz', 'initramfs.img'):
        assert sha(build / payload) == sha(parent / 'build' / payload)
    before_raw = (parent / 'dtb-build/spx.dtb').read_bytes()
    candidate_raw = (X / 'dtb-build/spx.dtb').read_bytes()
    assert sha(X / 'dtb-build/spx.dtb') == '50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c'
    before, after = flatten(before_raw), flatten(candidate_raw)
    archived = json.loads((X / 'dtb-build/result.json').read_text())
    assert archived['all_other_nodes_properties_reservations_exact']
    assert archived['candidate_dtb_sha256'] == sha(X / 'dtb-build/spx.dtb')
    cci = '/soc@0/cci@ac4a000'
    rear = cci + '/i2c-bus@0/camera@10'
    led = '/camera-privacy-leds/led-0'
    new_nodes = set(after) - set(before)
    assert new_nodes == {'/camera-privacy-leds', led} and not set(before) - set(after)
    for name in before:
        properties = dict(after[name])
        if name == rear:
            assert set(properties) - set(before[name]) == {'leds', 'led-names'}
            del properties['leds'], properties['led-names']
        assert before[name] == properties, name
    for node in (cci, rear):
        assert after[node]['status'] == b'okay\0'.hex()
    assert after[cci]['assigned-clock-rates'] == (37500000).to_bytes(4, 'big').hex()
    base, candidate = libfdt.Fdt(before_raw), libfdt.Fdt(candidate_raw)
    assert base.num_mem_rsv() == candidate.num_mem_rsv()
    assert all(base.get_mem_rsv(n) == candidate.get_mem_rsv(n) for n in range(base.num_mem_rsv()))
    led_h = candidate.getprop(candidate.path_offset(rear), 'leds').as_uint32()
    assert candidate.get_path(candidate.node_offset_by_phandle(led_h)) == led
    assert candidate.getprop(candidate.path_offset(rear), 'led-names') == b'privacy\0'
    gpio = candidate.getprop(candidate.path_offset(led), 'gpios')
    assert len(gpio) == 12 and int.from_bytes(gpio[4:8], 'big') == 11 and int.from_bytes(gpio[8:12], 'big') == 0
    assert candidate.get_path(candidate.node_offset_by_phandle(int.from_bytes(gpio[:4], 'big'))) == '/soc@0/pinctrl@3100000'
    assert candidate.getprop(candidate.path_offset(led), 'default-state') == b'off\0'
    assert 'CONFIG_LEDS_GPIO=y\n' in (build / 'artifacts/.config').read_text()
    mods = json.loads((build / 'module-sha256.json').read_text())
    root = build / 'module-root/lib/modules' / RELEASE
    assert files(root) == mods and len(mods) == 208
    vermagic = {}
    for module in sorted(root.rglob('*.ko')):
        value = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
        assert value.split()[0] == RELEASE
        vermagic[str(module.relative_to(root))] = value
    assert len(vermagic) == 193 and vermagic == json.loads((build / 'module-vermagic.json').read_text())
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
              'embedded_config_exact': True, 'reviewed_config_delta_exact': True,
              'new_dtb_nodes': sorted(new_nodes), 'existing_dtb_properties_exact_except_rear_led': True, 'rear_only_enabled_scope_verified': True, 'kernel_modules_initramfs_reused_exact_ar': True,
              'module_files_verified': 208, 'module_vermagic_records_verified': 193,
              'embedded_modules_verified': 54, 'build_manifest_sha256': sha(X / 'build-sha256.json'),
              'full_source_archive_sha256': sha(build / 'source.tar.zst'),
              'boot_selected': False, 'deployed': False}
    (X / 'independent-build-review.json').write_text(json.dumps(result, indent=2) + '\n')
    os.sync()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
