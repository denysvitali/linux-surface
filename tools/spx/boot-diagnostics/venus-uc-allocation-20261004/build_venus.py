#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual shared-UC AArch64 constituents in an isolated BF tree."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import time

sys.dont_write_bytecode=True
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
PARENT=Path('/var/tmp/spx-mainline-trial-20261004bf')
VENUS='drivers/media/platform/qcom/venus/'


def parameter_record(path):
    data=path.read_bytes()
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
    assert h[0][:6]==b'\x7fELF\x02\x01' and h[2]==183 and h[11]==64
    assert 0<h[12]<65535 and h[6]+h[11]*h[12]<=len(data)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,h[6]+64*n) for n in range(h[12])]
    symbols={}
    for section in sections:
        if section[1]!=2:continue
        assert section[9]==24 and section[5]%24==0 and section[4]+section[5]<=len(data)
        strings=sections[section[6]];assert strings[4]+strings[5]<=len(data)
        names=data[strings[4]:strings[4]+strings[5]]
        for at in range(section[4],section[4]+section[5],24):
            s=struct.unpack_from('<IBBHQQ',data,at);assert s[0]<len(names)
            end=names.index(b'\0',s[0]);name=names[s[0]:end].decode()
            if name in ('spx_uc_shared_alloc','__param_spx_uc_shared_alloc'):
                assert name not in symbols;symbols[name]=s
    var=symbols['spx_uc_shared_alloc'];assert var[5]==1 and sections[var[3]][1]==8
    param=symbols['__param_spx_uc_shared_alloc'];assert param[5]==40
    sec=sections[param[3]];assert param[4]+40<=sec[5]
    at=sec[4]+param[4];assert at+40<=len(data)
    assert struct.unpack_from('<H',data,at+24)[0]==0o400


def main():
    p=argparse.ArgumentParser();p.add_argument('native',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
    os.umask(0o077);sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics');import bf_boot_guard as g
    a=g.load();assert a['state'].startswith('BF terminal;')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==a['returned_boot_id']
    assert not g.recovery(a).get('next_entry','')
    n=json.loads((args.native/'report.json').read_text());nd=g.sha(args.native/'sha256.json')
    assert nd=='a3d0a1b29336e859a642de3df3f90628730049f2cb1dd1e40fdd8024d0ed9dfe'
    assert g.files(args.native)==json.loads((args.native/'sha256.json').read_text())|{'sha256.json':nd}
    assert sum(r['unchanged_path_comparisons'] for r in n['actual_body_results'])==744
    assert sum(r['shared_cases'] for r in n['actual_body_results'])==24
    assert len(n['rejected_candidates'])==6
    rows=json.loads((g.X/'assembly/source-files.json').read_text());assert len(rows)==96938
    def live():
        checked=0
        for name,row in rows.items():
            top=Path(name).parts[0]
            if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or (top=='tools' and not name.startswith('tools/spx/boot-diagnostics/')) or name=='Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):continue
            path=REPO/name
            if 'sha256' in row:assert g.sha(path)==(n['candidate_sha256'] if name==VENUS+'hfi_venus.c' else row['sha256']),name
            else:assert path.is_symlink() and os.readlink(path)==row['symlink'],name
            checked+=1
        assert checked==84669
        assert g.sha(REPO/'.config')==g.sha(g.X/'assembly/live-config-before')
        return checked
    checked=live()
    out=args.output;out.mkdir(mode=0o700);shutil.copy2(__file__,out/Path(__file__).name)
    shutil.copy2(g.X/'assembly/source-files.json',out/'parent-source-files.json')
    commands=[]
    def run(label,argv,timeout=300):
        start=time.monotonic()
        with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
            r=subprocess.run(argv,stdout=stdout,stderr=stderr,timeout=timeout)
        commands.append(dict(label=label,argv=argv,exit_code=r.returncode,seconds=round(time.monotonic()-start,3)))
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');print(json.dumps(commands[-1]),flush=True);assert r.returncode==0,label
    source=out/'source';output=out/'output'
    run('source-snapshot',['cp','-a','--reflink=auto',str(PARENT/'source'),str(source)])
    def verify_source(expected):
        actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()};assert actual==set(expected)
        for name,row in expected.items():
            path=source/name
            if 'sha256' in row:assert not path.is_symlink() and g.sha(path)==row['sha256'] and stat.S_IMODE(path.stat().st_mode)==row['mode'],name
            else:assert path.is_symlink() and os.readlink(path)==row['symlink'],name
        return len(actual)
    assert verify_source(rows)==96938
    expected=copy.deepcopy(rows);file=source/VENUS/'hfi_venus.c';shutil.copy2(REPO/VENUS/'hfi_venus.c',file)
    expected[VENUS+'hfi_venus.c'].update(sha256=n['candidate_sha256'],bytes=file.stat().st_size)
    assert verify_source(expected)==96938
    (out/'candidate-source-files.json').write_text(json.dumps(expected,indent=2)+'\n')
    run('output-clone',['cp','-a','--reflink=auto',str(PARENT/'work-build'),str(output)])
    config=g.X/'assembly/config-extracted';assert g.sha(output/'.config')==g.sha(config);shutil.copy2(config,out/'config')
    make=['make','-C',str(source),'O='+str(output),'ARCH=arm64','LOCALVERSION=+']
    run('olddefconfig',make+['olddefconfig']);assert g.sha(output/'.config')==g.sha(config)
    run('prepare',make+['-j6','modules_prepare'])
    match=re.search(r'venus-core-objs \+= (.*?)\n\n',(source/VENUS/'Makefile').read_text(),re.S);assert match
    names=re.findall(r'\b[\w-]+\.o\b',match[1]);assert len(names)==len(set(names))==14
    run('objects',make+['-j6']+[VENUS+name for name in names])
    for name in names:
        shutil.copy2(output/VENUS/name,out/name);shutil.copy2(output/VENUS/('.'+name+'.cmd'),out/('.'+name+'.cmd'))
    run('independent-link',['ld','-r','-o',str(out/'venus-core.o')]+[str(out/name) for name in names])
    run('headers',['readelf','-h',str(out/'venus-core.o')]);run('symbols',['readelf','-sW',str(out/'venus-core.o')]);run('strings',['strings',str(out/'venus-core.o')])
    parameter_record(out/'venus-core.o')
    strings=(out/'strings.stdout').read_text().splitlines();assert 'parmtype=spx_uc_shared_alloc:bool' in strings and 'spx_uc_shared_alloc' in strings
    cmd=(out/'.hfi_venus.o.cmd').read_text().splitlines()[0];assert '-DMODULE' in cmd and '-D__KBUILD_MODNAME=venus_core' in cmd
    assert verify_source(expected)==96938 and live()==checked
    assert g.sha(output/'.config')==g.sha(config) and not g.recovery(a).get('next_entry','')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot
    report=dict(utc=datetime.now(timezone.utc).isoformat(),boot_id=boot,native_manifest_sha256=nd,source_records_verified=96938,live_compiled_paths_verified=checked,one_source_change=VENUS+'hfi_venus.c',candidate_source_sha256=n['candidate_sha256'],config_exact_bf=True,live_config_unchanged=True,actual_aarch64_constituents=14,independent_link_sha256=g.sha(out/'venus-core.o'),actual_parameter_mode='0o400',actual_parameter_default_zero_bss=True,module_identity='venus_core',known_good_recovery_verified=True,next_empty=True,full_fresh_kernel_built=False,deployed=False,boot_selected=False,hardware_acceptance_closed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    hashes={p.name:g.sha(p) for p in sorted(out.iterdir()) if p.is_file() and not p.is_symlink()};(out/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n');os.sync();print(json.dumps(report|{'manifest_sha256':g.sha(out/'sha256.json')},indent=2),flush=True)


if __name__=='__main__':main()
