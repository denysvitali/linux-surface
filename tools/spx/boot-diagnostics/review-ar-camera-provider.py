#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash actual AR provider evidence and independently compare raw PMIC records to AP."""
import hashlib
import json
import os
from pathlib import Path
import re

BASE = Path('/var/lib/spx-boot-diagnostics/attempts')
X = BASE / '20261003ar'
PROVIDER = '/soc@0/spmi@c440000/pmic@1/regulators'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(records):
    values = {}
    for record in records:
        match = re.fullmatch(r'([0-9a-f]{4}): ([0-9a-f]{2}|XX)\n', record['raw'])
        assert match and int(match[1], 16) == record['address']
        address = int(match[1], 16)
        assert address not in values and record['file_offset'] == address * 9
        values[address] = None if match[2] == 'XX' else int(match[2], 16)
    return values


def main():
    assert os.geteuid() == 0 and not (X / 'camera-provider-review.json').exists()
    a = json.loads((X / 'attempt.json').read_text())
    assert a['release'] == os.uname().release
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid != a['preboot_id']
    out = X / 'camera-provider-result'
    expected = json.loads((out / 'sha256.json').read_text())
    actual = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    assert actual == expected | {'sha256.json': sha(out / 'sha256.json')}
    r = json.loads((out / 'report.json').read_text())
    assert sha(out / 'ar-camera-provider.py') == a['runtime_sha256'][
        '/usr/local/lib/spx-boot-diagnostics/ar-camera-provider.py']
    before, after = r['identity_before'], r['identity_after']
    assert before == after and before['boot_id'] == bid and before['taint'] == '0'
    assert before['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261003ar/vmlinuz'] + a['cmdline'].split()
    assert before['release'] == a['release']
    previous = BASE / '20261002ap/camera-pmic-metadata-20261003'
    assert sha(previous / 'sha256.json') == '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
    for name, digest in json.loads((previous / 'sha256.json').read_text()).items():
        assert sha(previous / name) == digest, name
    old = decode(json.loads((previous / 'result.json').read_text())['reads'])
    now = decode(r['pmic_reads'])
    assert set(now) <= set(old) and len(now) <= 21
    controls_match = len(now) == 21 and now == old
    checks = {}
    rails = {'spx-camera-dvdd': 0x4000, 'spx-camera-dovdd': 0x4d00, 'spx-camera-avdd': 0x5000}
    for name, base in rails.items():
        fields = r['providers'].get(name, {})
        voltage = (old[base + 0x40] | old[base + 0x41] << 8) * 1000
        checks[name] = (fields.get('name') == name and fields.get('state') == 'disabled' and
            fields.get('num_users') == '0' and fields.get('provider_driver') == 'qcom-spmi-regulator' and
            fields.get('provider_of_node', '').endswith(PROVIDER) and
            all(fields.get(field) == str(voltage) for field in ('microvolts', 'min_microvolts', 'max_microvolts')))
    passed = set(r['providers']) == set(rails) and all(checks.values()) and controls_match
    assert r['provider_registration_verified'] == passed
    report = {'attempt': a['attempt'], 'boot_id': bid, 'release': a['release'],
              'provider_registration_verified': passed, 'provider_checks': checks,
              'raw_pmic_reads_verified': len(now), 'pmic_controls_exact_ap': controls_match,
              'result_manifest_sha256': sha(out / 'sha256.json'),
              'reference_metadata_manifest_sha256': sha(previous / 'sha256.json'),
              'files_verified': len(expected), 'failure': r.get('failure'),
              'camera_functional_acceptance': False,
              'limits': ['No consumer enable, camera probe or capture tested.',
                         'Identical sampled controls do not prove absence of transient writes or firmware arbitration.']}
    os.umask(0o077)
    with (X / 'camera-provider-review.json').open('x') as file:
        file.write(json.dumps(report, indent=2) + '\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
