#!/usr/bin/python3
"""Generate AH exact AG artifact reuse and corrected-topology pin1 control."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BID='43efd328-c5ba-48bf-9edf-797ccf268b1f'
def save(name,text):
 with (ROOT/name).open('x') as f:f.write(text)
def owned(s):
 for a,b in [('attempts/20260930ag','attempts/20260930ah'),('spx_attempt=20260930ag','spx_attempt=20260930ah'),("ATTEMPT = '20260930ag'","ATTEMPT = '20260930ah'"),("['attempt'] == '20260930ag'","['attempt'] == '20260930ah'"),("'attempt': '20260930ag'","'attempt': '20260930ah'"),('spx-ag-','spx-ah-')]:s=s.replace(a,b)
 return s

# Reuse installer performs no build and retains all installed payload paths.
s=(ROOT/'deploy-af.py').read_text()
for a,b in [('attempts/20260930ae','attempts/20260930ag'),('20260930af','20260930ah'),('spx-af-','spx-ah-'),('104-af','106-ah'),('af-finalize.py','ah-finalize.py'),('af-reboot-check.py','ah-reboot-check.py'),('custom-before-af','custom-before-ah'),('custom.cfg.af-new','custom.cfg.ah-new'),('attempt-af.new','attempt-ah.new'),('prepared AF;','prepared AH;'),('1b26cb6c-0e7f-4a3b-a290-f3bf44a6855c',BID)]:s=s.replace(a,b)
s=s.replace("assert command('uname', '-r') == RELEASE","assert command('uname', '-r') == '6.18.3-1-surface+'")
s=s.replace("assert 'spx_attempt=20260930ae' in", "assert 'spx_boot=known-good' in")
s=s.replace("(Z / 'build/source.diff')", "(Z / 'dtb-build/source.diff')")
s=s.replace("assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']", "assert parent_review['boot_id'] == '06d871cf-3529-49e2-9c02-3b9256e6fb06' and not parent_review['scoped_passed'] and not parent_review['fallback_stopped']\nassert parent_review['scoped_failure_reasons'] == ['native bus/clock-stop path']")
s=s.replace("parent_review['native_force_off_path_passed']", "parent_review['firmware_identity_match_passed']")
s=s.replace("'spx-ae-fallback.timer'", "'spx-ag-fallback.timer'")
s=s.replace("cmdline = prior['cmdline'].replace('spx_attempt=20260930ae',", "cmdline = prior['cmdline'].replace('spx_attempt=20260930ag',")
s=s.replace(".replace('wcd934x.spx_wsa_en_pin=1', 'wcd934x.spx_wsa_en_pin=2')", ".replace('wcd934x.spx_wsa_en_pin=2', 'wcd934x.spx_wsa_en_pin=1')")
s=s.replace("{'spx_attempt=20260930ah', 'wcd934x.spx_wsa_en_pin=2'}", "{'spx_attempt=20260930ah', 'wcd934x.spx_wsa_en_pin=1'}")
s=s.replace("{'spx_attempt=20260930ae', 'wcd934x.spx_wsa_en_pin=1'}", "{'spx_attempt=20260930ag', 'wcd934x.spx_wsa_en_pin=2'}")
s=s.replace('--id spx-trial-20260930ae','--id spx-trial-20260930ag').replace('set spx_diag_attempt=20260930ae','set spx_diag_attempt=20260930ag').replace('SPX bounded boot diagnostic 20260930ae','SPX bounded boot diagnostic 20260930ag')
s=s.replace('Authorized one-shot AE silent later-startup metadata trial','Authorized one-shot AG silent right identity matching trial').replace('Authorized one-shot AF silent alternate-pin native enumeration trial','Authorized one-shot AH silent corrected-topology pin1 control')
s=s.replace('devicetree /spx-trial-20260930ae/spx.dtb','devicetree /spx-trial-20260930ag/spx.dtb')
s=s.replace("'parent_attempt': '20260930ae'", "'parent_attempt': '20260930ag'")
s=s.replace('Exact AE artifacts; pin1 -> pin2; no PCM or playback','Exact AG artifacts; pin2 -> pin1; no PCM or playback').replace('AF silent alternate-pin enumeration','AH silent corrected-topology pin1 control').replace('AF installed with exact AE','AH installed with exact AG')
s=s.replace("for name, digest in (prior['sha256']", "recovery = json.loads((Y / 'recovery-return/report.json').read_text())\nassert recovery['recovery_boot_id'] == BID and recovery['userspace_fallback_return_verified']\nassert sha(Y / 'recovery-return/sha256.json') == reuse['parent_recovery_manifest_sha256']\nfor name, digest in json.loads((Y / 'recovery-return/sha256.json').read_text()).items():\n    assert sha(Y / 'recovery-return' / name) == digest, name\nfor name, digest in (prior['sha256']",1)
save('deploy-ah.py',s)

for old,new in [('ag-reboot-check.py','ah-reboot-check.py'),('queue-ag-once.py','queue-ah-once.py'),('review-ag-install.py','review-ah-install.py')]:
 s=owned((ROOT/old).read_text())
 for a,b in [('spx-trial-20260930ag','spx-trial-20260930ah'),('105-ag','106-ah'),('AG selected','AH selected'),('prepared AG;','prepared AH;'),('ag_timers','ah_timers'),('4fe7d83a-37fd-4eb7-800c-850d2aa0885b',BID)]:s=s.replace(a,b)
 if old=='review-ag-install.py':
  start=s.index('script_names = ');end=s.index('\nfor name in script_names:',start)
  s=s[:start]+"script_names = ('prepare-ah.py', 'generate-ah.py', 'deploy-ah.py', 'review-ah-install.py', 'ah-finalize.py', 'queue-ah-once.py', 'ah-reboot-check.py', 'review-ah-result.py', 'RESULT-20260930ag.md', 'AUDIO-AFTER-AG-20260930.md', 'archive-ag-return.py')"+s[end:]
 s=s.replace('Select AG once after verified AF fallback return','Select AH once after verified AG fallback return').replace('Recheck AF selection','Recheck AH selection').replace("Verify AB's DT-only installation and preserve AA preboot state", "Verify AH exact artifact reuse and preserve known-good preboot state")
 save(new,s)

for old,new in [('ag-finalize.py','ah-finalize.py'),('review-ag-result.py','review-ah-result.py')]:
 s=owned((ROOT/old).read_text())
 s=s.replace('wcd934x.spx_wsa_en_pin=2','wcd934x.spx_wsa_en_pin=1')
 s=s.replace("get('spx_wsa_en_pin') == '2'", "get('spx_wsa_en_pin') == '1'").replace("'spx_wsa_en_pin': '2'", "'spx_wsa_en_pin': '1'")
 s=s.replace('direction == 0x04 and value == 0x1c','direction == 0x02 and value == 0x1a').replace("{'0042': 4, '0043': 28}","{'0042': 2, '0043': 26}").replace('SPX: forced wcd-gpio pin 2 output-high','SPX: forced wcd-gpio pin 1 output-high')
 s=s.replace('slot=1 decoded=0217:2110 unique=4','slot=1 decoded=0217:2110 unique=3')
 s=s.replace("right = sdw_slaves.get('sdw:0:0:0217:2110:00:4'", "left = sdw_slaves.get('sdw:0:0:0217:2110:00:3'").replace("right = sdw.get('sdw:0:0:0217:2110:00:4'", "left = sdw.get('sdw:0:0:0217:2110:00:3'")
 s=s.replace('right.get(', 'left.get(').replace("endswith('/speaker@0,4')", "endswith('/speaker@0,3')").replace('right firmware identity matching','left firmware identity matching')
 s=s.replace('wsa881x-codec sdw:0:0:0217:2110:00:4: SPX: initializing','wsa881x-codec sdw:0:0:0217:2110:00:3: SPX: initializing').replace('right_init','left_init').replace('right_wsa_cold_init_markers','left_wsa_cold_init_markers')
 s=s.replace('pin2_diagnostic','pin1_diagnostic').replace('pin2_enumeration_diagnostic','pin1_enumeration_diagnostic')
 s=s.replace('Archive AG right firmware matching','Archive AH corrected-topology pin1 control').replace("Rehash AG's right firmware matching", "Rehash AH's corrected-topology pin1 control")
 save(new,s)
print('Generated six AH helpers; exact AE kernel/initramfs and AG DTB retained; no boot selected')
