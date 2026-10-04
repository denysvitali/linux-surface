#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pin SQ2 miniport startup instructions and retained video stream groups offline."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
REPO = next((p for p in Path(__file__).resolve().parents if (p / 'PORT-CHECKLIST.md').is_file()),
            Path('/home/dvitali/Documents/git/linux-surface-next'))
MINIPORT_SHA = '049da069400c124746e2f6ef0bd5851c603d865b3c1867e0c47c74e27c46220b'
SMMU_INF_SHA = '1e9e06a07882260542c51dbe6d1f9bf9a4f1becd91406cacf1977266d9676379'
INVENTORY_SHA = 'f7049b043c472599086e33d5c477b90a06606b68cd05d88c3e4bf50a23892c5f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path):
    spec = importlib.util.spec_from_file_location('video_pe_image', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify(root, digest):
    assert sha(root / 'sha256.json') == digest
    hashes = json.loads((root / 'sha256.json').read_text())
    assert set(hashes) == {p.name for p in root.iterdir()} - {'sha256.json'}
    for name, expected in hashes.items():
        assert Path(name).name == name and sha(root / name) == expected, name
    return hashes


def streams(source):
    """Retain literal INF rows; compare candidate SID/mask pairs to IORT separately."""
    sections = dict((m.group(1), m.group(2)) for m in re.finditer(
        r'^\[([^\]]+)\]\s*\n(.*?)(?=^\[|\Z)', source, re.M | re.S))
    expected = [(4, 10, 0x2300, 0x60), (0x10, 11, 0x2303, 0x20),
                (8, 12, 0x2301, 4), (0x40, 13, 0x2304, 0x60)]
    results = {}
    for revision in (1, 2):
        name = f'SMMU_V{revision}_Registry_Settings_Dynamic'
        rows = []
        for m in re.finditer(
                r'^HKR,0\\S2CB\\0x04\\(0x[0-9a-f]+)\\(0x[0-9a-f]+),'
                r'"MAP",%REG_BINARY%,([^\n]+)$', sections[name], re.M | re.I):
            vmid, cb = (int(m.group(i), 16) for i in (1, 2))
            values = [int(v.strip(), 16) for v in m.group(3).split(',')]
            assert len(values) == 5 and all(0 <= v <= 255 for v in values)
            assert values[0] == 0xff
            sid, mask = values[1] * 256 + values[2], values[3] * 256 + values[4]
            rows.append(dict(client=4, vmid=vmid, context_bank=cb,
                             literal_bytes=values, candidate_sid=sid, candidate_mask=mask))
        assert [(r['vmid'], r['context_bank'], r['candidate_sid'], r['candidate_mask'])
                for r in rows] == expected
        # VMID/context names below are comments in the retained INF, not live state.
        assert '(S1_VIDEO_HLOS)' in sections[name] and '(S1_VIDEO_CP_P)' in sections[name]
        results[name] = rows
    assert '03/20/2020,1.0.1040.0000' in source
    return results


# Each selected range is bounded by the original image's ARM64 .pdata record.
RANGES = [
    (0x33cb60, 0x33e5c4, 'VedStartEngine'),
    (0x34a788, 0x34b834, 'vedInitPlatformConfigs V1'),
    (0x357a10, 0x359ac8, 'VedInitVideoCore'),
    (0x356978, 0x35748c, 'VedHfiReset'),
    (0x361148, 0x36152c, 'VedHfiInterfaceQueuesInit'),
    (0x355a18, 0x35674c, 'VedHfiSysInit'),
    (0x356750, 0x356974, 'VedPilLoadAndReset'),
    (0x363420, 0x3640d4, 'VedInitSMMUInterface V2'),
    (0x3687f8, 0x368a04, 'CopySmmuARIDInfo'),
    (0x368a08, 0x368c14, 'CopySmmuCBIDInfo'),
]


def instructions(image):
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    decoded, metadata, listing = {}, [], []
    for start, end, role in RANGES:
        assert image.functions[start] == end
        raw = image.read(start, end - start)
        insns = list(md.disasm(raw, image.base + start))
        assert sum(i.size for i in insns) == len(raw)
        metadata.append(dict(start_rva=start, end_rva=end, role=role,
                             sha256=hashlib.sha256(raw).hexdigest(),
                             linear_instructions=len(insns), opaque=sum(not i.id for i in insns)))
        listing.append(f'\n{role}: {start:#x}..{end:#x}')
        for i in insns:
            at = i.address - image.base
            decoded[at] = (i.mnemonic, i.op_str)
            listing.append(f'{at:#x}: {i.mnemonic} {i.op_str}')
    pins = {
        0x33cd04: ('ldr', 'w9, [x9]'),
        0x33cd08: ('str', 'w9, [x21, x10]'),
        0x33ce14: ('strh', 'wzr, [x21, x9]'),
        0x34b26c: ('mov', 'w8, #0x50100000'),
        0x34b274: ('b.eq', '#0x14034b350'),
        0x34b350: ('mov', 'x8, #0x7014'),
        0x34b35c: ('str', 'x7, [x6]'),
        0x34a7c0: ('add', 'x7, x8, #0xd40'),
        0x34b444: ('mov', 'w11, #0x1f6'),
        0x34b44c: ('mov', 'x10, #0x7038'),
        0x34b458: ('str', 'w11, [x19, x10]'),
        0x3586cc: ('mov', 'x8, #0x7038'),
        0x3586d0: ('ldr', 'w4, [x22, x8]'),
        0x358744: ('str', 'w10, [x9, #0x10]'),
        0x3597bc: ('bl', '#0x140355a18'),
        0x355a3c: ('mov', 'w8, #0xc'),
        0x355a48: ('str', 'w8, [sp, #0x18]'),
        0x355a4c: ('mov', 'w9, #0x10001'),
        0x355a50: ('mov', 'w8, #2'),
        0x355a54: ('stp', 'w9, w8, [sp, #0x1c]'),
        0x35699c: ('bl', '#0x140361148'),
        0x3611b0: ('mov', 'w9, #0xc0'),
        0x3611b4: ('mov', 'w10, #0x18'),
        0x3611c4: ('mov', 'w10, #3'),
        0x3611c8: ('mov', 'w9, #0x38'),
        0x3611d4: ('mov', 'w14, #0x1010000'),
        0x361248: ('str', 'w11, [x8, #0xc]'),
        0x3612ac: ('b.lo', '#0x1403611e4'),
        0x3612fc: ('str', 'w10, [x9, #0x54]'),
        0x361414: ('str', 'w22, [x9, #0x50]'),
        0x356bbc: ('str', 'w10, [x9, #0x5c]'),
        0x356cdc: ('str', 'w10, [x9, #0x60]'),
        0x356e0c: ('str', 'w11, [x9, #0x64]'),
        0x356f34: ('mov', 'w10, #0x1000000'),
        0x356f3c: ('str', 'w10, [x9, #0x68]'),
        0x35708c: ('str', 'w10, [x9, #0x48]'),
        0x3571bc: ('ldr', 'w24, [x9, #0x4c]'),
        0x356854: ('mov', 'w8, #4'),
        0x356874: ('mov', 'w2, #0x2410'),
        0x356878: ('movk', 'w2, #0x9c41, lsl #16'),
        0x363ab8: ('mov', 'w1, #4'),
        0x363ac0: ('blr', 'x20'),
        0x36899c: ('madd', 'x10, x11, x15, x14'),
        0x3689a0: ('str', 'x8, [x10, #0x38]'),
        0x368bb0: ('str', 'x8, [x10, #0x30]'),
    }
    for at, expected in pins.items():
        assert decoded[at] == expected, (hex(at), decoded[at], expected)
    return metadata, listing, [dict(rva=at, mnemonic=value[0], operands=value[1])
                               for at, value in pins.items()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--inventory', type=Path, default=Path('/var/tmp/spx-video-integration-20261003-v1'))
    args = p.parse_args()
    verify(args.inventory, INVENTORY_SHA)
    inventory = json.loads((args.inventory / 'inventory.json').read_text())
    out = args.output
    out.mkdir(mode=0o700)
    vendor = Path('/home/dvitali/Documents/drivers/FileRepository/qcsmmu8180.inf_arm64_a3025ec179111ba9')
    paths = {name: args.inventory / name for name in ('oem-00040.sys', 'dsdt.dsl')}
    # Use the inventory's exact retained IORT filename rather than guessing one.
    iort_name = next(name for name in inventory['inputs'] if name.startswith('iort.'))
    paths[iort_name] = args.inventory / iort_name
    paths.update({name: vendor / name for name in ('qcsmmu8180.sys', 'qcsmmu8180.inf', 'SMMC.bin')})
    paths.update({
        'audit_pep_loader.py': REPO / 'tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_loader.py',
        'prior-inventory.json': args.inventory / 'inventory.json',
        'prior-sha256.json': args.inventory / 'sha256.json',
        'audit_startup.py': Path(__file__).resolve(),
    })
    for name in ('hfi_venus.c', 'hfi_cmds.c', 'hfi_cmds.h', 'hfi_helper.h', 'hfi_venus_io.h'):
        paths['linux-' + name] = REPO / 'drivers/media/platform/qcom/venus' / name
    expected = {
        'oem-00040.sys': MINIPORT_SHA,
        'qcsmmu8180.inf': SMMU_INF_SHA,
        'qcsmmu8180.sys': '152b8295a97855237cb8a5d37fbeae80b65b43d211e0d644ecf0e3cc0fb40e76',
        'SMMC.bin': 'b5bf1ef5c81d69135842d420b61bc6d52ee38df35d5513ca0b201e34c3f90bbf',
        'dsdt.dsl': 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8',
    }
    inputs = {}
    for name, path in paths.items():
        checksum = sha(path)
        if name in expected:
            assert checksum == expected[name], name
        inputs[name] = dict(path=str(path), sha256=checksum)
        shutil.copyfile(path, out / name)
        assert sha(out / name) == checksum
    image = module(out / 'audit_pep_loader.py').Image((out / 'oem-00040.sys').read_bytes())
    ranges, listing, pins = instructions(image)
    (out / 'miniport-disassembly.txt').write_text('\n'.join(listing) + '\n')
    inf = (out / 'qcsmmu8180.inf').read_text(encoding='utf-16')
    (out / 'qcsmmu8180.inf.txt').write_text(inf)
    groups = streams(inf)
    mappings = inventory['video_iort_mappings']
    assert len(mappings) == 10
    # These four literal hardware groups cover the ten retained output SIDs.
    sids = [row['output'] for row in mappings]
    for group in groups['SMMU_V2_Registry_Settings_Dynamic']:
        base, mask = group['candidate_sid'], group['candidate_mask']
        group['covered_iort_sids'] = [sid for sid in sids if (sid & ~mask) == (base & ~mask)]
        group['all_mask_aliases'] = [sid for sid in range(0x2300, 0x2380)
                                     if (sid & ~mask) == (base & ~mask)]
    assert [g['covered_iort_sids'] for g in groups['SMMU_V2_Registry_Settings_Dynamic']] == [
        [0x2300, 0x2320, 0x2340], [0x2303, 0x2323], [0x2301, 0x2305],
        [0x2304, 0x2324, 0x2344]]
    # Original ARM64 bytes, call-free and bounded, for isolated synthetic-RAM checks.
    fragments = [(0x3611ac, 0x3612dc, 'queue-builder.bin'),
                 (0x355a3c, 0x355a58, 'sys-init-builder.bin')]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    for start, end, name in fragments:
        raw = image.read(start, end - start)
        insns = list(md.disasm(raw, image.base + start))
        assert len(insns) * 4 == len(raw) and all(i.id for i in insns)
        assert all(i.mnemonic not in ('bl', 'blr', 'br', 'svc', 'hvc', 'smc', 'ret') for i in insns)
        for i in insns:
            if i.mnemonic.startswith('b.'):
                assert start <= i.operands[-1].imm - image.base < end
        (out / name).write_bytes(raw)
    pointers = list(struct.unpack('<7Q', image.read(0x1abd40, 56)))
    assert pointers == [0x140361d50, 0x1403626f0, 0x140053b40, 0x140053e20,
                        0, 0x14004f120, 0x14004f5d0]
    report = dict(inputs=inputs, prior_inventory_manifest_sha256=INVENTORY_SHA,
                  miniport_exception_records=image.exception_count, selected_ranges=ranges,
                  instruction_pins=pins, smmu_registry_groups=groups,
                  hfi5x_table_rva=0x1abd40, hfi5x_table_pointers=pointers,
                  conditional_hw_version=0x50100000, initial_interrupt_mask=0x1f6,
                  sys_init_words=[12, 0x10001, 2], uc_region_size=0x1000000,
                  hardware_operations=0, firmware_loaded=False,
                  limits=['Windows hardware-version selection has not been observed live.',
                          'All ten selected ranges are linear disassembly; this is not a full CFG or Windows execution.',
                          'Literal INF SID/mask interpretation agrees with IORT; Input-ID packing and runtime SMMU policy remain untraced.',
                          'Mask 0x60 includes a fourth alias absent from the retained three-entry IORT groups.',
                          'SYS_INIT/header contracts do not prove other packets, formats or firmware authentication.'])
    (out / 'startup.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    verify(out, sha(out / 'sha256.json'))
    print(json.dumps(dict(files=len(hashes), selected_ranges=len(ranges),
                          instruction_pins=len(pins), manifest_sha256=sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
