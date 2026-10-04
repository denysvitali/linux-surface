#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Collect AY's three camera providers without requesting voltage or enables."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

BASE = Path('/var/lib/spx-boot-diagnostics')
ATTEMPT = '20261003ay'
X = BASE / 'attempts' / ATTEMPT
RELEASE = '7.3.0-rc2-spx-mainline-20261003ay+'
PROVIDER = '/soc@0/spmi@c440000/pmic@1/regulators'
EXPECTED = {
    'spx-camera-dvdd': ('l1', 0x4000, 0x6b, 1200000),
    'spx-camera-dovdd': ('l14', 0x4d00, 0x72, 1800000),
    'spx-camera-avdd': ('l17', 0x5000, 0x7d, 2856000),
}
OFFSETS = {'dig_major': 0x01, 'type': 0x04, 'subtype': 0x05,
           'vset_lsb': 0x40, 'vset_msb': 0x41, 'mode': 0x45, 'enable': 0x46}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity():
    return {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'release': os.uname().release,
            'taint': Path('/proc/sys/kernel/tainted').read_text().strip(),
            'cmdline': Path('/proc/cmdline').read_text().strip()}


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    a = json.loads((X / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    before = identity()
    assert a['attempt'] == ATTEMPT and a['release'] == RELEASE == before['release']
    assert before['boot_id'] != a['preboot_id'] and before['taint'] == '0'
    assert before['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261003ay/vmlinuz'] + a['cmdline'].split()
    env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'saved_entry=spx-known-good\n' in env and 'next_entry=\n' in env
    out = X / 'camera-provider-result'
    assert not out.exists()
    out.mkdir(mode=0o700)
    result = {'identity_before': before, 'time': time.time(), 'grubenv': env,
              'providers': {}, 'pmic_reads': [], 'writes': 0,
              'provider_registration_verified': False,
              'limits': ['Collector requests no rail enable, voltage set, probe, capture or module operation; normal DT-enabled drivers may have run.',
                         'Matching before/after controls cannot exclude transient changes or firmware interference.',
                         'Registration is not camera functional acceptance.']}
    try:
        matches = {}
        for node in Path('/sys/class/regulator').glob('regulator.*'):
            name = (node / 'name').read_text().strip()
            if name in EXPECTED:
                assert name not in matches, 'Duplicate regulator name: ' + name
                matches[name] = node
        assert set(matches) == set(EXPECTED), 'Missing camera regulators: ' + str(set(EXPECTED) - set(matches))
        for name, node in matches.items():
            fields = {p: (node / p).read_text().strip() for p in (
                'name', 'microvolts', 'min_microvolts', 'max_microvolts', 'state', 'num_users')}
            resolved = node.resolve()
            fields['sysfs_path'] = str(resolved)
            # Regulator class devices have an intermediate "regulator/" directory.
            # The device symlink identifies the actual provider platform device.
            assert (node / 'device').is_symlink()
            device = (node / 'device').resolve()
            fields['provider_driver'] = (device / 'driver').resolve().name
            fields['provider_of_node'] = str((device / 'of_node').resolve())
            result['providers'][name] = fields
            voltage = EXPECTED[name][3]
            assert fields['provider_driver'] == 'qcom-spmi-regulator'
            assert fields['provider_of_node'].endswith(PROVIDER)
            assert fields['state'] == 'disabled' and fields['num_users'] == '0'
            assert all(fields[p] == str(voltage) for p in ('microvolts', 'min_microvolts', 'max_microvolts'))
        regmap = Path('/sys/kernel/debug/regmap/0-01')
        assert (regmap / 'range').read_text() == '0-ffff\n'
        assert (regmap / 'name').read_text() == 'pmic-spmi\n'
        fd = os.open(regmap / 'registers', os.O_RDONLY | os.O_CLOEXEC)
        try:
            for name, (_, base, subtype, voltage) in EXPECTED.items():
                values = {}
                for field, offset in OFFSETS.items():
                    address = base + offset
                    raw = os.pread(fd, 9, address * 9).decode('ascii')
                    result['pmic_reads'].append({'name': name, 'field': field,
                        'address': address, 'file_offset': address * 9, 'raw': raw})
                    match = re.fullmatch(r'([0-9a-f]{4}): ([0-9a-f]{2})\n', raw)
                    assert match and int(match[1], 16) == address, raw
                    values[field] = int(match[2], 16)
                result['providers'][name]['registers'] = values
                assert values['type'] == 4 and values['subtype'] == subtype and values['dig_major'] == 2
                assert (values['vset_lsb'] | values['vset_msb'] << 8) * 1000 == voltage
                assert values['enable'] == 0 and values['mode'] == 7
        finally:
            os.close(fd)
        result['provider_registration_verified'] = True
    except Exception as error:
        result['failure'] = repr(error)
    finally:
        result['identity_after'] = identity()
        if result['identity_after'] != before:
            result['provider_registration_verified'] = False
            result['identity_changed'] = True
        (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
        shutil.copy2(__file__, out / Path(__file__).name)
        (out / 'kernel.log').write_bytes(subprocess.check_output(
            ['journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager'], timeout=60))
        hashes = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
        (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
        for name, digest in hashes.items():
            assert sha(out / name) == digest
        os.sync()
    print(json.dumps({'provider_registration_verified': result['provider_registration_verified'],
                      'manifest_sha256': sha(out / 'sha256.json'),
                      'failure': result.get('failure')}))
    raise SystemExit(0 if result['provider_registration_verified'] else 1)


if __name__ == '__main__':
    main()
