#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replay PEP clock bytes and compare independent native rate-selection models."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--preimage', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.inventory, args.output
    out.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__),out/Path(__file__).name)
    manifest = {}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ',1)
        assert Path(name).name == name and name not in manifest
        assert sha(root/name) == digest
        manifest[name] = digest
    assert set(manifest) == {p.name for p in root.iterdir()}-{'SHA256SUMS'}
    report = json.loads((root/'pep-clock.json').read_text())
    for name, value in report['inputs'].items():
        assert manifest[name] == value['sha256']
    import importlib.util
    import sys
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('review_clock',root/'audit_pep_clock.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    image_module = audit.module(root/'audit_pep_loader.py','review_clock_image')
    image = image_module.Image((root/'qcpep8180.sys').read_bytes())
    assert audit.clock_tables(image) == report['bsp']
    assert audit.conversion_tables(image) == report['conversions']
    assert audit.validate_linux((root/'camcc-sc8180x.c').read_text(),
                                (root/'camss.c').read_text()) == report['linux']
    assert report['instruction_checks'] == 85 and report['exception_records'] == 2442
    assert report['hardware_operations'] == 0 and not report['bsp']['live_bsp_observed']
    assert not report['bsp']['analog_supplier_established']
    assert len(report['selected_ranges']) == 13
    for row in report['selected_ranges']:
        start, end = row['start_rva'],row['end_rva']
        assert image.functions[start] == end
        assert hashlib.sha256(image.read(start,end-start)).hexdigest() == row['bytes_sha256']

    # Compile the actual Linux table lookup body alongside an independent,
    # unsigned C closest/ceiling/floor/exact model of the selected ARM64 branches.
    common = (root/'common.c').read_text()
    body = re.search(r'^const\nstruct freq_tbl \*qcom_find_freq\([^\n]+\)\n\{.*?^\}',
                     common,re.S | re.M)
    assert body is not None
    cases = []
    for label,rates in [('phy',[19200000,400000000]),('timer',[19200000,300000000])]:
        for request in (0,1,19200000,19200001,159600000,209600000,300000000,
                        400000000,400000001,4294967295):
            for mode in range(4):
                # Sorting by distance implements ties toward the lower rate,
                # independently of audit.choose's upper/lower branch structure.
                if request in rates:
                    answer = request
                elif mode == 0:
                    answer = min((r for r in rates if r>request),default=0)
                elif mode == 1:
                    answer = max((r for r in rates if r<request),default=0)
                elif mode == 2:
                    answer = min(rates,key=lambda r:(abs(r-request),r))
                else:
                    answer = 0
                assert (audit.choose(rates,request,mode) or 0) == answer
                linux_answer = next((r for r in rates if r>=request),rates[-1])
                cases.append(dict(label=label,rates=rates,request=request,mode=mode,
                                  expected=answer,linux_expected=linux_answer))
    for row in report['requests']:
        assert row['firmware_action'] == 8 and row['internal_action'] == 128
        assert row['firmware_mode'] == 3 and row['internal_mode'] == 2
        assert (row['static_selected_hz'],row['request_hz']) == (
            300000000 if 'phytimer' in row['name'] else 400000000,
            300000000 if row['package']=='CPC1' else 400000000)
        cases.append(dict(label=row['name'],rates=row['supported_hz'],request=row['request_hz'],
                          mode=2,expected=row['static_selected_hz'],linux_expected=row['static_selected_hz']))
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    initializers = ',\n'.join('{'+','.join(str(v)+'U' for v in
        (*r['rates'],r['request'],r['mode'],r['expected'],r['linux_expected']))+'}' for r in cases)
    code = '''#include <stdint.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
struct freq_tbl { unsigned long freq; };
'''+body.group()+'''
static uint32_t select_rate(uint32_t a, uint32_t b, uint32_t request, unsigned mode) {
    uint32_t rates[2]={a,b}, lower=0, upper=UINT32_MAX;
    int has_lower=0,has_upper=0;
    for (unsigned i=0;i<2;i++) {
        uint32_t r=rates[i];
        if (r==request) return r;
        if (r<request && (!has_lower || r>lower)) {lower=r;has_lower=1;}
        if (r>request && (!has_upper || r<upper)) {upper=r;has_upper=1;}
    }
    if (mode==0) return has_upper?upper:0;
    if (mode==1) return has_lower?lower:0;
    if (mode!=2) return 0;
    if (!has_lower) return has_upper?upper:0;
    if (!has_upper) return lower;
    return upper-request < request-lower ? upper:lower;
}
int main(void) {
    const uint32_t cases[][6]={
'''+initializers+'''
    };
    for (unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++) {
        const uint32_t *c=cases[i];
        struct freq_tbl f[]={{c[0]},{c[1]},{0}};
        uint32_t pep=select_rate(c[0],c[1],c[2],c[3]);
        uint32_t linux_rate=(uint32_t)qcom_find_freq(f,c[2])->freq;
        if (pep!=c[4] || linux_rate!=c[5]) return 2;
        printf("%u %" PRIu32 " %" PRIu32 "\\n",i,pep,linux_rate);
    }
    return 0;
}
'''
    source = out/'clock-selection-model.c'
    source.write_text(code)
    command = ['gcc','-std=c11','-Wall','-Wextra','-Werror',
               '-fsanitize=undefined',str(source),'-o',str(out/'clock-selection-model')]
    compiled = subprocess.run(command,text=True,capture_output=True,timeout=30)
    (out/'compile.stdout').write_text(compiled.stdout)
    (out/'compile.stderr').write_text(compiled.stderr)
    assert compiled.returncode == 0 and not compiled.stderr
    model = subprocess.run([str(out/'clock-selection-model')],text=True,capture_output=True,timeout=10)
    (out/'model.stdout').write_text(model.stdout)
    (out/'model.stderr').write_text(model.stderr)
    assert model.returncode == 0 and not model.stderr
    assert model.stdout.splitlines() == [f"{i} {r['expected']} {r['linux_expected']}" for i,r in enumerate(cases)]

    for name in ('camcc-sc8180x.c','camss.c'):
        shutil.copyfile(args.preimage/name,out/('before-'+name))
    assert sha(out/'before-camcc-sc8180x.c') == '7ff8df34e35e0dc707168cbe144da6e3b5050c2a0d78a13587f246aef727a3bb'
    assert sha(out/'before-camss.c') == 'fd4ce68da95af69d5c7d7f389a9aded0d618d0884585ee1a5ae3de780f49a2ac'
    rejected = []
    fixtures = [('old-phy-clock-table', 'camcc', (out/'before-camcc-sc8180x.c').read_text()),
                ('old-phy-requests', 'camss', (out/'before-camss.c').read_text())]
    camcc,camss = (root/'camcc-sc8180x.c').read_text(),(root/'camss.c').read_text()
    for name,kind,text in fixtures:
        p=out/(name+'.c');p.write_text(text)
        try:
            audit.validate_linux(text if kind=='camcc' else camcc,text if kind=='camss' else camss)
        except AssertionError as error:
            rejected.append(dict(name=name,sha256=sha(p),reason=str(error)))
        else:
            raise AssertionError('accepted '+name)
    original = (root/'qcpep8180.sys').read_bytes()
    mutations = [('phy-plan-300mhz',0x198908,struct.pack('<I',300000000),'bsp'),
                 ('timer-plan-400mhz',0x198a78,struct.pack('<I',400000000),'bsp'),
                 ('conditional-eligibility',0x1988f0,b'\x01','bsp'),
                 ('wrong-closest-mode',0x207430,image.read(0x207418,4),'conversion'),
                 ('wrong-action8-target',0x207377,image.read(0x207370,1),'conversion')]
    for name,rva,replacement,kind in mutations:
        section = next(s for s in image.sections if s['rva']<=rva< s['rva']+s['size'])
        at = section['raw']+rva-section['rva']
        data=bytearray(original);data[at:at+len(replacement)]=replacement
        path=out/(name+'.sys');path.write_bytes(data)
        altered = image_module.Image(bytes(data))
        try:
            (audit.clock_tables if kind=='bsp' else audit.conversion_tables)(altered)
        except AssertionError as error:
            rejected.append(dict(name=name,sha256=sha(path),reason=str(error)))
        else:
            raise AssertionError('accepted '+name)
    result = dict(inventory_files_verified=len(manifest),inventory_manifest_sha256=sha(root/'SHA256SUMS'),
                  native_cases_verified=len(cases),native_ubsan_clean=True,
                  actual_linux_lookup_body_compiled=True,rejected_fixtures=rejected,
                  selected_ranges_verified=13,hardware_operations=0,
                  limits=['C branch model is not native execution of the Windows driver.',
                          'No live clock/analog operation or BSP mutation observation.'])
    (out/'review.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    print(json.dumps(dict(files_verified=len(manifest),native_cases=len(cases),
                          rejected_fixtures=len(rejected),manifest_sha256=sha(out/'SHA256SUMS'))))


if __name__ == '__main__':
    main()
