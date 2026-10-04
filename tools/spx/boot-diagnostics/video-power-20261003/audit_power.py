#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve Iris1 power contracts and the guarded known-good RAM map, read only."""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ax_boot_guard as g

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
PRIOR = Path('/var/tmp/spx-video-integration-20261003-v1')
BOOT = 'b6b4f20b-376f-4577-b282-677ad4ae0ec8'
INVENTORY = 'f7049b043c472599086e33d5c477b90a06606b68cd05d88c3e4bf50a23892c5f'
PEP_SHA = '751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde'


def module(path):
    spec = importlib.util.spec_from_file_location('video_power_image', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def contracts(image, inventory):
    q = lambda a: struct.unpack('<Q', image.read(a, 8))[0]
    w = lambda a: struct.unpack('<I', image.read(a, 4))[0]
    string = lambda a: image.read(a, 120).split(b'\0')[0].decode('ascii')
    names = {
        'gcc_video_axic_clk': 0x10b02c, 'gcc_video_axi0_clk': 0x10b024,
        'gcc_video_axi1_clk': 0x10b028, 'video_cc_iris_ahb_clk': 0xab008f4,
        'video_cc_mvsc_core_clk': 0xab00850, 'video_cc_mvs0_core_clk': 0xab00890,
        'video_cc_mvs1_core_clk': 0xab008d0,
    }
    clocks = {}
    for i in range(427):
        at = 0x18ae00 + i * 0x60
        name = string(q(at) - image.base)
        if name not in names:
            continue
        assert q(at + 0x18) == names[name]
        domain = q(at + 8) - image.base
        count, table = w(domain + 8), q(domain) - image.base
        plan = []
        for n in range(count):
            entry = table + n * 0x38
            plan.append(dict(record_rva=entry, frequency_hz=w(entry), raw_corner=w(entry + 0x18),
                             trailing_fields_hex=image.read(entry + 0x20, 0x18).hex()))
        clocks[name] = dict(node_rva=at, branch_address=names[name], domain_rva=domain, plan=plan)
    assert set(clocks) == set(names)
    assert len({clocks[n]['domain_rva'] for n in names if n.startswith('video_cc_')}) == 1
    assert [r['frequency_hz'] for r in clocks['video_cc_mvsc_core_clk']['plan']] == \
        [200000000, 225000000, 240000000, 300000000, 338000000,
         365000000, 432000000, 444000000, 480000000, 533000000]
    pd_names = {'mvsc_gdsc': 0xab00814, 'mvs0_gdsc': 0xab00874, 'mvs1_gdsc': 0xab008b4}
    domains = {}
    for i in range(39):
        at = 0x19c550 + i * 0x48
        name = string(q(at) - image.base)
        if name not in pd_names:
            continue
        assert q(at + 0x10) == pd_names[name]
        assert q(at + 0x18) - image.base == 0x19f928
        assert q(at + 0x38) - image.base == 0x196230
        domains[name] = dict(node_rva=at, register_address=pd_names[name],
                             hal_rva=0x19f928, rail_rva=0x196230)
    assert set(domains) == set(pd_names)
    assert string(q(0x196230) - image.base) == '/arc/client/rail_mmcx'
    labels = {n: string(q(0x1c08a0 + n * 8) - image.base) for n in range(16)}
    assert labels[1] == 'ENABLE' and labels[2] == 'DISABLE'
    assert labels[14] == 'RESETCLOCK_BRANCH_ASSERT' and labels[15] == 'RESETCLOCK_BRANCH_DEASSERT'
    component = inventory['g4md'][0][2]
    assert component[:2] == ['COMPONENT', 4]
    states = {row[1]: row for row in component[2:] if row[0] == 'FSTATE'}
    operations = {}
    for state, length in [(1, 24), (2, 31)]:
        exit_ops = next(row[1:] for row in states[state][2:] if row[0] == 'EXIT')
        assert len(exit_ops) == length
        footswitches = [row[1] for row in exit_ops if row[0] == 'FOOTSWITCH']
        assert footswitches == [['mvsc_gdsc', 1], ['mvs0_gdsc', 1], ['mvs1_gdsc', 1],
                               ['mvs0_gdsc', 3], ['mvs1_gdsc', 3]]
        reset_ops = [row[1] for row in exit_ops if row[0] == 'CLOCK' and row[1][1] in (14, 15)]
        assert reset_ops == [['gcc_video_axic_clk', 14], ['video_cc_mvsc_core_clk', 14],
                             ['gcc_video_axic_clk', 15], ['video_cc_mvsc_core_clk', 15]]
        enabled = [row[1][0] for row in exit_ops if row[0] == 'CLOCK' and row[1][1] == 1]
        assert enabled[-7:] == list(names)
        operations[state] = exit_ops
    return dict(clocks=clocks, domains=domains, clock_operation_labels=labels,
                retained_exit_operations=operations,
                limits=['The initial retained PEP tables are not an observation of the live Windows BSP.',
                        'Raw frequency-plan eligibility fields and corners have not been translated into Linux OPP levels.',
                        'The label table names raw clock operations; the complete execution dispatcher is not traced.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert os.geteuid() == 0 and Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    env = g.recovery(a)
    assert not env.get('next_entry', '')
    assert g.sha(PRIOR / 'sha256.json') == INVENTORY
    pins = json.loads((PRIOR / 'sha256.json').read_text())
    os.umask(0o077)
    out = args.output
    out.mkdir(mode=0o700)
    inputs = {}

    def copy(path, name):
        assert path.is_file() and not path.is_symlink(), str(path)
        digest = g.sha(path)
        shutil.copyfile(path, out / name)
        assert g.sha(out / name) == digest
        inputs[name] = dict(path=str(path), sha256=digest)

    for name in ('inventory.json', 'sha256.json', 'dsdt.dsl'):
        if name != 'sha256.json':
            assert g.sha(PRIOR / name) == pins[name]
        copy(PRIOR / name, 'prior-' + name)
    pep = Path('/var/tmp/spx-pep-loader-contract-20261003-v1/qcpep8180.sys')
    assert g.sha(pep) == PEP_SHA
    copy(pep, 'qcpep8180.sys')
    copy(REPO / 'tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_loader.py', 'audit_pep_loader.py')
    image = module(out / 'audit_pep_loader.py').Image((out / 'qcpep8180.sys').read_bytes())
    evidence = contracts(image, json.loads((out / 'prior-inventory.json').read_text()))
    for rel in ('drivers/clk/qcom/videocc-sm8150.c', 'drivers/clk/qcom/gcc-sc8180x.c',
                'drivers/clk/qcom/gdsc.c', 'drivers/clk/qcom/gdsc.h',
                'drivers/of/of_reserved_mem.c', 'drivers/soc/qcom/mdt_loader.c',
                'include/dt-bindings/clock/qcom,videocc-sm8150.h',
                'include/dt-bindings/clock/qcom,gcc-sc8180x.h',
                'arch/arm64/boot/dts/qcom/sc8180x.dtsi',
                'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'):
        copy(REPO / rel, Path(rel).name)
    reference = Path('/var/tmp/spx-video-integration-fetch-20261003')
    fetch = json.loads((reference / 'fetch.json').read_text())
    copy(reference / 'fetch.json', 'reference-fetch.json')
    for name in ('sm8150-vidc.dtsi', 'venus_hfi.c', 'msm_vidc_platform.c'):
        copy(reference / name, 'reference-' + name)
    # /proc/iomem hides addresses from unprivileged readers, hence the root guard.
    iomem = Path('/proc/iomem').read_text()
    (out / 'iomem.txt').write_text(iomem)
    reservations = [(int(a, 16), int(b, 16)) for a, b in
                    re.findall(r'^\s*([0-9a-f]+)-([0-9a-f]+) : reserved$', iomem, re.M)]
    assert any(start <= 0x8bd80000 <= end and end >= 0x9a4fffff for start, end in reservations)
    for path, name in [('/sys/firmware/fdt', 'live-fdt.dtb'),
                       ('/proc/cmdline', 'cmdline.txt'), ('/proc/sys/kernel/random/boot_id', 'boot-id.txt')]:
        (out / name).write_bytes(Path(path).read_bytes())
    efimap = Path('/sys/firmware/efi/memmap')
    (out / 'efi-memmap-status.json').write_text(json.dumps(dict(path=str(efimap), exists=efimap.exists())) + '\n')
    logs = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=10)
    assert logs.returncode == 0
    (out / 'memory-dmesg.txt').write_text('\n'.join(line for line in logs.stdout.splitlines()
        if re.search(r'efi:|reserved mem|Reserved memory|OF: reserved|Memory:|Zone ranges', line, re.I)) + '\n')
    evidence.update(inputs=inputs, utc=datetime.now(timezone.utc).isoformat(), boot_id=BOOT,
                    release=os.uname().release, saved_entry=env['saved_entry'], next_entry=env.get('next_entry', ''),
                    efi_bootnext=False, old_image_loader_region_is_reserved=True,
                    proposed_firmware_allocation=dict(size_bytes=0x500000, alignment_bytes=0x100000,
                        no_map=True, dynamic_early_memblock=True, physical_address_chosen=False,
                        limit='Allocate below 4 GiB from actual free RAM, excluding existing reservations.'),
                    firmware_loaded=False, video_mmio_operations=0, boot_selection_changes=0,
                    reference_fetch_manifest_sha256=g.sha(reference / 'fetch.json'))
    (out / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    copy(Path(__file__), 'audit_power.py')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    manifest = ''.join(f'{g.sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(manifest)
    print(json.dumps(dict(files=len(manifest.splitlines()), manifest_sha256=g.sha(out / 'SHA256SUMS'),
                         clocks_verified=7, domains_verified=3, boot_id=BOOT,
                         old_image_loader_region_is_reserved=True)), flush=True)


if __name__ == '__main__':
    main()
