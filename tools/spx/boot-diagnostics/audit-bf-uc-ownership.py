#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pin startup allocation context and separate it from the internal video SID."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf')
V = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ax/offline-video-startup-20261003/inventory')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    os.umask(0o077)
    sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
    import bf_boot_guard as g
    a = g.load()
    assert a['state'].startswith('BF terminal;')
    c = module(REPO / 'tools/spx/boot-diagnostics/audit-bf-startup-correlation.py', 'correlation')
    c.sealed(X / 'offline-startup-correlation-v4', '4fb9e1005be3321f6e9f9e1a6ee2e571aadbdcfa9169859dabd1ad77012ca886')
    c.sealed(V, '9196bea5634ff8df0491ba656e525f15cedc03f64acdea4f6f9ea81a3d0d023a')
    out = X / 'offline-uc-ownership-v2'
    assert not out.exists()
    out.mkdir(mode=0o700)
    for name in ('oem-00040.sys', 'audit_pep_loader.py', 'audit_startup.py', 'qcsmmu8180.inf.txt'):
        shutil.copy2(V / name, out / name)
    shutil.copy2(__file__, out / Path(__file__).name)
    image = module(out / 'audit_pep_loader.py', 'pe').Image((out / 'oem-00040.sys').read_bytes())
    startup = module(out / 'audit_startup.py', 'startup')
    assert c.sha(out / 'oem-00040.sys') == startup.MINIPORT_SHA
    inf = (out / 'qcsmmu8180.inf.txt').read_text()
    groups = startup.streams(inf)
    # Allocation caller and reserve callback use the ARM64 ninth argument on SP.
    # Two callee frame adjustments total 0xc0; loading SP+0xc0 reads that argument.
    pins = {
        0x358464: ('mov', 'w3, #4'),
        0x365430: ('ubfx', 'x26, x2, #0, #0x20'),
        0x365444: ('mov', 'w19, w3'),
        0x3654f4: ('mov', 'w20, #2'),
        0x3654f8: ('cmp', 'w19, #1, lsl #12'),
        0x365500: ('lsr', 'w19, w19, #1'),
        0x365508: ('add', 'w20, w20, #1'),
        0x365514: ('ldr', 'x19, [x8, #0x50]'),
        0x36552c: ('str', 'wzr, [sp]'),
        0x365540: ('mov', 'w2, w20'),
        0x365544: ('mov', 'w1, w26'),
        0x36554c: ('blr', 'x19'),
        0x366340: ('stp', 'x19, x20, [sp, #-0x50]!'),
        0x366354: ('stp', 'x29, x30, [sp, #-0x70]!'),
        0x366374: ('mov', 'w22, w1'),
        0x366394: ('mov', 'w21, w2'),
        0x3663a0: ('add', 'x24, x8, #0x10'),
        0x3665f0: ('ldr', 'w22, [sp, #0xc0]'),
        0x366604: ('madd', 'x9, x8, x13, x24'),
        0x366608: ('ldr', 'w10, [x9, #4]'),
        0x36660c: ('cmp', 'w22, w10'),
        0x366610: ('b.eq', '#0x140366620'),
        0x366634: ('ldr', 'x27, [x21, #0x20]'),
        0x366648: ('ldr', 'x19, [x8, #0x78]'),
        0x366674: ('blr', 'x19'),
        0x366878: ('ldr', 'x19, [x8, #0xc8]'),
        0x36688c: ('blr', 'x19'),
        0x366894: ('ands', 'x22, x24, #-0x100000000'),
    }
    decoded = {}
    listing = []
    gnu = []
    for start, end in ((0x365400, 0x36555c), (0x366340, 0x3663a8),
                       (0x3665e8, 0x36667c), (0x366874, 0x36689c),
                       (0x358458, 0x358478)):
        raw = image.read(start, end - start)
        path = out / (hex(start) + '.bin')
        path.write_bytes(raw)
        for i in Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(raw, image.base + start):
            decoded[i.address-image.base] = (i.mnemonic, i.op_str)
            listing.append(f'{i.address-image.base:#x}: {i.mnemonic} {i.op_str}')
        result = subprocess.run(['objdump', '-D', '-b', 'binary', '-m', 'aarch64',
            '--adjust-vma=' + hex(image.base + start), str(path)], capture_output=True, timeout=60)
        (out / (hex(start) + '.gnu.stdout')).write_bytes(result.stdout)
        (out / (hex(start) + '.gnu.stderr')).write_bytes(result.stderr)
        assert result.returncode == 0
        gnu.append(result.stdout.decode())
    def normalize(s):
        s = s.split('//', 1)[0]
        s = re.sub(r'#(-?(?:0x[0-9a-f]+|\d+))', lambda m: '#'+hex(int(m[1], 0)), s)
        return re.sub(r'\s+', '', s)
    for at, (mnemonic, operands) in pins.items():
        assert decoded[at] == (mnemonic, operands), hex(at)
        match = re.search(r'^\s*'+format(image.base+at,'x')+r':\s+[0-9a-f]{8}\s+(\S+)\s+(.+)$', '\n'.join(gnu), re.M)
        assert match and match[1] == mnemonic, hex(at)
        left, right = normalize(match[2]), normalize(operands)
        if mnemonic.startswith('b.'):
            left, right = int(left,16), int(right.removeprefix('#'),0)
        if mnemonic == 'ands':
            # Logical-immediate disassemblers use signed and unsigned spellings.
            lp, li = left.rsplit('#', 1)
            rp, ri = right.rsplit('#', 1)
            left, right = (lp, int(li, 0) & ((1 << 64)-1)), (rp, int(ri, 0) & ((1 << 64)-1))
        assert left == right, (hex(at),left,right)
    (out / 'selected-disassembly.txt').write_text('\n'.join(listing)+'\n')
    rows = [list(struct.unpack('<18I', image.read(0x1b56b0+16+n*72,72))) for n in range(4)]
    assert [r[1] for r in rows] == [0,1,3,4]
    ns, internal = rows[0], rows[3]
    assert ns[3:7] == [10,0,0x25800000,0xba800000]
    assert internal[3:7] == [13,0,0x1000000,0x24800000]
    # The primary callback table independently binds the function under examination.
    assert struct.unpack('<Q',image.read(0x1ac050+0x50,8))[0]-image.base == 0x366340
    assert internal[5]+internal[6] == ns[5]
    def matches(sid, base, mask):
        return (sid & ~mask) == (base & ~mask)
    assert all(matches(sid,0x2300,0x60) for sid in (0x2300,0x2320,0x2340))
    assert not any(matches(sid,0x2300,0x60) for sid in (0x2304,0x2324,0x2344))
    source = (REPO / 'drivers/iommu/arm/arm-smmu/arm-smmu.c').read_text()
    assert 'return arm_smmu_iova_to_phys_hard(domain, iova);' in source
    # A generic translation query may perform ATS MMIO; do not call it live.
    for name in ('drivers/iommu/iommu.c','drivers/iommu/arm/arm-smmu/arm-smmu.c',
                 'drivers/media/platform/qcom/venus/hfi_venus.c',
                 'drivers/media/platform/qcom/venus/firmware.c',
                 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):
        assert c.sha(REPO/name) == c.read(X/'assembly/source-files.json')[name]['sha256']
        target = out / name.replace('/','_')
        shutil.copy2(REPO/name,target)
    kernel=(X/'video-startup/kernel.stdout').read_text()
    assert 'platform aa00000.video-codec: Adding to iommu group 5' in kernel
    report = dict(primary_image_sha256=c.sha(out/'oem-00040.sys'),
        inventory_manifest_sha256=c.sha(V/'sha256.json'), original_stream_groups=groups,
        new_instruction_pins=len(pins), independent_gnu_pins=len(pins),
        retained_reserve_callback_rva='0x366340', caller_ninth_argument_context=0,
        caller_w3_is_alignment_not_internal_context=True, callback_frame_bytes=0xc0,
        selected_static_context=dict(type=0,cb=10,start=hex(ns[5]),length=hex(ns[6])),
        separate_internal_static_context=dict(type=4,cb=13,start=hex(internal[5]),length=hex(internal[6])),
        linux_nonsecure_mask_matches_internal_sids=False,
        actual_bf_iommu_group_observed=5, actual_bf_page_translation_observed=False,
        generic_iova_query_can_issue_mmio=True, hardware_operations=0,
        next_isolated_experiment='Allocate the declared shared UC size once; partition queue/SFR within it, use allocator-provided addresses and one owner/free operation, with an SC8180X/default-off trial gate.',
        required_offline_checks=['verbatim actual allocator/init/release/reinit paths with allocation failures and cleanup',
            'no suballocation dma_free or double free; zeroed shared backing and unchanged queue packet layout',
            'non-trial and other resources preserve their allocation traces',
            'queue/SFR/UC bounds at arbitrary allocator addresses; no hard-coded Windows IOVA',
            'native behavior and full distinct source/config/kernel/modules/initramfs/archive provenance before boot'],
        root_cause_proven=False, internal_secure_context_runtime_owner_proven=False,
        hardware_acceptance_closed=False,
        limits=['Static context selection does not prove observed Windows mapping or firmware execution.',
                'BF group enumeration is not page-table or internal secure-context translation proof.',
                'Internal SID absence from Linux nonsecure mask alone does not justify assigning secure-owned streams.',
                'Proposed geometry trial tests a hypothesis; it does not establish the firmware containment requirement.'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'sha256.json').write_text(json.dumps(c.files(out),indent=2)+'\n')
    c.sealed(out)
    assert not g.recovery(a).get('next_entry','')
    os.sync()
    print(json.dumps(report|{'manifest_sha256':c.sha(out/'sha256.json')},indent=2))


if __name__ == '__main__':
    main()
