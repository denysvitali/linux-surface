#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded read-only camera LDO metadata through fixed-record regmap pread."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parents[4]
BOOT = '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'
RELEASE = '7.3.0-rc2-spx-mainline-20261001am+'
REGMAP = Path('/sys/kernel/debug/regmap/0-01')
# Identity and control offsets already read by qcom_spmi-regulator.c.
OFFSETS = {'dig_major': 0x01, 'type': 0x04, 'subtype': 0x05,
           'vset_lsb': 0x40, 'vset_msb': 0x41, 'mode': 0x45, 'enable': 0x46}
RAILS = {'ldo1_a': 0x4000, 'ldo14_a': 0x4d00, 'ldo17_a': 0x5000}
WIDTH = 9  # Four address digits, ': ', two value digits and newline.


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity():
    return {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'release': os.uname().release,
            'taint': Path('/proc/sys/kernel/tainted').read_text().strip(),
            'touch': Path('/sys/bus/spi/devices/spi0.0/ready').read_text().strip(),
            'uptime': Path('/proc/uptime').read_text().strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    assert os.geteuid() == 0
    before = identity()
    assert before['boot_id'] == BOOT and before['release'] == RELEASE
    assert before['taint'] == '0' and before['touch'] == 'ready'
    # The range file builds offset metadata without reading hardware registers.
    ranges = (REGMAP / 'range').read_text()
    assert ranges == '0-ffff\n', ranges
    assert (REGMAP / 'name').read_text() == 'pmic-spmi\n'
    env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'saved_entry=spx-known-good\n' in env and 'next_entry=\n' in env
    args.archive.mkdir(mode=0o700, parents=True, exist_ok=False)
    sources = args.archive / 'sources'
    sources.mkdir()
    for name in ('drivers/base/regmap/regmap-debugfs.c', 'drivers/mfd/qcom-spmi-pmic.c',
                 'drivers/regulator/qcom_spmi-regulator.c'):
        shutil.copy2(REPO / name, sources / Path(name).name)
    shutil.copy2(__file__, sources / 'read_pmic.py')
    result = {'identity_before': before, 'start_wall_time': time.time(),
              'map': str(REGMAP), 'ranges': ranges, 'grubenv': env,
              'record_width': WIDTH, 'reads': [], 'rails': {}, 'writes': 0,
              'success': False, 'limits': 'Configured voltage is decoded only after '
              'subtype/layout verification. No status/IRQ registers, writes, scans, '
              'module operations or power transitions.'}
    fd = os.open(REGMAP / 'registers', os.O_RDONLY | os.O_CLOEXEC)
    try:
        for name, base in RAILS.items():
            registers = {}
            for field, offset in OFFSETS.items():
                address = base + offset
                raw = os.pread(fd, WIDTH, address * WIDTH)
                record = {'rail': name, 'field': field, 'address': address,
                          'file_offset': address * WIDTH, 'count': WIDTH,
                          'raw': raw.decode('ascii', errors='strict')}
                result['reads'].append(record)
                match = re.fullmatch(r'([0-9a-f]{4}): ([0-9a-f]{2}|XX)\n', record['raw'])
                assert match and int(match[1], 16) == address, record
                if match[2] == 'XX':
                    raise RuntimeError(f'{name} {field} read failed: {record}')
                registers[field] = int(match[2], 16)
            result['rails'][name] = {'base': base, 'registers': registers}
        result['success'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        os.close(fd)
        result['identity_after'] = identity()
        result['end_wall_time'] = time.time()
        if any(result['identity_after'][key] != before[key]
               for key in ('boot_id', 'release', 'taint', 'touch')):
            result['success'] = False
            result['identity_changed'] = True
        (args.archive / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        files = {str(path.relative_to(args.archive)): sha(path)
                 for path in sorted(args.archive.rglob('*')) if path.is_file()}
        (args.archive / 'sha256.json').write_text(json.dumps(files, indent=2) + '\n')
        for path, digest in files.items():
            assert sha(args.archive / path) == digest
        os.sync()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
