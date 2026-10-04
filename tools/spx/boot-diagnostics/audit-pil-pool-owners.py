#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Correlate original SQ2 ACPI owners and PIL PGCM registry with BD's NOMAP pool."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
SRC = Path(__file__).resolve().parent
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bd_boot_guard as g


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    out = g.X / 'offline-pil-pool-owners'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    dsdt = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')
    inf = Path('/home/dvitali/Documents/drivers/FileRepository/qcpil8180.inf_arm64_33f5ea4e4b666c6f/qcpil8180.inf')
    assert g.sha(dsdt) == 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
    helper = SRC / 'video-integration-20261003/audit_video.py'
    shutil.copy2(helper, out / 'asl_reader.py')
    spec = importlib.util.spec_from_file_location('pil_owner_asl_reader', out / 'asl_reader.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    shutil.copy2(dsdt, out / dsdt.name)
    shutil.copy2(inf, out / inf.name)
    source = reader.clean(dsdt.read_text())
    headers = {m.end()-1: m.group(1) + '(' + m.group(2).strip() + ')' for m in
        re.finditer(r'\b(Device|Scope)\s*\(([^()\n]+)\)\s*\{', source)}
    tokens = list(re.finditer(r'"[^"\n]*"|[{}]', source))
    stack, scope_ranges = [], []
    for token in tokens:
        if token.group() == '{':
            stack.append((token.start(), headers.get(token.start())))
        elif token.group() == '}':
            start, name = stack.pop()
            if name:
                scope_ranges.append((start, token.end(), name))
    assert not stack
    claims = []
    for match in re.finditer(r'Memory32Fixed\s*\(\s*(ReadWrite|ReadOnly)\s*,\s*'
                            r'(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,?\s*\)', source):
        base, size = int(match[2], 16), int(match[3], 16)
        if not (base < 0x9ab00000 and base+size > 0x8b700000):
            continue
        owners = [name for start, end, name in sorted(scope_ranges)
                  if start < match.start() < end]
        claims.append(dict(base=base, bytes=size, exclusive_end=base+size,
                           access=match[1], scopes=owners, source_offset=match.start()))
    expected = {0x8b700000: (0x500000, 'Device(VFE0)'),
                0x8bc00000: (0x180000, 'Device(QWLN)'),
                0x9a500000: (0x600000, 'Device(QSM)')}
    for base, (size, owner) in expected.items():
        found = [row for row in claims if row['base'] == base and row['bytes'] == size]
        assert len(found) == 1 and owner in found[0]['scopes'], (hex(base), found)
        line = dsdt.read_text().splitlines()
        at = source[:found[0]['source_offset']].count('\n')
        (out / ('acpi-' + hex(base) + '.txt')).write_text('\n'.join(line[max(0, at-8):at+10]) + '\n')
    raw = inf.read_bytes()
    text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8-sig')
    (out / 'qcpil8180-decoded.inf').write_text(text)
    section = re.search(r'^\[SubsysReg_8180\]\s*\n(.*?)(?=^\[|\Z)', text, re.M | re.S)[1]
    def field(name):
        values = re.findall(r'^HKR,PGCM,' + name + r',%REG_DWORD%,(0x[0-9a-f]+)\s*$', section, re.M | re.I)
        assert len(values) == 1
        return int(values[0], 16)
    base, size = field('BaseAddress'), field('Size')
    assert base == 0x8bd80000 and size == 0xe780000 and base+size == 0x9a500000
    actual = g.X / 'actual-memory-aperture'
    assert g.sha(actual / 'sha256.json') == 'bdef166c9bc560eaa30a8eef390d81df9d5b7770f8e362752653c392beeab0fc'
    assert g.files(actual) == json.loads((actual / 'sha256.json').read_text()) | {'sha256.json': g.sha(actual / 'sha256.json')}
    (out / 'actual-memory-report.json').write_bytes((actual / 'report.json').read_bytes())
    (out / 'actual-dt-reservations.json').write_bytes((actual / 'explicit-dt-reservations.json').read_bytes())
    report = dict(utc=datetime.now(timezone.utc).isoformat(), retained_acpi_sha256=g.sha(dsdt),
        retained_pil_inf_sha256=g.sha(inf), resource_claims=claims,
        declared_pgcm=dict(base=hex(base), bytes=size, exclusive_end=hex(base+size)),
        pgcm_excludes_camera_wlan_qsm_claims=True,
        actual_nomap_range_broader_than_declared_pgcm=True,
        gap_ownership_in_pgcm_complete=False, pgcm_initialization_execution_traced=False,
        current_windows_runtime_observed=False, fixed_video_carveout_chosen=False,
        compiled_candidate_changed=False, hardware_acceptance_closed=False,
        next_action='Trace the retained PIL PGCM initialization/allocation path and its treatment of reserved pages.',
        limits=['Retained ACPI declarations do not prove current hardware accesses.',
                'PGCM registry bounds establish a narrower declared pool, not a runtime allocation or free gap.',
                'Camera/QSM physical claims remain protected; no ordinary RAM release or physical access occurs.'])
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    assert g.files(out) == json.loads((out / 'sha256.json').read_text()) | {'sha256.json': g.sha(out / 'sha256.json')}
    os.sync()
    print(json.dumps(report | dict(manifest_sha256=g.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
