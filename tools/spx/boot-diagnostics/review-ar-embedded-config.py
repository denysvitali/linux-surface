#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently extract actual AR Image/compressed-kernel config, without booting."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

X = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ar')
SOURCE = Path('/var/tmp/spx-mainline-trial-20261003ar/source')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    out = X / 'embedded-config-review'
    assert not out.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == '991a6fbd-2217-4f93-8185-287a223a13f6'
    records = json.loads((X / 'build/source-files.json').read_text())
    extractor = SOURCE / 'scripts/extract-ikconfig'
    assert sha(extractor) == records['scripts/extract-ikconfig']['sha256']
    expected = (X / 'build/artifacts/.config').read_bytes()
    checked = []
    for name in ('build/artifacts/arch/arm64/boot/Image', 'build/vmlinuz'):
        command = [str(extractor), str(X / name)]
        actual = subprocess.check_output(command, timeout=90)
        assert actual == expected, name
        checked.append({'payload': name, 'payload_sha256': sha(X / name),
                        'command': command, 'extracted_bytes': len(actual),
                        'extracted_config_sha256': hashlib.sha256(actual).hexdigest()})
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(extractor, out / 'extract-ikconfig')
    (out / 'report.json').write_text(json.dumps({'checked': checked,
        'both_actual_payload_configs_exact': True, 'extractor_source_record_verified': True,
        'config_sha256': sha(X / 'build/artifacts/.config'),
        'hardware_actions': []}, indent=2) + '\n')
    hashes = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    os.sync()
    print(json.dumps({'actual_payloads_checked': len(checked), 'config_sha256': sha(X / 'build/artifacts/.config'),
                      'manifest_sha256': sha(out / 'sha256.json')}))


if __name__ == '__main__':
    main()
