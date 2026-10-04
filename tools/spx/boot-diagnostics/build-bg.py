#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze and fully build BG's isolated shared UC allocation experiment."""
from datetime import datetime, timezone
import difflib
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode=True
sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
import bf_boot_guard as g

REPO=g.REPO
PARENT=Path('/var/tmp/spx-mainline-trial-20261004bf')
STAGE=Path('/var/tmp/spx-mainline-trial-20261004bg')
BOOT='42966575-e6ec-4698-83c2-80e5aeb07011'
RELEASE='7.3.0-rc2-spx-mainline-20261004bg+'
CHANGED='drivers/media/platform/qcom/venus/hfi_venus.c'
BOARD='arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'
CANDIDATE_SHA='baada5ccc9e08dd9267451cbfa32a23bf2b8eba064a63bf8250ba0f1f9c209ee'


def read(path):return json.loads(path.read_text())


def records(root):
    rows={}
    for p in sorted(root.rglob('*')):
        name=str(p.relative_to(root))
        if p.is_symlink():rows[name]=dict(symlink=os.readlink(p))
        elif p.is_file():rows[name]=dict(sha256=g.sha(p),bytes=p.stat().st_size,mode=stat.S_IMODE(p.stat().st_mode))
    return rows


def live_source():
    rows=read(g.X/'assembly/source-files.json');checked=0
    for name,row in rows.items():
        top=Path(name).parts[0]
        if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or (top=='tools' and not name.startswith('tools/spx/boot-diagnostics/')) or name=='Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):continue
        path=REPO/name
        if 'sha256' in row:assert g.sha(path)==(CANDIDATE_SHA if name==CHANGED else row['sha256']),name
        else:assert path.is_symlink() and os.readlink(path)==row['symlink'],name
        checked+=1
    assert checked==84669 and g.sha(REPO/'.config')==g.sha(g.X/'assembly/live-config-before')
    return checked


def states(path):
    return {l.split('=',1)[0]:l.split('=',1)[1] for l in path.read_text().splitlines() if l.startswith('CONFIG_')}


def main():
    os.umask(0o077);assert os.geteuid()==0 and os.uname().machine=='aarch64'
    a=g.load();assert a['state'].startswith('BF terminal;') and a['returned_boot_id']==BOOT
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BOOT
    assert os.uname().release=='6.18.3-1-surface+' and not g.recovery(a).get('next_entry','')
    g.artifacts(a);live_source()
    proofs={'offline-uc-allocation-20261004':'0cec64d92caef49bf0570da4a733f55711981f606f502d5a4e7a53bea2499dec',
            'offline-uc-module-20261004-v2':'2d2d1213b6456c6ad2b51622134400c2af13a1c9b681d357b5e91077e95c52a5'}
    for name,digest in proofs.items():
        p=g.X/name;assert g.sha(p/'sha256.json')==digest and g.files(p)==read(p/'sha256.json')|{'sha256.json':digest}
    proof=read(g.X/'offline-uc-allocation-20261004/report.json')
    assert proof['unchanged_path_comparisons']==744 and proof['shared_path_cases']==24 and proof['rejected_candidates']==6
    assert proof['candidate_source_sha256']==CANDIDATE_SHA
    assert g.sha(PARENT/'work-build/.config')==g.sha(g.X/'assembly/config-extracted')=='6897d4a27ae7e4120522df46a22babdf1b41eb2bb4d4a83cc43010aa6648f59c'
    STAGE.mkdir(mode=0o700);shutil.copy2(__file__,STAGE/Path(__file__).name)
    shutil.copy2(REPO/'.config',STAGE/'live-config-before');shutil.copy2(PARENT/'work-build/.config',STAGE/'config-parent')
    shutil.copy2(g.X/'assembly/source-files.json',STAGE/'parent-bf-source-files.json')
    commands=[]
    def run(label,argv):
        start=time.monotonic()
        with (STAGE/(label+'.log')).open('xb') as stream:r=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT)
        commands.append(dict(label=label,argv=argv,exit_code=r.returncode,seconds=round(time.monotonic()-start,3)))
        (STAGE/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');print(json.dumps(commands[-1]),flush=True);assert r.returncode==0,label
    source=STAGE/'source';build=STAGE/'work-build'
    run('snapshot',['cp','-a','--reflink=auto',str(PARENT/'source'),str(source)])
    parent=read(STAGE/'parent-bf-source-files.json');original=records(source);assert original==parent and len(original)==96938
    before=(source/CHANGED).read_text();after=(REPO/CHANGED).read_text();assert before!=after
    shutil.copy2(REPO/CHANGED,source/CHANGED)
    final=records(source);assert set(final)==set(parent) and {n for n in final if final[n]!=parent[n]}=={CHANGED}
    delta={CHANGED:dict(before_sha256=parent[CHANGED]['sha256'],after_sha256=CANDIDATE_SHA)}
    (STAGE/'compiled-source-delta.json').write_text(json.dumps(delta,indent=2)+'\n')
    (STAGE/'source-files.json').write_text(json.dumps(final,indent=2)+'\n')
    (STAGE/'source.diff').write_text(''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+CHANGED,tofile='b/'+CHANGED)))
    run('source-archive',['tar','--hard-dereference','--zstd','-cf',str(STAGE/'source.tar.zst'),'-C',str(source),'.'])
    seen=set()
    with subprocess.Popen(['zstd','-dc',str(STAGE/'source.tar.zst')],stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
            for e in archive:
                if e.isdir():continue
                name=e.name.removeprefix('./');assert name in final and name not in seen;seen.add(name);row=final[name]
                if e.issym():assert row==dict(symlink=e.linkname)
                else:
                    assert e.isfile() and e.size==row['bytes'] and e.mode==row['mode'];h=hashlib.sha256();f=archive.extractfile(e)
                    for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
                    assert h.hexdigest()==row['sha256'],name
        assert proc.wait()==0 and seen==set(final)
    (STAGE/'source-tar.json').write_text(json.dumps(dict(records_verified=len(seen),source_archive_stream_verified=True,sha256=g.sha(STAGE/'source.tar.zst')),indent=2)+'\n')
    run('output-clone',['cp','-a','--reflink=auto',str(PARENT/'work-build'),str(build)])
    make=['make','-C',str(source),'O='+str(build),'ARCH=arm64','LOCALVERSION=+']
    run('config-set',[str(source/'scripts/config'),'--file',str(build/'.config'),'--set-str','LOCALVERSION','-spx-mainline-20261004bg'])
    run('olddefconfig',make+['olddefconfig'])
    before_cfg,after_cfg=states(STAGE/'config-parent'),states(build/'.config')
    cfg={k:dict(before=before_cfg.get(k,'n'),after=after_cfg.get(k,'n')) for k in set(before_cfg)|set(after_cfg) if before_cfg.get(k,'n')!=after_cfg.get(k,'n')}
    assert cfg=={'CONFIG_LOCALVERSION':dict(before='"-spx-mainline-20261004bf"',after='"-spx-mainline-20261004bg"')}
    prepared=dict(utc=datetime.now(timezone.utc).isoformat(),boot_id=BOOT,release=RELEASE,source_files=len(final),source_manifest_sha256=g.sha(STAGE/'source-files.json'),source_archive_sha256=g.sha(STAGE/'source.tar.zst'),config_sha256=g.sha(build/'.config'),config_delta=cfg,one_shared_allocation_source_change=delta,proof_manifests=proofs,boot_selected=False)
    (STAGE/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');(STAGE/'compile-started.json').write_text(json.dumps(dict(utc=prepared['utc']),indent=2)+'\n')
    run('prepare',make+['prepare']);assert (build/'source').resolve()==source
    assert subprocess.check_output(make+['-s','kernelrelease'],text=True).strip().splitlines()[-1]==RELEASE
    run('image-dtb',make+['-j6','Image','qcom/sc8180x-surface-pro-x.dtb']);run('modules',make+['-j6','modules'])
    order=(build/'modules.order').read_text().splitlines();assert len(order)==len(set(order))==202 and set(order)==set((PARENT/'work-build/modules.order').read_text().splitlines())
    modules=[str(Path(n).with_suffix('.ko')) for n in order]
    names=['.config','System.map','vmlinux','Module.symvers','modules.order','arch/arm64/boot/Image','arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']+modules
    artifacts=STAGE/'artifacts'
    for n in names:
        destination=artifacts/n;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(build/n,destination)
    config=(build/'.config').read_bytes();assert subprocess.check_output([str(source/'scripts/extract-ikconfig'),str(artifacts/'arch/arm64/boot/Image')])==config
    (STAGE/'config-extracted').write_bytes(config)
    vermagic={}
    for n in modules:
        value=subprocess.check_output(['modinfo','-F','vermagic',str(artifacts/n)],text=True).strip();assert value.split()[0]==RELEASE;vermagic[n]=value
    (STAGE/'module-vermagic.json').write_text(json.dumps(vermagic,indent=2)+'\n')
    raw='arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb';assert (artifacts/raw).read_bytes()==(g.X/'build/artifacts'/raw).read_bytes()
    shutil.copy2(g.X/'build/spx.dtb',STAGE/'spx.dtb')
    venus=artifacts/'drivers/media/platform/qcom/venus/venus-core.ko'
    spec=importlib.util.spec_from_file_location('uc_elf',REPO/'tools/spx/boot-diagnostics/venus-uc-allocation-20261004/build_venus.py');elf=importlib.util.module_from_spec(spec);spec.loader.exec_module(elf);elf.parameter_record(venus)
    symbols=subprocess.check_output(['nm','--defined-only',str(venus)],text=True);parsed={r.split()[-1]:r.split()[-2] for r in symbols.splitlines() if len(r.split())==3}
    assert parsed['venus_hfi_startup_diag']=='T' and all(parsed[n]=='b' for n in ('spx_hfi_startup_diag','spx_hfi_startup_diag_lines','spx_uc_shared_alloc'))
    parms=subprocess.check_output(['modinfo','-F','parmtype',str(venus)],text=True).splitlines();assert 'spx_uc_shared_alloc:bool' in parms and 'spx_hfi_startup_diag:bool' in parms
    (STAGE/'venus-module-parmtype.txt').write_text('\n'.join(parms)+'\n')
    with (STAGE/'vmlinuz').open('xb') as out:
        with gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as compressed:shutil.copyfileobj((artifacts/'arch/arm64/boot/Image').open('rb'),compressed)
    assert records(source)==final and live_source()==84669
    assert (REPO/'.config').read_bytes()==(STAGE/'live-config-before').read_bytes() and g.sha(PARENT/'work-build/.config')==g.sha(STAGE/'config-parent')
    assert not g.recovery(a).get('next_entry','') and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BOOT
    result=dict(**prepared,utc_complete=datetime.now(timezone.utc).isoformat(),modules=len(modules),artifacts={n:g.sha(artifacts/n) for n in names},embedded_config_exact=True,full_kernel_linked=True,loadable_modules_linked=True,raw_dtb_exact_bf=True,venus_shared_alloc_actual_zero_default_0400=True,source_snapshot_unchanged=True,live_config_unchanged=True,live_compiled_source_paths_verified=84669,deployed=False,hardware_operations=0,hardware_acceptance_closed=False)
    (STAGE/'build-complete.json').write_text(json.dumps(result,indent=2)+'\n');os.sync();print(json.dumps(dict(release=RELEASE,modules=202,source_manifest_sha256=prepared['source_manifest_sha256'])),flush=True)


if __name__=='__main__':main()
