#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Static vendor power/indicator inventory; no binary execution or hardware access."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

OUT = Path(sys.argv[1])
assert not OUT.exists()
OUT.mkdir(mode=0o700)
ROOT = Path('/home/dvitali/Documents/drivers/FileRepository')
DSDT = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
expected = {
    'qccamplatform8180.sys': '88172ff32ddd3b004dfcd0152eb32cfd17971f7860e4d8eccad0b917e016165e',
    'qccamplatform8180.inf': 'f27ed8f982ce0617c891cedf891f8e949eb1779fdc1ab30cf33cb4ae1e9be723',
    'qccammipicsi8180.sys': '39e299af8ada6d80778f510c363085f49c5a06d94d418ce98ea87065c806a306',
    'qccammipicsi8180.inf': '821f1172fe7ab910e45bea489d059744bb17f4689f55612d520881fbd8a8e40e',
}
inputs = {}
metadata = {}
for pattern in ('qccamplatform8180.inf_*', 'qccammipicsi8180.inf_*'):
    matches = list(ROOT.glob(pattern)); assert len(matches) == 1
    for p in sorted(matches[0].iterdir()):
        if p.name not in expected: continue
        assert sha(p) == expected[p.name]
        inputs[p.name] = {'path': str(p), 'sha256': sha(p)}
        shutil.copyfile(p, OUT / p.name)
        if p.suffix != '.sys': continue
        b = p.read_bytes()
        e = struct.unpack_from('<I', b, 0x3c)[0]
        assert b[:2] == b'MZ' and b[e:e+4] == b'PE\0\0'
        assert struct.unpack_from('<H', b, e+4)[0] == 0xaa64
        count = struct.unpack_from('<H', b, e+6)[0]
        optional = struct.unpack_from('<H', b, e+20)[0]
        base = struct.unpack_from('<Q', b, e+24+24)[0]
        sections = []
        for i in range(count):
            at = e+24+optional+i*40
            name = b[at:at+8].split(b'\0')[0].decode()
            vsz, rva, size, raw = struct.unpack_from('<IIII', b, at+8)
            sections.append({'name': name, 'va': base+rva, 'raw': raw, 'size': size})
        strings = []
        for m in re.finditer(rb'[\x20-\x7e]{5,}', b):
            if not re.search(rb'(?i)vdda|regulat|volt|vreg|pmic|supply|rail|power|vdd|fstate|pstate|privacy', m.group()): continue
            matches = [s for s in sections if s['raw'] <= m.start() < s['raw']+s['size']]
            strings.append({'offset': m.start(), 'va': matches[0]['va']+m.start()-matches[0]['raw'] if matches else None,
                            'string': m.group().decode()})
        imports = json.loads(subprocess.check_output(['rabin2', '-ij', str(p)], text=True, timeout=30))
        info = {'image_base': base, 'sections': sections, 'strings': strings,
                'import_count': len(imports['imports'])}
        (OUT / (p.stem+'-strings.json')).write_text(json.dumps(info, indent=2)+'\n')
        (OUT / (p.stem+'-imports.json')).write_text(json.dumps(imports, indent=2)+'\n')
        metadata[p.stem] = info
        if p.stem == 'qccamplatform8180':
            md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
            start, end = 0x140001df0, 0x140002118
            text = next(s for s in sections if s['name'] == '.text')
            raw = text['raw'] + start-text['va']
            insns = list(md.disasm(b[raw:raw+end-start], start))
            assert len(insns) == (end-start)//4
            listing = '\n'.join(f'{i.address:#x}: {i.mnemonic} {i.op_str}' for i in insns)+'\n'
            assert any(i.address == 0x140002084 and i.mnemonic == 'add' and '0x988' in i.op_str for i in insns)
            assert any(i.address == 0x1400020a4 and i.mnemonic == 'add' and '0x9a8' in i.op_str for i in insns)
            (OUT / 'privacy-indicator-function.txt').write_text(listing)
            led_strings = [s for s in strings if s['string'].startswith(('Privacy LED -- PMIC', 'Privacy LED -- PState'))]
            assert len(led_strings) == 2
            assert [s['va'] for s in led_strings] == [0x140010988, 0x1400109a8]
assert len(inputs) == 4
assert sha(DSDT) == 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
lines = DSDT.read_text().splitlines()
(OUT / 'camp-methods.dsl.txt').write_text('\n'.join(lines[100042:100528])+'\n')
inputs['firmware-dsdt.dsl'] = {'path': str(DSDT), 'sha256': sha(DSDT), 'retained_lines': [100043,100528]}
shutil.copyfile(Path(__file__).resolve(), OUT / 'audit_vendor.py')
(OUT / 'inputs.json').write_text(json.dumps(inputs, indent=2)+'\n')
result = {
    'scope': 'Static vendor C01/C05 power and privacy-indicator evidence after AS passed',
    'vendor_files_verified': 4,
    'platform_privacy_function_va': 0x140001df0,
    'privacy_string_references_verified': [0x140002084, 0x1400020a4],
    'camp_cam_prld_state_set': {'index': 11, 'type': 2, 'values': [0,1], 'dsl_line': 100514},
    'analog_supply_mapping_established': False,
    'privacy_indicator_wiring_established': False,
    'hardware_actions': 0,
    'limits': [
        'Filtered ASCII strings and PE imports are bounded inventory, not a complete call-graph or absence proof.',
        'PMIC and PState diagnostic strings occur in a privacy-indicator dispatch function; they are not analog rail identifiers.',
        'PRLD six-entry tuples and action selector meanings remain to be decoded before selecting GPIO/PMIC/LED wiring.',
        'Firmware PState values and static disassembly do not verify physical indicator operation or capture.',
        'No Windows binary was loaded/executed; no driver/config/DT/runtime changed.',
    ],
}
(OUT / 'result.json').write_text(json.dumps(result, indent=2)+'\n')
h = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}
(OUT / 'sha256.json').write_text(json.dumps(h, indent=2)+'\n')
assert all(sha(OUT / n) == v for n,v in h.items())
print(json.dumps({'files_verified':len(h),'manifest_sha256':sha(OUT/'sha256.json')},indent=2))
