#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract firmware touch power timing offline; never read live AML or MMIO."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('camera_audit', HERE / 'camera-power-20261003/audit_firmware.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def block(source, pattern):
    match = re.search(pattern, source)
    assert match, pattern
    brace = source.index('{', match.end())
    level, end = 1, brace + 1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end], match.start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dsl', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.dsl.read_bytes()
    source = raw.decode()
    clean = re.sub(r'/\*.*?\*/|//[^\n]*', lambda m: re.sub(r'[^\n]', ' ', m.group()), source, flags=re.S)
    device, start = block(clean, r'Device\s*\(GTCH\)')
    methods = {}
    for name in ('_PS0', '_PS3', '_RST'):
        text, offset = block(device, r'Method\s*\(' + name + r',')
        events = []
        for match in re.finditer(r'Sleep\s*\((0x[0-9A-Fa-f]+|\d+)\)|DWD2\s*=\s*(Zero|One|0x[0-9A-Fa-f]+)', text):
            number = match[1] or match[2]
            value = {'Zero': 0, 'One': 1}.get(number)
            if value is None:
                value = int(number, 0)
            events.append({'kind': 'sleep_ms' if match[1] else 'gpio54_io_assignment',
                           'value': value, 'line': source.count('\n', 0, start + offset + match.start()) + 1})
        methods[name] = {'line': source.count('\n', 0, start + offset) + 1,
                         'source': source[start + offset:start + offset + len(text)], 'events': events}
    assert [(e['kind'], e['value']) for e in methods['_PS0']['events']] == [
        ('sleep_ms', 300), ('gpio54_io_assignment', 2), ('sleep_ms', 150)]
    assert [(e['kind'], e['value']) for e in methods['_RST']['events']] == [
        ('gpio54_io_assignment', 0), ('sleep_ms', 300), ('gpio54_io_assignment', 2)]
    assert '0x03136000' in methods['_PS0']['source'] and '0x03136000' in methods['_RST']['source']
    tables = {name: audit.extract(source, name) for name in ('LPXC', 'LPXX')}
    for name, table in tables.items():
        assert list(table['devices']) == [r'\\_SB.GTCH'], name
    original = audit.extract(source)
    assert original['literal_packages_verified'] == 986
    report = {'source': str(args.dsl.resolve()), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'methods': methods, 'low_power_tables': tables,
              'camera_default_parser_regression_packages': 986,
              'selector': 'LPMX chooses LPXC when (SBFF & 1) == 0, otherwise LPXX',
              'selector_value_read': False,
              'sleep_unit_source': 'https://uefi.org/specs/ACPI/6.5/19_ASL_Reference.html#sleep-milliseconds-sleep',
              'limits': ['No live AML, NVS, MMIO, pin or rail access.',
                         'PEP DELAY package units and SBFF selection are not established.',
                         '_PS0 and _RST Sleep operands use ACPI-defined milliseconds.',
                         'These sequences do not prove the cause of an individual startup failure.']}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('source_sha256', 'selector', 'selector_value_read', 'limits')} |
                     {'methods': {name: value['events'] for name, value in methods.items()},
                      'table_packages': {name: value['literal_packages_verified'] for name, value in tables.items()}}, indent=2))


if __name__ == '__main__':
    main()
