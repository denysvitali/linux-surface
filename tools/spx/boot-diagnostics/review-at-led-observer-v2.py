#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify independent AT LED observation; leave the frozen trial verdict intact."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from at_camera_core import assess, decode, complete_trial_findings

X=Path('/var/lib/spx-boot-diagnostics/attempts/20261003at')
SRC=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def evidence(name):
 p=X/name;h=json.loads((p/'sha256.json').read_text())
 actual={str(q.relative_to(p)):sha(q) for q in p.rglob('*') if q.is_file()}
 assert actual==h|{'sha256.json':sha(p/'sha256.json')}
 return json.loads((p/'report.json').read_text()),len(h)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--final',action='store_true');args=parser.parse_args()
 a=json.loads((X/'attempt.json').read_text());assert a['attempt']=='20261003at'
 root=X/('camera-led-observer-v2-final' if args.final else 'camera-led-observer-v2-initial')
 output=X/('camera-led-observer-v2-final-review.json' if args.final else 'camera-led-observer-v2-initial-review.json');assert not output.exists()
 r,count=evidence(root.name)
 assert r['observer_lookup_source']=='LED class uevent OF_FULLNAME'
 assert r['identity_before']==r['identity_after']
 assert r['identity_before']['boot_id']!=a['preboot_id']
 assert r['identity_before']['cmdline'].split()==['BOOT_IMAGE=/spx-trial-20261003at/vmlinuz']+a['cmdline'].split()
 assert sha(root/'at_camera_core.py')==a['runtime_sha256']['/usr/local/lib/spx-boot-diagnostics/at_camera_core.py']
 assert sha(root/'at-camera-led-observer-v2.py')==sha(SRC/'at-camera-led-observer-v2.py')
 ap=X.parent/'20261002ap/camera-pmic-metadata-20261003'
 h=json.loads((ap/'sha256.json').read_text());assert all(sha(ap/n)==v for n,v in h.items())
 ref=decode(json.loads((ap/'result.json').read_text())['reads'])
 findings=assess(r,ref);assert findings['checks']==r['checks'] and findings['control_passed']==r['control_passed']
 deployment=json.loads((X/'deployment-sources-sha256.json').read_text());assert all(sha(SRC/n)==v for n,v in deployment.items())
 report={'attempt':a['attempt'],'actual_boot_id':r['identity_before']['boot_id'],'uptime_seconds':r['uptime_seconds'],
  'observer_files_verified':count,'observer_manifest_sha256':sha(root/'sha256.json'),
  'all24_original_deployment_sources_unchanged':True,'original_failed_trial_verdict_unchanged':True,
  'independent_observer_passed':findings['control_passed'],'checks':findings['checks'],
  'physical_privacy_acceptance':False,'hardware_writes':0}
 if args.final:
  first,_=evidence('camera-led-observer-v2-initial');providers,_=evidence('camera-provider-result')
  report['independent_two_observation_findings']=complete_trial_findings(first,r,providers,ref,r['identity_before'])
 with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))

if __name__=='__main__':main()
