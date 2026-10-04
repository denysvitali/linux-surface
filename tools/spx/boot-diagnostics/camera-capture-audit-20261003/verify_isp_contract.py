#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently review SQ2 receiver evidence and reject wrong register profiles.

Only read retained bytes, run offline parsers and evaluate native C macros.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(directory):
    expected = json.loads((directory / 'sha256.json').read_text())
    assert set(expected) == {p.name for p in directory.iterdir()
                             if p.is_file() and p.name != 'sha256.json'}
    assert all(sha(directory / name) == digest for name, digest in expected.items())
    return len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('contract', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)
    out = args.output
    inputs = {'inventory_manifest': sha(args.inventory / 'sha256.json'),
              'contract_manifest': sha(args.contract / 'sha256.json')}
    counts = [verify_manifest(args.inventory), verify_manifest(args.contract)]
    report = json.loads((args.contract / 'result.json').read_text())
    inventory = json.loads((args.inventory / 'isp-inventory.json').read_text())
    assert inventory['exception_record_count'] == 382
    assert not any(x['cfg_reachable'] for x in inventory['opaque_words'])
    assert sha(args.inventory / 'qccamisp8180.sys') == sha(args.contract / 'qccamisp8180.sys')
    for actual, archived in [('camss.c', 'profile.c'), ('camss-csid-gen2.c', 'csid.c'),
                             ('camss-vfe-17x.c', 'vfe.c')]:
        assert sha(args.inventory / actual) == sha(args.contract / archived)
    functions = inventory['functions']
    assert len(report['selected_ranges']) == 8
    code_ranges = []
    data = (args.contract / 'qccamisp8180.sys').read_bytes()
    base = inventory['image_base']
    for selected in report['selected_ranges']:
        start, end = selected['start_rva'], selected['end_rva']
        function = next(f for f in functions if f['start'] == base+start)
        assert function['end'] == base+end or (start, end, function['end']-base) == (
            0x16020, 0x16374, 0x1637c)
        section = next(s for s in inventory['sections'] if s['rva'] <= start and
                       end <= s['rva']+s['size'])
        raw = section['raw']+start-section['rva']
        assert hashlib.sha256(data[raw:raw+end-start]).hexdigest() == selected['bytes_sha256']
        code_ranges.append(dict(selected=selected, exception_function_end=function['end']))
    assert report['selected_instruction_contracts'] == 47
    assert report['linux_macro_values_verified'] == 69
    assert report['csid_branch_register_stores_verified'] == 66
    assert report['base_contract'] == {'csid_from_vfe': 16384, 'bus_from_vfe': 8192}
    assert not report['actual_hardware_revision_measured']
    assert not report['analog_supply_mapping_established'] and not report['hardware_operations']
    table = report['vfe_bus_client_jump_table']
    assert len(table['target_rvas']) == 19
    assert all(0x18f78 <= address < 0x192a8 for address in table['target_rvas'])
    assert table['target_rvas'][6:9] == [0x19168, 0x19178, 0x19188]
    fixture_root = out / 'negative-fixtures'
    fixture_root.mkdir()
    mutations = [
        ('csid-full-base', 'csid.c', '--csid-source', '? 0x200 : 0x300', '? 0x200 : 0x400'),
        ('csid-lite-base', 'csid.c', '--csid-source', '? 0x200 : 0x300', '? 0x100 : 0x300'),
        ('vfe-bus-status', 'vfe.c', '--vfe-source', '(0x205c +', '(0x105c +'),
        ('vfe-profile-480', 'profile.c', '--profile-source',
         '.hw_ops = &vfe_ops_170,', '.hw_ops = &vfe_ops_480,'),
    ]
    rejected = []
    for name, source_name, option, before, after in mutations:
        source = (args.contract / source_name).read_text()
        assert before in source
        changed = source.replace(before, after)
        fixture = fixture_root / (name+'.c')
        fixture.write_text(changed)
        command = [sys.executable, str(HERE / 'audit_isp_contract.py'),
                   str(fixture_root / (name+'-output')), option, str(fixture)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'AssertionError' in result.stderr
        assert not (fixture_root / (name+'-output/result.json')).exists()
        observed = dict(name=name, command=command, returncode=result.returncode,
                        stdout=result.stdout, stderr=result.stderr,
                        fixture_sha256=sha(fixture))
        (fixture_root / (name+'-result.json')).write_text(json.dumps(observed, indent=2)+'\n')
        rejected.append(observed)
    # Historical logs are retained observations. Their original boot UUID and
    # complete source/config provenance are absent from these standalone logs.
    historical = out / 'historical-observations'
    historical.mkdir()
    logs = {
        'v23-ov5693-real.stream.log': 'a4dd48a663fa3ffef23a50d06b7c3d3f19cdffede64128bfd0753bb4d7e86a25',
        'v22-iommu-a00-mask4e0.stream.log': '1da42f08b605284e1391eb40614f163ccae1fa8c9f069616d77b90fff939b6c5',
    }
    observations = []
    for name, digest in logs.items():
        path = Path('/var/log/spx-camera-archive') / name
        assert sha(path) == digest
        shutil.copyfile(path, historical / name)
        text = path.read_text()
        assert 'VFE:0 HW Version = 1.2.1' in text
        assert 'CSID:0 HW Version = 1.0.0' in text
        phy_logged = 'CSIPHY 3PH HW Version = 0x10000000' in text
        assert phy_logged == name.startswith('v23-')
        observations.append(dict(path=str(path), sha256=digest,
            phy_revision_logged='0x10000000' if phy_logged else None,
            vfe0_revision_logged='1.2.1',
            csid0_revision_logged='1.0.0', original_boot_uuid=None,
            final_candidate_acceptance=False))
    archive_manifest = Path('/var/log/spx-camera-archive/v23-multi-20260809/SHA256SUMS')
    assert sha(archive_manifest) == 'e7c3bb900154f61511bd98fa7a60cb668627677bffb7c231ab60ccbb8e524982'
    captures = {}
    for line in archive_manifest.read_text().splitlines():
        digest, name = line.split(None, 1)
        assert sha(Path(name)) == digest
        captures[name] = digest
    assert len(captures) == 9
    shutil.copyfile(archive_manifest, historical / 'capture-SHA256SUMS')
    (historical / 'observations.json').write_text(json.dumps(dict(logs=observations,
        old_capture_entries_rehashed=captures,
        limits=['Historical revision strings are not measurements on AX or a final candidate.',
                'Standalone stream logs lack full original boot/source/config provenance.',
                'Dummy regulators in historical logs do not establish analog rail ownership.']), indent=2)+'\n')
    shutil.copyfile(Path(__file__).resolve(), out / 'verify_isp_contract.py')
    tool_versions = {name: subprocess.check_output(command, text=True).splitlines()[0]
                     for name, command in {'gcc': ['gcc', '--version'],
                                           'python': [sys.executable, '--version']}.items()}
    import capstone
    tool_versions['capstone'] = capstone.__version__
    result = dict(input_manifests=inputs, input_files_verified=counts,
                  ranges_reviewed=code_ranges, register_macro_values=69,
                  byte_contracts=47, negative_profiles_rejected=rejected,
                  historical_log_observations=observations, capture_files_rehashed=9,
                  tool_versions=tool_versions, hardware_operations=0,
                  camera_capture_acceptance=False)
    (out / 'result.json').write_text(json.dumps(result, indent=2)+'\n')
    manifest = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'sha256.json').write_text(json.dumps(manifest, indent=2)+'\n')
    assert all(sha(out / name) == digest for name, digest in manifest.items())
    print(json.dumps(dict(output=str(out), files_verified=len(manifest),
                         negative_profiles_rejected=len(rejected),
                         manifest_sha256=sha(out / 'sha256.json'))))


if __name__ == '__main__':
    main()
