#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehash the static PEP loader evidence and check native method-name encoding."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root, out = args.inventory, args.output
    out.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__), out / Path(__file__).name)
    manifest = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert Path(name).name == name and name not in manifest
        assert sha(root / name) == digest
        manifest[name] = digest
    assert set(manifest) == {p.name for p in root.iterdir()}-{'SHA256SUMS'}
    report = json.loads((root / 'pep-loader.json').read_text())
    for name, metadata in report['inputs'].items():
        assert manifest[name] == metadata['sha256']
    assert report['static_camera_loader_path_established']
    assert not report['actual_windows_execution_observed']
    assert not report['analog_supply_mapping_established']
    assert report['hardware_operations'] == 0
    assert report['instruction_checks'] == 76 and report['exception_records'] == 2442
    assert report['request_shape'] == dict(size=260, signature_ascii='AeiA',
                                         control_code=0x32c018, method_field_offset=4, path_bytes=256)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('pep_loader_review', root / 'audit_pep_loader.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    source = (root / 'dsdt.dsl').read_text()
    assert audit.method_list(source) == report['method_list']
    image = audit.Image((root / 'qcpep8180.sys').read_bytes())
    for selected in report['selected_ranges']:
        start, end = selected['start_rva'], selected['end_rva']
        assert image.functions[start] == end
        assert hashlib.sha256(image.read(start, end-start)).hexdigest() == selected['bytes_sha256']
    assert len(report['selected_ranges']) == 12
    assert len(report['opaque_words']) == 2 and not any(i['reachable'] for i in report['opaque_words'])
    for item in report['opaque_words']:
        assert image.read(item['rva'], 4).hex() == item['bytes']

    # Independently exercise the instruction-derived byte assembly with native
    # unsigned C and memcpy, then compare every list entry and the direct literal
    # STND request. This program only computes bytes in userspace memory.
    code = '''#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "ARM64 request model needs little endian");
int main(int argc, char **argv) {
    for (int i=1; i<argc; i++) {
        const unsigned char *entry=(const unsigned char *)argv[i];
        if (strlen(argv[i]) != 4) return 2;
        uint32_t word=((uint32_t)entry[0]<<24)|((uint32_t)entry[1]<<16)|
                      ((uint32_t)entry[2]<<8)|(uint32_t)entry[3];
        unsigned char buffer[260]={0};
        memcpy(buffer,"AeiA",4);
        memcpy(buffer+4,&word,4);
        if (buffer[8] != 0) return 3;
        printf("%s %08" PRIx32 " %.4s\\n",argv[i],word,buffer+4);
    }
    unsigned char direct[260]={0};
    memcpy(direct,"AeiA",4);
    memcpy(direct+4,"STND",4);
    printf("literal %.4s\\n",direct+4);
    return 0;
}
'''
    (out / 'method-name-model.c').write_text(code)
    compile_result = subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                     '-fsanitize=undefined', str(out / 'method-name-model.c'),
                                     '-o', str(out / 'method-name-model')],
                                    text=True, capture_output=True, timeout=30)
    (out / 'compile.stdout').write_text(compile_result.stdout)
    (out / 'compile.stderr').write_text(compile_result.stderr)
    assert compile_result.returncode == 0
    entries = report['method_list']['entries']
    model = subprocess.run([str(out / 'method-name-model'), *[e['entry'] for e in entries]],
                           text=True, capture_output=True, timeout=10)
    (out / 'model.stdout').write_text(model.stdout)
    (out / 'model.stderr').write_text(model.stderr)
    assert model.returncode == 0 and not model.stderr
    assert model.stdout.splitlines() == [f"{e['entry']} {e['assembled_u32']:08x} {e['request_name']}"
                                          for e in entries]+['literal STND']
    start = source.index('Name (STNX,')
    end = source.index('Method (CTPM,', start)
    section = source[start:end]
    fixtures = {
        'unreversed-c1md-entry': source[:start]+section.replace('"DM1C"', '"C1MD"', 1)+source[end:],
        'missing-c1md-entry': source[:start]+section.replace('"DM1C",', '', 1)+source[end:],
        'missing-stnd-return': source.replace('Return (STNX)', 'Return (STNY)', 1),
        'wrong-c1md-package': source.replace('Return (CPC1)', 'Return (CPC2)', 1),
    }
    rejected = []
    for name, fixture in fixtures.items():
        path = out / f'{name}.dsl'
        path.write_text(fixture)
        try:
            audit.method_list(fixture)
        except AssertionError as error:
            rejected.append(dict(name=name, fixture_sha256=sha(path), reason=str(error)))
        else:
            raise AssertionError('accepted wrong loader fixture: '+name)
    result = dict(inventory_manifest_sha256=sha(root / 'SHA256SUMS'),
                  inventory_files_verified=len(manifest), selected_ranges_verified=12,
                  native_method_list_encodings_verified=31, native_direct_literal_verified='STND',
                  native_undefined_behavior_sanitizer_clean=True,
                  rejected_fixtures=rejected, hardware_operations=0)
    (out / 'review.json').write_text(json.dumps(result, indent=2)+'\n')
    rows = ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file())
    (out / 'SHA256SUMS').write_text(rows)
    print(json.dumps(dict(files_verified=len(manifest), native_names=32,
                          fixtures_rejected=len(rejected), manifest_sha256=sha(out / 'SHA256SUMS'))))


if __name__ == '__main__':
    main()
