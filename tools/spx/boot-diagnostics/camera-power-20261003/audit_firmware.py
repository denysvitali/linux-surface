#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract literal camera PEP packages offline, retaining order and line numbers."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def extract(source, package_name='CPXC'):
    if not re.fullmatch(r'[A-Z_][A-Z0-9_]{3}', package_name):
        raise ValueError('invalid ACPI package name')
    # Keep positions intact when removing comments, so evidence refers to the DSL.
    clean = re.sub(r'/\*.*?\*/|//[^\n]*',
                   lambda m: re.sub(r'[^\n]', ' ', m.group()), source, flags=re.S)
    begin = clean.index('Package', clean.index(f'Name ({package_name},'))
    tokens = list(re.finditer(r'"[^"\n]*"|0x[0-9A-Fa-f]+|\d+|[A-Za-z_]+|[^\s]',
                              clean[begin:]))
    index = 0
    packages = 0

    def take(expected=None):
        nonlocal index
        token = tokens[index].group()
        index += 1
        if expected is not None and token != expected:
            raise ValueError(f'expected {expected}, got {token}')
        return token

    def value():
        nonlocal packages
        line = source.count('\n', 0, begin + tokens[index].start()) + 1
        token = take()
        if token == 'Package':
            take('(')
            size = value()['value']
            take(')')
            take('{')
            children = []
            while tokens[index].group() != '}':
                children.append(value())
                if tokens[index].group() == ',':
                    take(',')
            take('}')
            if len(children) != size:
                raise ValueError(f'line {line}: package count {size} != {len(children)}')
            packages += 1
            return {'line': line, 'value': children}
        if token.startswith('"'):
            literal = token[1:-1]
        elif token in ('Zero', 'One'):
            literal = int(token == 'One')
        elif re.fullmatch(r'0x[0-9A-Fa-f]+|\d+', token):
            literal = int(token, 0) if token.startswith('0x') else int(token)
        else:
            raise ValueError(f'line {line}: non-literal value {token}')
        return {'line': line, 'value': literal}

    root = value()

    def plain(node):
        val = node['value']
        return [plain(child) for child in val] if isinstance(val, list) else val

    def states(node, component=None):
        values = node['value']
        if not isinstance(values, list) or not values:
            return []
        tag = values[0]['value']
        if tag == 'COMPONENT':
            component = values[1]['value']
        if tag in ('DSTATE', 'FSTATE'):
            return [{'line': node['line'], 'kind': tag, 'state': values[1]['value'],
                     'component': component,
                     'actions': [{'line': action['line'], 'operation': plain(action)[0],
                                  'arguments': plain(action)[1]}
                                 for action in values[2:]]}]
        found = []
        for child in values:
            found.extend(states(child, component))
        return found

    devices = {}
    for device in root['value']:
        fields = device['value']
        if fields[0]['value'] != 'DEVICE':
            raise ValueError('unexpected CPXC entry')
        name = fields[1]['value']
        if name in devices:
            raise ValueError(f'duplicate device {name}')
        devices[name] = states(device)
    return {'literal_packages_verified': packages, 'devices': devices,
            'cpxc_start_line': root['line']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dsl', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.dsl.read_bytes()
    result = extract(raw.decode())
    result['source'] = str(args.dsl.resolve())
    result['source_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for name, states in result['devices'].items():
        for state in states:
            votes = [(a['arguments'][0], a['arguments'][2]) for a in state['actions']
                     if a['operation'] == 'PMICVREGVOTE']
            if state['kind'] == 'DSTATE' or votes:
                print(name, state['kind'], state['state'], votes)
    print('Verified literal packages:', result['literal_packages_verified'])


if __name__ == '__main__':
    main()
