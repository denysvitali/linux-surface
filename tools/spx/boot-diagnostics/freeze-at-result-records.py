#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Freeze AT baseline pass, original observer failure and separate LED observations."""
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
from at_boot_guard import X,REPO,load,recovery,files,sha,command

def verify(root):
 h=json.loads((root/'sha256.json').read_text())
 assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}

def main():
 os.umask(0o077);a=load();bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 assert bid=='1cf4d1ac-a076-4f3f-b89a-b0690e487528'!=a['preboot_id'] and os.uname().release==a['release']
 assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20261003at/vmlinuz']+a['cmdline'].split()
 assert not recovery(a).get('next_entry','')
 dirs=('final-result','camera-provider-result','camera-control-result','camera-control-final-result',
       'handoff-review','startup-discovery','initial-observer-failure','camera-led-observer-v2-initial',
       'camera-led-observer-v2-final','supplemental-source')
 for n in dirs:verify(X/n)
 result=json.loads((X/'final-result/result.json').read_text());review=json.loads((X/'independent-result-review.json').read_text())
 action=json.loads((X/'finalizer-action.json').read_text());touch=json.loads((X/'touch-startup-review.json').read_text())
 assert all(r['boot_id']==bid for r in (result,review,action,touch))
 assert result['passed_scoped_baseline'] is True and review['scoped_passed'] is True
 assert result['passed_trial'] is False and review['trial_passed'] is False
 assert action['fallback_stopped'] is False and review['fallback_stopped'] is False
 assert review['camera_provider_idle_passed'] and review['camera_observations_ordered']
 assert not review['camera_control_initial_passed'] and not review['camera_control_final_passed']
 for n in ('camera-control-review.json','camera-control-final-review.json'):
  r=json.loads((X/n).read_text());assert r['boot_id']==bid and not r['control_passed']
  assert r['failure_reasons']==['rear_privacy_provider_bound_idle','rear_privacy_dt_relation_exact']
 assert touch['clean_touch_startup'] and touch['final_scoped_baseline_passed']
 for n in ('camera-led-observer-v2-initial-review.json','camera-led-observer-v2-final-review.json'):
  r=json.loads((X/n).read_text());assert r['actual_boot_id']==bid and r['independent_observer_passed']
  assert r['all24_original_deployment_sources_unchanged'] and r['original_failed_trial_verdict_unchanged']
 assert r['independent_two_observation_findings']['camera_trial_passed']
 assert command('systemctl','show','spx-at-fallback.timer','-p','ActiveState','--value')=='active'
 helpers=REPO/'tools/spx/boot-diagnostics'
 for n,v in json.loads((X/'deployment-sources-sha256.json').read_text()).items():assert sha(helpers/n)==v
 checklist=(REPO/'PORT-CHECKLIST.md').read_text();items=re.findall(r'^- \[([ xX])\] \*\*([A-Z]\d{2})',checklist,re.M)
 hardware=[(v,n) for v,n in items if not n.startswith('M')];assert len(hardware)==47 and all(v==' ' for v,n in hardware)
 names=('attempt.json','archive-review.json','independent-result-review.json','finalizer-action.json',
        'camera-provider-review.json','camera-control-review.json','camera-control-final-review.json',
        'camera-led-observer-v2-initial-review.json','camera-led-observer-v2-final-review.json',
        'touch-startup-review.json','deployment-sources-sha256.json','reboot-check-passed.json')
 inputs={n:X/n for n in names}
 inputs|={n+'-sha256.json':X/n/'sha256.json' for n in dirs}
 inputs|={n:REPO/n for n in ('LOCAL-PROGRESS.md','PORT-CHECKLIST.md')}
 inputs|={n:helpers/n for n in ('RESULT-20261003at.md','PREPARED-20261003at.md','review-at-result.py',
    'review-at-handoff.py','review-at-handoff-v2.py','at-camera-control.py','at-camera-led-observer-v2.py',
    'review-at-led-observer-v2.py','at_camera_core.py',Path(__file__).name)}
 out=X/'post-result-records';assert not out.exists();out.mkdir(mode=0o700)
 for n,p in inputs.items():shutil.copyfile(p,out/n)
 assert files(out)=={n:sha(p) for n,p in inputs.items()}
 r={'attempt':a['attempt'],'boot_id':bid,'baseline_passed':True,'original_trial_passed':False,
    'independent_two_led_observations_passed':True,'original24_helpers_unchanged':True,
    'fallback_armed':True,'actual_recovery_return_observed':False,'physical_privacy_acceptance':False,
    'capture_verified':False,'hardware_acceptance_checks_remaining':47}
 (out/'report.json').write_text(json.dumps(r,indent=2)+'\n');h=files(out)
 (out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');verify(out)
 assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid;assert not recovery(a).get('next_entry','')
 os.sync();print(json.dumps(r|{'files_verified':len(h),'manifest_sha256':sha(out/'sha256.json')},indent=2))

if __name__=='__main__':main()
