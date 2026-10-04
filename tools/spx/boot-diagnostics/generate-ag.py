#!/usr/bin/python3
"""Generate AG DT-only installation and bounded collection without selecting it."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
BID='4fe7d83a-37fd-4eb7-800c-850d2aa0885b'
def save(name,s):
 with (ROOT/name).open('x') as f:f.write(s)
s=(ROOT/'deploy-ab.py').read_text()
for a,b in [('20260930aa','20260930af'),('20260930ab','20260930ag'),('spx-aa-','spx-af-'),('spx-ab-','spx-ag-'),('100-ab','105-ag'),('ab-reboot-check.py','ag-reboot-check.py'),('ab-finalize.py','ag-finalize.py'),('custom-before-ab','custom-before-ag'),('custom.cfg.ab-new','custom.cfg.ag-new'),('attempt-ab.new','attempt-ag.new'),('prepared AB;','prepared AG;'),('4c68904a-46a5-4eb8-a9ee-3991fbb3c243',BID)]:s=s.replace(a,b)
s=s.replace('20260930af+','20260930ae+')
s=s.replace("assert command('uname','-r')==RELEASE and 'spx_attempt=20260930af'", "assert command('uname','-r')=='6.18.3-1-surface+' and 'spx_boot=known-good'")
s=s.replace("assert review['boot_id']==BID and review['scoped_passed'] and review['fallback_stopped']", "assert review['boot_id']=='10c7bf46-31c1-45aa-b087-b0dd74357fa8' and not review['scoped_passed'] and not review['fallback_stopped']")
s=s.replace("assert sha(AB/'build-sha256.json')", "assert sha(AA/'independent-result-review.json')==archive['prior_result_review_sha256']\nrecovery=json.loads((AA/'recovery-return/report.json').read_text())\nassert recovery['recovery_boot_id']==BID and recovery['userspace_fallback_return_verified']\nassert sha(AA/'recovery-return/sha256.json')==archive['prior_recovery_manifest_sha256']\nfor n,h in json.loads((AA/'recovery-return/sha256.json').read_text()).items():assert sha(AA/'recovery-return'/n)==h,n\nassert sha(AB/'build-sha256.json')",1)
s=s.replace('Authorized one-shot AA silent enumerator identity trial','Authorized one-shot AF silent alternate-pin native enumeration trial').replace('Authorized one-shot AB silent left identity matching trial','Authorized one-shot AG silent right identity matching trial')
s=s.replace('devicetree /spx-trial-20260930af/spx.dtb','devicetree /spx-trial-20260930ae/spx.dtb')
s=s.replace('linux /spx-trial-20260930af/vmlinuz','linux /spx-trial-20260930ae/vmlinuz').replace('initrd /spx-trial-20260930af/initramfs.img','initrd /spx-trial-20260930ae/initramfs.img')
s=s.replace('Install AB','Install AG').replace('Description=AB','Description=AG').replace('AB installed; exact AA','AG installed; exact AE').replace('new left-identity DTB','new right-identity DTB').replace('only left DT compatible','only right DT compatible').replace('Exact AA kernel','Exact AE kernel')
save('deploy-ag.py',s)

for old,new in [('af-reboot-check.py','ag-reboot-check.py'),('queue-af-once.py','queue-ag-once.py'),('review-ab-install.py','review-ag-install.py')]:
 s=(ROOT/old).read_text()
 if old=='review-ab-install.py':
  for a,b in [('20260930ab','20260930ag'),('spx-ab-','spx-ag-'),('ab_timers','ag_timers'),('prepared AB;','prepared AG;'),('4c68904a-46a5-4eb8-a9ee-3991fbb3c243',BID),('20260930aa+','20260930ae+'),('spx_attempt=20260930aa','spx_boot=known-good')]:s=s.replace(a,b)
  start=s.index('script_names = ');end=s.index('\nfor name in script_names:',start)
  s=s[:start]+"script_names = ('prepare-ag.py', 'generate-ag.py', 'deploy-ag.py', 'review-ag-install.py', 'ag-finalize.py', 'queue-ag-once.py', 'ag-reboot-check.py', 'review-ag-result.py', 'RESULT-20260930af.md', 'AUDIO-AFTER-AF-20260930.md', 'archive-af-return.py')"+s[end:]
 else:
  for a,b in [('20260930af','20260930ag'),('spx-af-','spx-ag-'),('104-af','105-ag'),('AF selected once','AG selected once'),('prepared AF;','prepared AG;'),('AF selected','AG selected')]:s=s.replace(a,b)
  s=s.replace("assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260930ae+'", "assert command('uname', '-r') == '6.18.3-1-surface+'")
  s=s.replace("assert 'spx_attempt=20260930ae' in", "assert 'spx_boot=known-good' in")
  s=s.replace('1b26cb6c-0e7f-4a3b-a290-f3bf44a6855c',BID)
 s=s.replace('Select AF once from verified AE after a clean logged boot','Select AG once after verified AF fallback return')
 save(new,s)

for old,new in [('af-finalize.py','ag-finalize.py'),('review-af-result.py','review-ag-result.py')]:
 s=(ROOT/old).read_text()
 for a,b in [('attempts/20260930af','attempts/20260930ag'),('spx_attempt=20260930af','spx_attempt=20260930ag'),("ATTEMPT = '20260930af'","ATTEMPT = '20260930ag'"),("['attempt'] == '20260930af'","['attempt'] == '20260930ag'"),("'attempt': '20260930af'","'attempt': '20260930ag'"),('spx-af-','spx-ag-')]:s=s.replace(a,b)
 s=s.replace('sdw:0:0:0217:2010:00:4','sdw:0:0:0217:2110:00:4')
 s=s.replace('slot=1 decoded=0217:2110 unique=3','slot=1 decoded=0217:2110 unique=4')
 s=s.replace("left = sdw_slaves.get('sdw:0:0:0217:2110:00:3'", "right = sdw_slaves.get('sdw:0:0:0217:2110:00:4'")
 s=s.replace("left = sdw.get('sdw:0:0:0217:2110:00:3'", "right = sdw.get('sdw:0:0:0217:2110:00:4'")
 s=s.replace('left.get(', 'right.get(').replace("endswith('/speaker@0,3')", "endswith('/speaker@0,4')").replace('left firmware identity matching','right firmware identity matching')
 if old=='af-finalize.py':
  s=s.replace("    passed = (", "    right_init = kernel.count('wsa881x-codec sdw:0:0:0217:2110:00:4: SPX: initializing amplifier at SoundWire device 1')\n    passed = (right_init >= 1 and ",1)
  s=s.replace("'wsa_cold_init_markers': wsa_init,", "'wsa_cold_init_markers': wsa_init,\n              'right_wsa_cold_init_markers': right_init,")
  s=s.replace('Archive AF alternate-pin native enumeration','Archive AG right firmware matching')
 else:
  s=s.replace('mechanism = (', "right_init = kernel.count('wsa881x-codec sdw:0:0:0217:2110:00:4: SPX: initializing amplifier at SoundWire device 1')\nassert result['right_wsa_cold_init_markers'] == right_init\nmechanism = (right_init >= 1 and ",1)
  s=s.replace("'codec_mechanism_passed': mechanism,", "'codec_mechanism_passed': mechanism,\n          'right_wsa_cold_init_markers': right_init,")
  s=s.replace("Rehash AE's native attachment", "Rehash AG's right firmware matching")
 save(new,s)
print('Generated six AG helpers with AE kernel/initramfs paths and right-specific scope; no deployment or selection')
