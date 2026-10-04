#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Correlate actual BF observations with retained instructions, without HW I/O."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bf')
CONTRACTS = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ax/offline-video-iris1-20261003/contracts')
OUT = X / 'offline-startup-correlation-v4'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sealed(root, expected=None):
    if expected:
        assert sha(root / 'sha256.json') == expected
    assert files(root) == read(root / 'sha256.json') | {'sha256.json': sha(root / 'sha256.json')}


def run(label, argv):
    p = subprocess.run(argv, capture_output=True, timeout=90)
    (OUT / (label + '.stdout')).write_bytes(p.stdout)
    (OUT / (label + '.stderr')).write_bytes(p.stderr)
    assert p.returncode == 0, (label, p.returncode)
    return p.stdout.decode()


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and not OUT.exists()
    sealed(CONTRACTS, '3bb3dfcd86755512b811bda2e955bce5083c2e42c2e93ffc53f550629f8eee21')
    sealed(X / 'startup-review', 'd28aa69b9509b565b642343c1282af2be07f50db30547f9f7e0a4b6a4b9348dc')
    sealed(X / 'video-startup', '34970765ebb61fd6ae0262aa43ef8a5c92336460f0e67a1203dac56d9f4aa397')
    OUT.mkdir(mode=0o700)
    inputs = {}

    def retain(name, path):
        shutil.copy2(path, OUT / name)
        assert sha(OUT / name) == sha(path)
        inputs[name] = {'path': str(path), 'sha256': sha(path)}

    retain(Path(__file__).name, Path(__file__))
    for name in ('audit_pep_loader.py', 'audit_contracts.py', 'oem-00040.sys', 'contracts.json'):
        retain(name, CONTRACTS / name)
    retain('audit_startup.py', REPO / 'tools/spx/boot-diagnostics/video-startup-20261003/audit_startup.py')
    retain('actual-startup-review.json', X / 'startup-review/report.json')
    retain('actual-startup-kernel.log', X / 'video-startup/kernel.stdout')
    rows = read(X / 'assembly/source-files.json')
    for name in ('hfi_venus.c', 'hfi_venus_io.h', 'core.c'):
        path = REPO / 'drivers/media/platform/qcom/venus' / name
        assert sha(path) == rows[str(path.relative_to(REPO))]['sha256']
        retain('linux-' + name, path)

    image = load(OUT / 'audit_pep_loader.py', 'vendor_pe').Image((OUT / 'oem-00040.sys').read_bytes())
    startup = load(OUT / 'audit_startup.py', 'vendor_startup')
    assert sha(OUT / 'oem-00040.sys') == startup.MINIPORT_SHA
    ranges, listing, pins = startup.instructions(image)
    iris = load(OUT / 'audit_contracts.py', 'vendor_contracts')
    iris_ranges, tables, iris_listing = iris.contracts(image)
    (OUT / 'vendor-startup-disassembly.txt').write_text('\n'.join(listing) + '\n')
    (OUT / 'vendor-uc-disassembly.txt').write_text('\n'.join(iris_listing) + '\n')

    # Pin the complete local value chain, including normalization and dispatch.
    selected = [(0x33cce8, 0x33cd10), (0x33ce08, 0x33ce20),
                (0x34a8b0, 0x34a93c), (0x34abd8, 0x34abe8),
                (0x34b26c, 0x34b278), (0x358400, 0x358478),
                (0x358568, 0x3585a0)]
    decoded = {}
    gnu_outputs = []
    for start, end in selected:
        raw = image.read(start, end - start)
        path = OUT / (hex(start) + '.bin')
        path.write_bytes(raw)
        for i in Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(raw, image.base + start):
            decoded[i.address - image.base] = (i.mnemonic, i.op_str)
        gnu_outputs.append(run('gnu-' + hex(start),
            ['objdump', '-D', '-b', 'binary', '-m', 'aarch64',
             '--adjust-vma=' + hex(image.base + start), str(path)]))
    extra = {
        0x33ccfc: ('mov', 'x10, #0x606c'),
        0x33cd00: ('add', 'x9, x8, #0xe0, lsl #12'),
        0x33cd04: ('ldr', 'w9, [x9]'),
        0x33cd08: ('str', 'w9, [x21, x10]'),
        0x33ce08: ('mov', 'x9, #0x606c'),
        0x33ce0c: ('ldrh', 'w4, [x21, x9]'),
        0x33ce14: ('strh', 'wzr, [x21, x9]'),
        0x34a8d0: ('mov', 'x9, #0x606c'),
        0x34a8d8: ('add', 'x13, x19, x9'),
        0x34a934: ('ldr', 'w12, [x13]'),
        0x34abe0: ('b.hi', '#0x14034b26c'),
        0x34b26c: ('mov', 'w8, #0x50100000'),
        0x34b270: ('cmp', 'w12, w8'),
        0x34b274: ('b.eq', '#0x14034b350'),
        0x35840c: ('mov', 'w12, #0x1000000'),
        0x35843c: ('ldp', 'w8, w9, [x8, #0x24]'),
        0x358450: ('sub', 'w19, w10, w12'),
        0x358474: ('blr', 'x20'),
        0x358568: ('ldr', 'w10, [x22, #0xd0]'),
        0x35856c: ('ldr', 'w8, [x22, #0x12c]'),
        0x35857c: ('add', 'w11, w8, w10'),
        0x358588: ('str', 'w11, [x22, #0x194]'),
        0x358590: ('add', 'x20, x8, w10, uxtw'),
        0x358598: ('str', 'x20, [x22, #0x198]'),
    }
    for at, value in extra.items():
        assert decoded[at] == value, (hex(at), decoded.get(at), value)
    gnu = '\n'.join(gnu_outputs)
    for at, (mnemonic, operands) in extra.items():
        match = re.search(r'^\s*' + format(image.base + at, 'x') + r':\s+[0-9a-f]{8}\s+(\S+)\s+(.+)$', gnu, re.M)
        assert match and match[1] == mnemonic, (hex(at), mnemonic)
        # GNU spells branch target addresses without Capstone's #0x prefix.
        def normalize(s):
            s = s.split('//', 1)[0]
            s = re.sub(r'#(-?(?:0x[0-9a-f]+|\d+))',
                       lambda m: '#' + hex(int(m[1], 0)), s)
            return re.sub(r'\s+', '', s)
        left, right = normalize(match[2]), normalize(operands)
        if mnemonic.startswith('b.'):
            left, right = int(left, 16), int(right.removeprefix('#'), 0)
        assert left == right, (hex(at), left, right)

    source = (OUT / 'linux-hfi_venus.c').read_text()
    header = (OUT / 'linux-hfi_venus_io.h').read_text()
    definitions = []
    for name in ('IFACEQ_NUM', 'IFACEQ_MAX_PKT_SIZE', 'IFACEQ_MAX_BUF_COUNT',
                 'IFACEQ_MAX_PARALLEL_CLNTS', 'IFACEQ_TABLE_SIZE', 'IFACEQ_QUEUE_SIZE',
                 'QDSS_SIZE', 'SFR_SIZE', 'QUEUE_SIZE', 'ALIGNED_QDSS_SIZE',
                 'ALIGNED_SFR_SIZE', 'ALIGNED_QUEUE_SIZE', 'SHARED_QSIZE'):
        lines = source.splitlines()
        starts = [n for n, line in enumerate(lines)
                  if re.match(r'^#define\s+' + name + r'\b', line)]
        assert len(starts) == 1
        start = end = starts[0]
        while lines[end].endswith('\\'):
            end += 1
        definitions.append('\n'.join(lines[start:end + 1]))
    structs = [re.search(r'struct ' + name + r' \{.*?\n\};', source, re.S)[0]
               for name in ('hfi_queue_table_header', 'hfi_queue_header')]
    versions = re.findall(r'^#define WRAPPER_HW_VERSION[^\n]+', header, re.M)
    observed = read(OUT / 'actual-startup-review.json')['venus_startup']
    b = observed['buffer_observations'][0]
    p = observed['poll_observations'][0]
    assert observed['line_count'] == 5 and p['hardware_version'] == 0x5010002f
    body = '\n'.join(['#include <stdint.h>', '#include <stdio.h>', '#include <assert.h>',
        'typedef uint32_t u32;', '#define SZ_4K 4096U', '#define SZ_1M 1048576U',
        '#define ALIGN(x,a) (((x)+(a)-1)&~((a)-1))'] + structs + definitions + versions)
    body += f'''\nint main(void) {{
    const uint64_t q={b['queue_dma']}ULL, s={b['sfr_dma']}ULL;
    const uint32_t v={p['hardware_version']}U;
    assert(ALIGNED_QUEUE_SIZE == {b['queue_bytes']}U);
    assert(SHARED_QSIZE == {b['uc_bytes']}U);
    assert(ALIGNED_SFR_SIZE == {b['sfr_bytes']}U);
    assert((v & WRAPPER_HW_VERSION_MAJOR_VERSION_MASK) >> WRAPPER_HW_VERSION_MAJOR_VERSION_SHIFT == 5);
    assert((v & WRAPPER_HW_VERSION_MINOR_VERSION_MASK) >> WRAPPER_HW_VERSION_MINOR_VERSION_SHIFT == 16);
    assert((v & WRAPPER_HW_VERSION_STEP_VERSION_MASK) == 47);
    assert(q + ALIGNED_QUEUE_SIZE == 0xbfe59000ULL);
    assert(q + SHARED_QSIZE == 0xbff00000ULL);
    assert(s + ALIGNED_SFR_SIZE == q && s < q);
    assert(SHARED_QSIZE - ALIGNED_QUEUE_SIZE == 0xa7000U);
    printf("queue_end=%llx uc_end=%llx sfr_end=%llx tail=%x minor=%x\\n",
        (unsigned long long)(q+ALIGNED_QUEUE_SIZE), (unsigned long long)(q+SHARED_QSIZE),
        (unsigned long long)(s+ALIGNED_SFR_SIZE), (unsigned)(SHARED_QSIZE-ALIGNED_QUEUE_SIZE),
        (v & WRAPPER_HW_VERSION_MINOR_VERSION_MASK) >> WRAPPER_HW_VERSION_MINOR_VERSION_SHIFT);
}}\n'''
    (OUT / 'actual-bf-geometry.c').write_text(body)
    run('compile', ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', str(OUT / 'actual-bf-geometry.c'), '-o', str(OUT / 'geometry')])
    native = run('native', [str(OUT / 'geometry')])
    assert 'queue_end=bfe59000 uc_end=bff00000 sfr_end=bfc00000 tail=a7000 minor=10' in native
    core = (OUT / 'linux-core.c').read_text().split('static const struct venus_resources sc8180x_res = {', 1)[1].split('\n};', 1)[0]
    assert '.hfi_version = HFI_VERSION_4XX' in core and '.vpu_version = VPU_VERSION_IRIS1' in core
    assert '.dma_mask = 0xc0000000 - 1' in core
    assert 'venus_alloc(hdev, &desc, ALIGNED_QUEUE_SIZE)' in source
    assert 'venus_alloc(hdev, &desc, ALIGNED_SFR_SIZE)' in source
    report = dict(inputs=inputs, actual_boot_id=read(OUT / 'actual-startup-review.json')['boot_id'],
        retained_instruction_pins_redecoded=len(pins)+len(iris.PINS), extra_pins=len(extra),
        extra_pins_independently_gnu_compared=len(extra), normalized_observed_version=hex(p['hardware_version'] & 0xffff0000),
        retained_dispatch_constant='0x50100000', linux_version_fields=dict(major=5, minor=16, step=47),
        actual_queue=dict(start=hex(b['queue_dma']), end_exclusive='0xbfe59000'),
        actual_declared_uc=dict(start=hex(b['queue_dma']), end_exclusive='0xbff00000', bytes=b['uc_bytes']),
        actual_sfr=dict(start=hex(b['sfr_dma']), end_exclusive='0xbfc00000', bytes=b['sfr_bytes']),
        actual_sfr_outside_declared_uc=True, declared_tail_beyond_queue_bytes=0xa7000,
        queue_fully_inside_declared_uc=True, vendor_sfr_device_formula='queue_device_base + queue_data_bytes',
        vendor_sfr_cpu_formula='queue_cpu_base + queue_data_bytes',
        retained_nonsecure_start=tables['0x1b56b0'][0][5], retained_nonsecure_length=tables['0x1b56b0'][0][6],
        retained_uc_iova='0xdf000000', retained_uc_bytes=0x1000000,
        linux_macros_extracted_exact_bf_source=True, native_geometry_sanitizers_passed=True,
        hardware_operations=0, device_translation_observed=False, firmware_execution_proven=False,
        root_cause_proven=False, linux_uc_policy_requirement_proven=False, hardware_acceptance_closed=False,
        limits=['Retained instructions and tables are static evidence, not observed Windows execution.',
                'The declared UC tail is not proven mapped by these allocation records.',
                'An SFR outside UC is an observed geometry difference, not proof that firmware requires containment.',
                'Protocol HFI_VERSION_4XX is distinct from the hardware version; no mismatch follows.',
                'UC is a device address window, distinct from the physical PAS firmware reservation.'])
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (OUT / 'sha256.json').write_text(json.dumps(files(OUT), indent=2) + '\n')
    sealed(OUT)
    os.sync()
    print(json.dumps(report | {'manifest_sha256': sha(OUT / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
