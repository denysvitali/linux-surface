#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Inventory retained SQ2 video resources offline; no device or firmware loading."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

REPO = Path(__file__).resolve().parents[4]
DSDT_SHA = 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
FIRMWARE_SHA = {
    'oem-00040.mbn': 'bb75ac2dfcedf0bb53fb8364e66a82ffeab144168a76ca2110abaf2c0e8e2672',
    'oem-00061.mbn': 'c89f95f8443b5ed729493f294e5ea4089c6967ea49fff9c38cf34cc33d8183cc',
    'installed-00042.mbn': '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(source):
    return re.sub(r'/\*.*?\*/|//[^\n]*',
                  lambda m: re.sub(r'[^\n]', ' ', m.group()), source, flags=re.S)


def block(source, marker):
    """Bound a selected ASL scope, ignoring braces in quoted strings/comments."""
    stripped = clean(source)
    start = stripped.index(marker)
    brace = stripped.index('{', start)
    depth = 0
    for match in re.finditer(r'"[^"\n]*"|[{}]', stripped[brace:]):
        token = match.group()
        depth += (token == '{') - (token == '}')
        if depth == 0:
            return source[start:brace + match.end()]
    raise ValueError('unterminated scope')


def package(source, name):
    """Parse literal package trees, preserving every ordered item and counts."""
    stripped = clean(source)
    begin = stripped.index('Package', stripped.index(f'Name ({name},'))
    tokens = list(re.finditer(r'"[^"\n]*"|0x[0-9A-Fa-f]+|\d+|[A-Za-z_]+|[^\s]',
                              stripped[begin:]))
    index = 0
    count = 0

    def take(expected=None):
        nonlocal index
        value = tokens[index].group()
        index += 1
        if expected is not None and value != expected:
            raise ValueError(f'expected {expected}, got {value}')
        return value

    def value():
        nonlocal count
        token = take()
        if token == 'Package':
            take('('); size = value(); take(')'); take('{')
            children = []
            while tokens[index].group() != '}':
                children.append(value())
                if tokens[index].group() == ',':
                    take(',')
            take('}')
            if len(children) != size:
                raise ValueError(f'package count {size} != {len(children)}')
            count += 1
            return children
        if token == 'ToUUID':
            take('('); result = {'uuid': value()}; take(')')
            return result
        if token == 'Buffer':
            take('('); size = value(); take(')'); take('{')
            data = []
            while tokens[index].group() != '}':
                data.append(value())
                if tokens[index].group() == ',':
                    take(',')
            take('}')
            if len(data) != size or not all(isinstance(v, int) and 0 <= v < 256 for v in data):
                raise ValueError('invalid literal buffer')
            return {'buffer_hex': bytes(data).hex()}
        if token.startswith('"'):
            return token[1:-1]
        if token in ('Zero', 'One'):
            return int(token == 'One')
        if re.fullmatch(r'0x[0-9A-Fa-f]+|\d+', token):
            return int(token, 0) if token.startswith('0x') else int(token)
        raise ValueError(f'non-literal token {token}')

    return value(), count


def tagged(tree, tag):
    found = []
    if isinstance(tree, list):
        if tree and tree[0] == tag:
            found.append(tree)
        for child in tree:
            found.extend(tagged(child, tag))
    return found


def firmware(path):
    data = path.read_bytes()
    assert data[:7] == b'\x7fELF\x01\x01\x01'
    fields = struct.unpack_from('<HHIIIIIHHHHHH', data, 16)
    assert fields[1] == 40 and fields[8] == 32
    headers = []
    for index in range(fields[9]):
        vals = struct.unpack_from('<8I', data, fields[4] + index * fields[8])
        row = dict(zip(['type', 'offset', 'vaddr', 'paddr', 'filesz', 'memsz', 'flags', 'align'], vals))
        assert row['offset'] + row['filesz'] <= len(data)
        row['linux_mdt_loadable'] = (row['type'] == 1 and row['memsz'] != 0 and
                                    row['flags'] & (7 << 24) != 2 << 24)
        row['relocatable'] = bool(row['flags'] & (1 << 27))
        headers.append(row)
    load = [h for h in headers if h['linux_mdt_loadable']]
    low = min(h['paddr'] for h in load)
    end = max((h['paddr'] + h['memsz'] + 4095) & ~4095 for h in load)
    versions = [m.group().decode() for m in re.finditer(
        rb'(?:QC_IMAGE_VERSION_STRING|IMAGE_VARIANT_STRING|OEM_IMAGE_VERSION_STRING)=[\x20-\x7e]+', data)]
    readelf = subprocess.check_output(['readelf', '-W', '-l', str(path)], text=True)
    return dict(headers=headers, loadable_segments=len(load), lowest_paddr=low,
                aligned_end=end, linux_mdt_size=end-low, versions=versions,
                relocatable=all(h['relocatable'] for h in load), readelf=readelf)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--references', type=Path, default=Path('/var/tmp/spx-video-integration-fetch-20261003'))
    args = p.parse_args()
    out = args.output
    out.mkdir(mode=0o700)
    acpi = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2')
    drivers = Path('/home/dvitali/Documents/drivers/FileRepository')
    paths = {'dsdt.dsl': acpi/'dsdt.dsl', 'iort.dsl': acpi/'iort.dsl', 'audit_video.py': Path(__file__)}
    for revision, suffix in [('00040','80e19250e112d800'), ('00061','df5df23ee5cd0b80')]:
        root = drivers/f'qcdx8180.inf_arm64_{suffix}'
        paths[f'oem-{revision}.mbn'] = root/'qcvss8180.mbn'
        paths[f'oem-{revision}.inf'] = root/'qcdx8180.inf'
        paths[f'oem-{revision}.sys'] = root/'qcdxkm8180.sys'
    paths['installed-00042.mbn'] = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    for name in ['core.c','core.h','hfi_venus.c','hfi_venus_io.h','pm_helpers.c','firmware.c','hfi_cmds.c','hfi_helper.h']:
        paths['linux-'+name] = REPO/'drivers/media/platform/qcom/venus'/name
    for relative in ['arch/arm64/boot/dts/qcom/sc8180x.dtsi', 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts',
                     'drivers/clk/qcom/videocc-sm8150.c', 'drivers/clk/qcom/gcc-sc8180x.c',
                     'drivers/soc/qcom/mdt_loader.c', 'include/linux/soc/qcom/mdt_loader.h']:
        paths['linux-'+Path(relative).name] = REPO/relative
    for entry in json.loads((args.references/'fetch.json').read_text()):
        if 'file' in entry:
            path = args.references/entry['file']
            assert sha(path) == entry['sha256']
            paths['reference-'+entry['file']] = path
    for name in ['fetch.json','vidc-directory.json']:
        paths['reference-'+name] = args.references/name
    inputs = {}
    for name, source in paths.items():
        digest = sha(source)
        if name == 'dsdt.dsl': assert digest == DSDT_SHA
        if name in FIRMWARE_SHA: assert digest == FIRMWARE_SHA[name]
        shutil.copyfile(source, out/name)
        assert sha(out/name) == digest
        inputs[name] = dict(path=str(source), sha256=digest)
    source = (out/'dsdt.dsl').read_text()
    gpu = block(source, 'Device (GPU0)')
    resources = {}
    for name in ['ABUF','BBUF']:
        selected = block(gpu, f'Name ({name},')
        memories = [tuple(int(v,16) for v in m) for m in re.findall(
            r'Memory32Fixed \(Read\w+,\s*(0x[0-9A-F]+),\s*//[^\n]*\n\s*(0x[0-9A-F]+)', selected)]
        interrupts = [int(v,16) for v in re.findall(r'Interrupt \([^\n]*\)\s*\{\s*(0x[0-9A-F]+)', selected)]
        assert (0xaa00000,0x200000) in memories and interrupts[-2:] == [206,207]
        resources[name] = dict(memories=memories, interrupts_gsi=interrupts)
    engs, eng_count = package(block(gpu,'Method (ENGS,'),'EBUF')
    pmcl, pmcl_count = package(block(gpu,'Method (PMCL,'),'RBUF')
    video = [v for v in tagged(engs,'ENGINE') if v[1]=='VIDEO']
    assert len(video)==1 and video[0][2:4]==['Venus',4]
    components = [v for v in tagged(pmcl,'COMPONENT') if v[3]=='VIDEO_POWER_STATES']
    assert len(components)==1
    g4, g4_count = package(block(source,'Method (G4MD,'),'GPCC')
    assert g4[0][0:2] == ['DEVICE','\\\\_SB.GPU0'] and g4[0][2][0:2] == ['COMPONENT',4]
    iort = (out/'iort.dsl').read_text()
    at = iort.index('Device Name : "\\_SB.GPU0"')
    boundary = re.search(r'^\[[^\n]+\]\s+Type :',iort[at:],re.M)
    selected = iort[at:at+boundary.start()]
    mappings = [dict(zip(['input','count','output','reference','flags'], map(lambda s:int(s,16), m)))
                for m in re.findall(r'Input base : ([0-9A-F]+).*?ID Count : ([0-9A-F]+).*?Output Base : ([0-9A-F]+).*?Output Reference : ([0-9A-F]+).*?Flags \(decoded below\) : ([0-9A-F]+)',selected,re.S)]
    assert len(mappings)==51
    vm = [m for m in mappings if m['input']>>24==4]
    assert len(vm)==10 and all(m['reference']==0x30 and m['count']==0 for m in vm)
    images = {name:firmware(out/name) for name in FIRMWARE_SHA}
    for name, record in images.items():
        (out/(name+'.readelf.txt')).write_text(record.pop('readelf'))
        assert record['linux_mdt_size']==0x500000 and record['loadable_segments']==3 and record['relocatable']
    core = (out/'linux-core.c').read_text()
    matches = re.findall(r'\.compatible = "([^"]+)"',core[core.index('static const struct of_device_id venus_dt_match'):])
    assert 'qcom,sc8180x-venus' not in matches and 'qcom,sm8150-venus' not in matches
    result = dict(inputs=inputs, resources=resources, video_engine=video[0],
                  video_page_tables=[v for v in tagged(engs,'VideoNonSecurePT')+tagged(engs,'VideoSecurePT1')+tagged(engs,'VideoSecurePT2')+tagged(engs,'VideoSecurePT3')+tagged(engs,'VideoSecurePT4')],
                  video_power_component=components[0], g4md=g4,
                  literal_packages_verified={'ENGS':eng_count,'PMCL':pmcl_count,'G4MD':g4_count},
                  video_iort_mappings=vm, firmware=images, venus_matches=matches,
                  hardware_actions=0, limits=['Static firmware tables are not observed Windows execution.',
                  'IORT input-ID packing, SID masks and Linux context-bank policy need explicit reconciliation.',
                  'Related SM8150 HFI4xx and power sequence are reference evidence, not SQ2 firmware acceptance.',
                  'MDT layout/relocatable flags do not establish secure authentication, carveout safety or a boot.',
                  'Formats, codec work, output correctness and sustained playback are untested.'])
    (out/'inventory.json').write_text(json.dumps(result,indent=2)+'\n')
    sums={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out/'sha256.json').write_text(json.dumps(sums,indent=2)+'\n')
    assert all(sha(out/name)==digest for name,digest in sums.items())
    print(json.dumps({'files_verified':len(sums),'manifest_sha256':sha(out/'sha256.json'),
                      'packages':result['literal_packages_verified'],'video_iort_mappings':vm,
                      'firmware_versions':{n:r['versions'] for n,r in images.items()},'hardware_actions':0},indent=2))


if __name__ == '__main__':
    main()
