#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal source, native failure controls, AArch64 proof and current recovery."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import hashlib

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
COMPILE=Path('/var/tmp/spx-venus-uc-aarch64-20261004-v1')
NATIVE=Path('/var/tmp/spx-venus-uc-native-20261004-v3')
PRE=Path('/var/tmp/spx-venus-uc-preimage-20261004-v1')


def main():
    os.umask(0o077);sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics');import bf_boot_guard as g
    a=g.load();assert a['state'].startswith('BF terminal;')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==a['returned_boot_id']
    assert not g.recovery(a).get('next_entry','')
    report=json.loads((COMPILE/'report.json').read_text())
    assert report['live_compiled_paths_verified']==84669 and report['source_records_verified']==96938
    assert report['actual_aarch64_constituents']==14 and report['actual_parameter_default_zero_bss']
    assert report['actual_parameter_mode']=='0o400' and not report['full_fresh_kernel_built']
    hashes={p.name:g.sha(p) for p in COMPILE.iterdir() if p.is_file() and not p.is_symlink()}
    assert hashes==json.loads((COMPILE/'sha256.json').read_text())|{'sha256.json':g.sha(COMPILE/'sha256.json')}
    out=g.X/'offline-uc-allocation-20261004';assert not out.exists();out.mkdir(mode=0o700)
    for name,path in {'preimage':PRE,'native':NATIVE,
        'native-reinit-fixture-failure':Path('/var/tmp/spx-venus-uc-native-20261004-v1'),
        'native-unused-mock-failure':Path('/var/tmp/spx-venus-uc-native-20261004-v2'),
        'compile-import-failure':Path('/var/tmp/spx-venus-uc-compile-import-failure-20261004')}.items():
        original=json.loads((path/'sha256.json').read_text())
        assert g.files(path)==original|{'sha256.json':g.sha(path/'sha256.json')}
        shutil.copytree(path,out/name)
        assert g.files(out/name)==g.files(path)
    compiled=out/'aarch64';compiled.mkdir(mode=0o700)
    for p in COMPILE.iterdir():
        if p.is_file() and not p.is_symlink():shutil.copy2(p,compiled/p.name)
    for name in ('verify.py','build_venus.py','archive_candidate.py','native.h','checks.h','README.md'):
        shutil.copy2(HERE/name,out/name)
    archive=out/'candidate-source.tar.zst'
    with archive.open('xb') as destination,(out/'source-tar.stderr').open('xb') as te,(out/'source-zstd.stderr').open('xb') as ze:
        tar=subprocess.Popen(['tar','--hard-dereference','--sort=name','-C',str(COMPILE),'-cf','-','source'],stdout=subprocess.PIPE,stderr=te)
        zstd=subprocess.Popen(['zstd','-T2','-3','-c'],stdin=tar.stdout,stdout=destination,stderr=ze)
        tar.stdout.close();zc=zstd.wait();tc=tar.wait();assert zc==tc==0
    rows=json.loads((compiled/'candidate-source-files.json').read_text());seen=set();total=0
    p=subprocess.Popen(['zstd','-dc',str(archive)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    with tarfile.open(fileobj=p.stdout,mode='r|') as stream:
        for member in stream:
            if member.isdir():continue
            assert member.name.startswith('source/')
            name=member.name.removeprefix('source/');assert name in rows and name not in seen;seen.add(name);row=rows[name]
            if member.issym():assert row==dict(symlink=member.linkname)
            else:
                assert member.isfile() and member.mode==row['mode'] and member.size==row['bytes'],name
                h=hashlib.sha256();file=stream.extractfile(member)
                for chunk in iter(lambda:file.read(1048576),b''):h.update(chunk);total+=len(chunk)
                assert h.hexdigest()==row['sha256'],name
    p.stdout.close();err=p.stderr.read();rc=p.wait();(out/'source-stream.stderr').write_bytes(err);assert rc==0 and seen==set(rows) and len(seen)==96938
    spec=importlib.util.spec_from_file_location('uc_verify',out/'verify.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    before=(out/'preimage/hfi_venus.c').read_text();after=(out/'native/linux-hfi_venus.c').read_text();unchanged=[]
    for marker in ('int venus_hfi_create(','void venus_hfi_destroy(','void venus_hfi_queues_reinit('):
        assert v.block(before,marker)==v.block(after,marker);unchanged.append(marker)
    expected=report['candidate_source_sha256'];assert g.sha(g.REPO/'drivers/media/platform/qcom/venus/hfi_venus.c')==expected==g.sha(out/'native/linux-hfi_venus.c')
    shutil.copy2(g.X/'attempt.json',out/'terminal-bf-attempt.json');shutil.copy2(g.X/'working-recovery.json',out/'working-recovery.json')
    final=dict(utc=datetime.now(timezone.utc).isoformat(),boot_id=boot,source_tar_records_verified=len(seen),source_stream_bytes=total,source_archive_sha256=g.sha(archive),candidate_source_sha256=expected,one_changed_compiled_file=True,actual_body_functions=6,unchanged_caller_bodies=unchanged,unchanged_path_comparisons=744,shared_path_cases=24,rejected_candidates=6,actual_aarch64_constituents=14,parameter_actual_default_zero_and_mode_0400=True,original_verifier_failures_preserved=3,known_good_recovery_verified=True,next_empty=True,full_fresh_kernel_built=False,boot_selected=False,hardware_operations=0,hardware_acceptance_closed=False)
    assert not g.recovery(a).get('next_entry','') and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot
    (out/'report.json').write_text(json.dumps(final,indent=2)+'\n');(out/'sha256.json').write_text(json.dumps(g.files(out),indent=2)+'\n')
    assert g.files(out)==json.loads((out/'sha256.json').read_text())|{'sha256.json':g.sha(out/'sha256.json')};os.sync();print(json.dumps(final|{'manifest_sha256':g.sha(out/'sha256.json')},indent=2),flush=True)


if __name__=='__main__':main()
