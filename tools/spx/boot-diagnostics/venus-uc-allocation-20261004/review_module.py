#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Finish scoped module linking without installing it into the running kernel."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
WORK=Path('/var/tmp/spx-venus-uc-aarch64-20261004-v1')
VENUS='drivers/media/platform/qcom/venus/'


def main():
    os.umask(0o077);sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics');import bf_boot_guard as g
    a=g.load();assert a['state'].startswith('BF terminal;')
    assert not g.recovery(a).get('next_entry','')
    evidence=g.X/'offline-uc-allocation-20261004';hashes=json.loads((evidence/'sha256.json').read_text());assert g.files(evidence)==hashes|{'sha256.json':g.sha(evidence/'sha256.json')}
    out=g.X/'offline-uc-module-20261004-v2';assert not out.exists();out.mkdir(mode=0o700);shutil.copy2(__file__,out/Path(__file__).name)
    spec=importlib.util.spec_from_file_location('uc_compile',HERE/'build_venus.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
    proof=json.loads((WORK/'report.json').read_text());assert proof['candidate_source_sha256']==g.sha(WORK/'source'/VENUS/'hfi_venus.c')==g.sha(g.REPO/VENUS/'hfi_venus.c')
    config=g.X/'assembly/config-extracted';assert g.sha(WORK/'output/.config')==g.sha(config)
    symvers=WORK/'output/Module.symvers';frozen=g.X/'assembly/artifacts/Module.symvers'
    assert g.sha(symvers)==g.sha(frozen)=='2f11ab32d2674021bb6095e62396b932afa6290c9928976324b6759de4eb109b'
    module_output=out/'module-output';module_output.mkdir(mode=0o700)
    argv=['make','-C',str(WORK/'output'),'M='+str(WORK/'source'/VENUS),'MO='+str(module_output),'ARCH=arm64','-j6','modules']
    with (out/'make.stdout').open('xb') as stdout,(out/'make.stderr').open('xb') as stderr:r=subprocess.run(argv,stdout=stdout,stderr=stderr,timeout=300)
    (out/'command.json').write_text(json.dumps(dict(argv=argv,exit_code=r.returncode),indent=2)+'\n');assert r.returncode==0
    module=module_output/'venus-core.ko';shutil.copy2(module,out/module.name)
    c.parameter_record(module)
    data=subprocess.check_output(['modinfo',str(module)],text=True,timeout=30);(out/'modinfo').write_text(data)
    assert 'spx_uc_shared_alloc:' in data and '7.3.0-rc2-spx-mainline-20261004bf+' in data
    (out/'parent-modversions-sha256').write_text(g.sha(symvers)+'\n')
    assert g.sha(WORK/'output/.config')==g.sha(config)
    assert not g.recovery(a).get('next_entry','')
    report=dict(utc=datetime.now(timezone.utc).isoformat(),candidate_source_sha256=proof['candidate_source_sha256'],module_sha256=g.sha(module),actual_module_link_and_modpost_passed=True,scope='candidate module compiled with frozen BF config; not installed or a fresh trial kernel',actual_parameter_mode='0o400',actual_parameter_zero_bss=True,native_and_source_evidence_manifest=g.sha(evidence/'sha256.json'),known_good_recovery_verified=True,boot_selected=False,hardware_acceptance_closed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');(out/'sha256.json').write_text(json.dumps(g.files(out),indent=2)+'\n');os.sync();print(json.dumps(report|{'manifest_sha256':g.sha(out/'sha256.json')},indent=2),flush=True)


if __name__=='__main__':main()
