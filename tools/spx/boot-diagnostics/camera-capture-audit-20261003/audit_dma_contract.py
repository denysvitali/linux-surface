#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reconcile retained SQ2 IORT, SMMU INF and camera resources offline.

No device access or vendor code execution. Output is exclusive; firmware data
and historical camera sources are copied without changing their bytes.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys

import libfdt

REPO = Path(__file__).resolve().parents[4]
FW = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2')
V23 = REPO.parent / 'linux-surface-kernel/docs/camdtb'
INF = Path('/home/dvitali/Documents/drivers/FileRepository/'
           'qcsmmu8180.inf_arm64_a3025ec179111ba9/qcsmmu8180.inf')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iort_bytes(text):
    raw = bytearray()
    for line in text.splitlines():
        match = re.fullmatch(r'\s+([0-9A-F]{4}): ([0-9A-F ]+?)\s*//.*', line)
        if match:
            assert int(match[1], 16) == len(raw), 'noncontiguous raw table'
            raw.extend(bytes.fromhex(match[2]))
    assert raw[:4] == b'IORT'
    assert struct.unpack_from('<I', raw, 4)[0] == len(raw) == 0x1943
    assert sum(raw) % 256 == 0, 'ACPI checksum'
    return bytes(raw)


def parse_iort(raw):
    count, offset = struct.unpack_from('<II', raw, 36)
    assert count == 26 and offset == 0x30
    nodes = []
    for _ in range(count):
        kind, length, revision, identifier, mappings, map_offset = \
            struct.unpack_from('<BHBIII', raw, offset)
        assert length >= 16 and offset + length <= len(raw)
        assert not mappings or 16 <= map_offset <= length - mappings * 20
        node = dict(offset=offset, type=kind, length=length, revision=revision,
                    identifier=identifier, mapping_offset=map_offset, mappings=[])
        if kind == 1:
            name = raw[offset + 29:offset + (map_offset or length)]
            node['name'] = name.split(b'\0', 1)[0].decode('ascii')
        if kind == 3:
            node['base'], node['span'] = struct.unpack_from('<QQ', raw, offset + 16)
        for index in range(mappings):
            values = struct.unpack_from('<IIIII', raw, offset + map_offset + index * 20)
            node['mappings'].append(dict(zip(
                ('input_base', 'id_count', 'output_base', 'output_reference', 'flags'), values)))
        nodes.append(node)
        offset += length
    assert offset == len(raw)
    offsets = {node['offset'] for node in nodes}
    assert all(m['output_reference'] in offsets for n in nodes for m in n['mappings'])
    return nodes


def device_block(text, name):
    # Strip comments before balancing; all retained device strings have no braces.
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    matches = list(re.finditer(r'\bDevice \(' + re.escape(name) + r'\)', text))
    assert len(matches) == 1
    start = matches[0].start()
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def resources(text, name):
    block = device_block(text, name)
    # _CRS contains one literal RBUF ResourceTemplate in these two devices.
    assert len(re.findall(r'Method \(_CRS,', block)) == 1
    start = block.index('Method (_CRS,')
    end = block.index('Return (RBUF)', start)
    crs = block[start:end]
    mmio = [dict(access=a, base=int(b, 16), size=int(s, 16)) for a, b, s in
            re.findall(r'Memory32Fixed \((ReadWrite|ReadOnly),\s*'
                       r'(0x[0-9A-F]+),\s*(0x[0-9A-F]+)', crs)]
    irq = [dict(gsi=int(g, 16), spi=int(g, 16)-32, trigger='edge-rising') for g in
           re.findall(r'Interrupt \(ResourceConsumer, Edge, ActiveHigh, Exclusive,'
                      r'[^)]*\)\s*\{\s*(0x[0-9A-F]+),\s*\}', crs)]
    assert len(mmio) == crs.count('Memory32Fixed (')
    assert len(irq) == crs.count('Interrupt (')
    return dict(mmio=mmio, interrupts=irq)


def cells(data):
    assert len(data) % 4 == 0
    return list(struct.unpack('>' + 'I' * (len(data) // 4), data))


def strings(data):
    assert bytes(data).endswith(b'\0')
    return bytes(data)[:-1].decode().split('\0')


def main():
    out = Path(sys.argv[1])
    out.mkdir(mode=0o700)  # Refuse existing output, including failed runs.
    pinned = {
        'dsdt.dsl': (FW / 'dsdt.dsl', 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'),
        'iort.dsl': (FW / 'iort.dsl', '8c74750be80f39c29e713c8a0783cb9a554f7db5b1b40497f6965bec8a05eea2'),
        'qcsmmu8180.inf': (INF, '1e9e06a07882260542c51dbe6d1f9bf9a4f1becd91406cacf1977266d9676379'),
        'v23.dts': (V23 / 'v23.dts', 'e69f2637abc57ec2eca28925ce9b3e5c984e1d0085f06c0f45d6148fb92899d7'),
        'v23.dtb': (V23 / 'v23.dtb', '24453b427caa64c20424006db4a1a53d9a608bc64acf64a64a3a30997c163ff1'),
    }
    paths = {name: path for name, (path, digest) in pinned.items()}
    for name, (path, digest) in pinned.items():
        assert sha(path) == digest, name
    paths.update({
        'arm-smmu.c': REPO / 'drivers/iommu/arm/arm-smmu/arm-smmu.c',
        'iort.c': REPO / 'drivers/acpi/arm64/iort.c',
        'camss.c': REPO / 'drivers/media/platform/qcom/camss/camss.c',
        'audit_dma_contract.py': Path(__file__).resolve(),
    })
    inputs = {}
    for name, path in paths.items():
        inputs[name] = dict(path=str(path), sha256=sha(path))
        shutil.copyfile(path, out / name)
        assert sha(out / name) == inputs[name]['sha256']

    raw = iort_bytes((out / 'iort.dsl').read_text())
    (out / 'iort-reconstructed.dat').write_bytes(raw)
    nodes = parse_iort(raw)
    apps = next(n for n in nodes if n['offset'] == 0x30)
    assert apps['type'] == 3 and apps['base'] == 0x15000000
    avs = next(n for n in nodes if n.get('name') == r'\_SB.GPU0.AVS0')
    assert len(avs['mappings']) == 31
    # Use the actual INF assignments, excluding all semicolon comments.
    text = (out / 'qcsmmu8180.inf').read_text(encoding='utf-16')
    records, section = [], None
    for number, line in enumerate(text.splitlines(), 1):
        active = line.split(';', 1)[0].strip()
        if active.startswith('['):
            section = active
        match = re.fullmatch(r'HKR,0\\S2CB\\0x01\\0x04\\0x15,"MAP",%REG_BINARY%,\s*(.*)', active)
        if match:
            values = bytes(int(v.strip(), 16) for v in match[1].split(','))
            assert values == bytes.fromhex('ff 0a 00 04 e0')
            records.append(dict(section=section, line=number, bytes=values.hex(' ')))
    assert len(records) == 2
    # INF column comments identify the two big-endian byte pairs as SID/mask;
    # cross-check their interpretation against historical DT and actual IORT.
    sid, mask = 0xa00, 0x4e0
    expanded = [v for v in range(1 << 16) if ((v ^ sid) & ~mask) == 0]
    expected = [base + step for base in (0xa00, 0xe00) for step in range(0, 0x100, 0x20)]
    assert expanded == expected and len(expanded) == 16
    camera_maps = [m for m in avs['mappings'] if m['output_base'] in expanded]
    assert len(camera_maps) == 16
    assert sorted(m['output_base'] for m in camera_maps) == expanded
    assert all(m['id_count'] == m['flags'] == 0 and m['output_reference'] == 0x30
               for m in camera_maps)
    assert [m['input_base'] for m in camera_maps] == list(range(0x01030006, 0x01030016))
    matches = []
    for node in nodes:
        for m in node['mappings']:
            if m['output_reference'] == 0x30:
                assert m['flags'] == 0
                overlap = sorted(set(range(m['output_base'], m['output_base'] + m['id_count'] + 1)) & set(expanded))
                if overlap:
                    matches.append(dict(node=node.get('name', node['offset']), mapping=m, overlap=overlap))
    assert len(matches) == 16 and all(m['node'] == avs['name'] for m in matches)

    dsdt = (out / 'dsdt.dsl').read_text()
    avs_block = device_block(dsdt, 'AVS0')
    assert r'\_SB.MMU0' in avs_block and r'\_SB.VFE0' in avs_block
    devices = {name: resources(dsdt, name) for name in ('MPCS', 'VFE0')}
    assert [(len(devices[n]['mmio']), len(devices[n]['interrupts']))
            for n in ('MPCS', 'VFE0')] == [(4, 4), (20, 24)]
    fdt = libfdt.Fdt((out / 'v23.dtb').read_bytes())
    cam = fdt.path_offset('/soc@0/camss@ac65000')
    iommu = cells(fdt.getprop(cam, 'iommus'))
    assert iommu == [0x2e, sid, mask]
    provider = fdt.node_offset_by_phandle(iommu[0])
    assert fdt.get_name(provider) == 'iommu@15000000'
    assert cells(fdt.getprop(provider, '#iommu-cells')) == [2]
    reg = cells(fdt.getprop(cam, 'reg'))
    reg_names = strings(fdt.getprop(cam, 'reg-names'))
    irqs = cells(fdt.getprop(cam, 'interrupts'))
    irq_names = strings(fdt.getprop(cam, 'interrupt-names'))
    assert len(reg) == 80 and len(irqs) == 60
    assert len(set(reg_names)) == len(set(irq_names)) == 20
    assert set(reg_names) == set(irq_names)
    rows = []
    for i, name in enumerate(reg_names):
        high, base, size_high, size = reg[i*4:i*4+4]
        assert high == size_high == 0
        device = 'MPCS' if name.startswith('csiphy') else 'VFE0'
        containing = [r for r in devices[device]['mmio']
                      if r['base'] <= base and base+size <= r['base']+r['size']]
        assert len(containing) == 1 and containing[0]['access'] == 'ReadWrite', name
        irq_index = irq_names.index(name)
        kind, spi, trigger = irqs[irq_index*3:irq_index*3+3]
        assert kind == 0 and trigger == 1
        firmware_irq = [r for r in devices[device]['interrupts'] if r['spi'] == spi]
        assert len(firmware_irq) == 1, name
        rows.append(dict(name=name, base=base, size=size, device=device,
                         firmware_range=containing[0], spi=spi, gsi=spi+32,
                         trigger='edge-rising'))
    result = dict(
        scope='Offline C01 DMA and resource correspondence; no functional hardware acceptance',
        inputs=inputs, reconstructed_iort_sha256=sha(out / 'iort-reconstructed.dat'),
        iort_nodes=nodes, active_inf_records=records, sid=sid, mask=mask,
        expanded_streams=expanded, camera_iort_node=avs['name'],
        camera_iort_mappings=camera_maps, full_table_overlaps=matches,
        firmware_devices=devices, resource_correspondence=rows,
        limits=['INF semantics use declared columns, cross-checked with DT/IORT; vendor binary not executed',
                'IORT namespace placement and DSDT dependency do not transfer GPU DMA ownership',
                'Resource containment does not validate register programming, hardware version or clocks',
                'Analog supply ownership, streaming, DMA faults, images and physical privacy remain untested'],
    )
    (out / 'dma-contract.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir())))
    print(json.dumps(dict(output=str(out), manifest_sha256=sha(out / 'SHA256SUMS'),
                         streams=16, register_ranges=len(rows), interrupts=len(rows))))


if __name__ == '__main__':
    main()
