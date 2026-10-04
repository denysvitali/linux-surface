#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify AZ's completed payloads after preserving the54-versus55 check failure."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ay_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261003az')
RELEASE = '7.3.0-rc2-spx-mainline-20261003az+'
BOOT = '57b50440-3c7b-4626-bcc8-b2f065b697f6'


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not (STAGE / 'build-verification.json').exists()
    a = g.load()
    assert not g.recovery(a).get('next_entry', '')
    built = json.loads((STAGE / 'build-complete.json').read_text())
    assert built['release'] == RELEASE and built['modules'] == 202
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    modules = STAGE / 'module-root/lib/modules' / RELEASE
    manifest = json.loads((STAGE / 'module-sha256.json').read_text())
    assert len(manifest) == 217 and g.files(modules) == manifest
    vermagic = json.loads((STAGE / 'module-vermagic.json').read_text())
    assert len(vermagic) == 202
    for name, value in vermagic.items():
        assert value.split()[0] == RELEASE
        assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(modules / name)], text=True).strip() == value
    assert not (STAGE / 'depmod.log').read_text().strip()
    alias = json.loads((STAGE / 'videocc-alias-resolution.json').read_text())
    resolved = subprocess.check_output(['modprobe', '--resolve-alias', '-d', str(STAGE / 'module-root'),
        '-S', RELEASE, alias['modalias']], text=True).splitlines()
    assert resolved == alias['modules'] == ['videocc_sm8150']
    extract = STAGE / 'initramfs-extracted'
    parent = g.X / 'build/initramfs-extracted'

    def embedded(root, release):
        prefix = 'usr/lib/modules/' + release + '/'
        rows = {}
        for path in root.rglob('*.ko'):
            name = str(path.relative_to(root))
            assert name.startswith(prefix)
            rows[name[len(prefix):]] = g.sha(path)
        return rows

    current, previous = embedded(extract, RELEASE), embedded(parent, a['release'])
    assert len(current) == 55 and len(previous) == 54
    added = set(current) - set(previous)
    assert added == {'kernel/drivers/clk/qcom/videocc-sm8150.ko'} and not set(previous) - set(current)
    for name, digest in current.items():
        assert manifest[name] == digest, name
    assert g.sha(extract / 'usr/local/lib/spx-boot-diagnostics/initrd-log.sh') == g.sha(STAGE / 'logging/initrd-log.sh')
    dt = STAGE / 'dtb-build'
    assert g.files(dt) == g.files(g.X / 'build/dtb-build')
    failure = STAGE / 'assembly-failure-v1'
    failure.mkdir(mode=0o700)
    for path in (STAGE / 'assemble-ay.py', Path('/var/tmp/spx-az-assembly.stdout'),
                 Path('/var/tmp/spx-az-assembly.stderr')):
        shutil.copy2(path, failure / path.name)
    (failure / 'observed.json').write_text(json.dumps(dict(
        expected_embedded_modules=54, actual_embedded_modules=55,
        added_embedded_modules=sorted(added), removed_embedded_modules=[],
        reason='kms includes the new clock provider; original expected count was stale',
        original_private_helper_filename='assemble-ay.py'), indent=2) + '\n')
    (failure / 'sha256.json').write_text(json.dumps(g.files(failure), indent=2) + '\n')
    shutil.copy2(__file__, STAGE / Path(__file__).name)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), release=RELEASE,
                  modules=202, module_tree_files=217, embedded_modules=55,
                  embedded_module_payloads_exact=True, private_logger_exact=True,
                  added_embedded_modules=sorted(added), videocc_provider_module_verified=True,
                  actual_of_fallback_alias_resolves=True, boot_dtb_exact_parent_ay=True,
                  prior_boot_tree_property_values_exact=True,
                  assembly_failure_preserved=True, boot_selected=False, deployed=False,
                  artifacts={name: g.sha(STAGE / name) for name in (
                      'vmlinuz', 'initramfs.img', 'dtb-build/spx.dtb', 'artifacts/.config')})
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    with (STAGE / 'build-verification.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
