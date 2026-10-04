#!/usr/bin/python3
"""Generate AF reuse helpers with explicit replacements; never select a boot."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
BID='1b26cb6c-0e7f-4a3b-a290-f3bf44a6855c'
def save(name,text):
 with (ROOT/name).open('x') as f:f.write(text)
def own(text):
 # Keep the AE release and payload paths: only attempt-owned names change.
 for old,new in [('attempts/20260930ae','attempts/20260930af'),
                 ('spx_attempt=20260930ae','spx_attempt=20260930af'),
                 ("ATTEMPT = '20260930ae'","ATTEMPT = '20260930af'"),
                 ("['attempt'] == '20260930ae'","['attempt'] == '20260930af'"),
                 ("'attempt': '20260930ae'","'attempt': '20260930af'"),
                 ('spx-ae-','spx-af-')]:text=text.replace(old,new)
 return text

s=(ROOT/'deploy-ad.py').read_text()
for old,new in [('20260930ac','20260930ae'),('20260930ad','20260930af'),
                ('spx-ac-','spx-ae-'),('spx-ad-','spx-af-'),
                ('102-ad','104-af'),('ad-finalize.py','af-finalize.py'),
                ('ad-reboot-check.py','af-reboot-check.py'),
                ('custom-before-ad','custom-before-af'),('custom.cfg.ad-new','custom.cfg.af-new'),
                ('attempt-ad.new','attempt-af.new'),('prepared AD;','prepared AF;')]:s=s.replace(old,new)
s=s.replace('2b761569-5b25-4ec5-a67e-f960c8fea28d',BID).replace('20260930aa+','20260930ae+')
s=s.replace("== '6.18.3-1-surface+'","== RELEASE")
s=s.replace("'spx_boot=known-good' in", "'spx_attempt=20260930ae' in")
s=s.replace("(Z / 'dtb-build/source.diff')", "(Z / 'build/source.diff')")
start=s.index('parent_review = ');end=s.index("for name, digest in (prior['sha256']",start)
s=s[:start]+'''parent_review = json.loads((Y / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']
assert parent_review['touch_startup_clean'] and parent_review['native_force_off_path_passed']
assert sha(Y / 'independent-result-review.json') == reuse['parent_result_review_sha256']
assert sha(Y / 'touch-startup-review.json') == reuse['parent_touch_review_sha256']
assert sha(Y / 'enumeration-word-review.json') == reuse['parent_enumeration_word_review_sha256']
assert sha(Y / 'final-result/sha256.json') == reuse['parent_result_manifest_sha256']
for name, digest in json.loads((Y / 'final-result/sha256.json').read_text()).items():
    assert sha(Y / 'final-result' / name) == digest, name
assert command('systemctl', 'show', 'spx-ae-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
''' + s[end:]
s=s.replace(".replace('spi_hid.startup_diag=0', 'spi_hid.startup_diag=1')", ".replace('wcd934x.spx_wsa_en_pin=1', 'wcd934x.spx_wsa_en_pin=2')")
s=s.replace("{'spx_attempt=20260930af', 'spi_hid.startup_diag=1'}", "{'spx_attempt=20260930af', 'wcd934x.spx_wsa_en_pin=2'}")
s=s.replace("{'spx_attempt=20260930ae', 'spi_hid.startup_diag=0'}", "{'spx_attempt=20260930ae', 'wcd934x.spx_wsa_en_pin=1'}")
s=s.replace('Authorized one-shot AC silent force-off native attachment trial', 'Authorized one-shot AE silent later-startup metadata trial')
s=s.replace('Authorized one-shot AD silent touch startup metadata trial', 'Authorized one-shot AF silent alternate-pin native enumeration trial')
s=s.replace('/spx-trial-20260930ab/spx.dtb','/spx-trial-20260930ae/spx.dtb').replace('/spx-trial-20260930aa/','/spx-trial-20260930ae/')
s=s.replace('Exact AC artifacts; startup_diag 0 -> 1; no PCM or playback','Exact AE artifacts; pin1 -> pin2; no PCM or playback')
s=s.replace('AD bounded touch metadata','AF silent alternate-pin enumeration').replace('AD silent touch startup metadata','AF silent alternate-pin enumeration').replace('AD installed with exact AC','AF installed with exact AE').replace('Description=AD ','Description=AF ')
save('deploy-af.py',s)

for old,new in [('ae-reboot-check.py','af-reboot-check.py'),('queue-ae-once.py','queue-af-once.py'),('review-ae-install.py','review-af-install.py')]:
 s=(ROOT/old).read_text()
 # These helpers refer to entry IDs as well as attempt-owned names, but never boot payloads.
 for a,b in [('20260930ae','20260930af'),('spx-ae-','spx-af-'),('103-ae','104-af'),('ae_timers','af_timers'),('AE selected once','AF selected once'),('prepared AE;','prepared AF;'),('AE selection','AF selection'),('AE installation','AF installation'),('AE selected','AF selected')]:s=s.replace(a,b)
 s=s.replace('20260930af+','20260930ae+').replace('20260930aa+','20260930ae+')
 s=s.replace('86c3ff68-09a9-480c-9288-be9443254378',BID).replace('spx_attempt=20260930ad','spx_attempt=20260930ae')
 s=s.replace('payloae_recovery','payload_recovery')
 s=s.replace('Select AE once from verified AD after archived fourth-open failure','Select AF once from verified AE after a clean logged boot')
 if old=='review-ae-install.py':
  start=s.index('script_names = ');end=s.index('\nfor name in script_names:',start)
  s=s[:start]+"script_names = ('prepare-af.py', 'generate-af.py', 'deploy-af.py', 'review-af-install.py', 'af-finalize.py', 'queue-af-once.py', 'af-reboot-check.py', 'review-af-result.py', 'RESULT-20260930ae.md', 'AUDIO-AFTER-AE-20260930.md')"+s[end:]
 save(new,s)

s=own((ROOT/'ae-finalize.py').read_text())
s=s.replace('wcd934x.spx_wsa_en_pin=1','wcd934x.spx_wsa_en_pin=2').replace("get('spx_wsa_en_pin') == '1'", "get('spx_wsa_en_pin') == '2'")
s=s.replace('direction == 0x02 and value == 0x1a','direction == 0x04 and value == 0x1c').replace('SPX: forced wcd-gpio pin 1 output-high','SPX: forced wcd-gpio pin 2 output-high')
s=s.replace('Archive AC attachment with force path off, without playback.', 'Archive AF alternate-pin native enumeration without playback.')
start=s.index('    # Refresh then copy')
s=s[:start]+'''    # A separate finding does not waive AE functional criteria or control fallback.
    paired = re.compile(r'SPX enum diag slot=(\\d+).*?rc=0/0 words=[0-9a-f]{8}/[0-9a-f]{8}\\n.*?SPX enum diag slot=\\1 decoded=0217:(?:2010|2110) unique=[34] version=[0-9a-f]+ class=[0-9a-f]+')
    pin2_diagnostic = (pin_state_passed and native_path_passed and
                       swr_params.get('spx_enum_diag') == 'Y' and
                       1 <= len(raw_trace) <= 8 and 1 <= len(decoded_trace) <= len(raw_trace) and
                       bool(paired.search('\\n'.join(raw_trace + decoded_trace))) and
                       power_path_passed and healthy and touch_diag_passed and
                       graph and wifi and touch and taint == '0')

'''+s[start:]
# Preserve the actual interleaved trace for pairing; the output file keeps its original format.
s=s.replace("paired.search('\\n'.join(raw_trace + decoded_trace))", "paired.search('\\n'.join(line for line in kernel.splitlines() if 'SPX enum diag slot=' in line))")
s=s.replace("'gpio_software_state_passed': pin_state_passed,", "'gpio_software_state_passed': pin_state_passed,\n              'pin2_enumeration_diagnostic_passed': pin2_diagnostic,\n              'pin2_diagnostic_controls_fallback': False,")
save('af-finalize.py',s)

s=own((ROOT/'review-ae-result.py').read_text())
s=s.replace("{'0042': 2, '0043': 26}","{'0042': 4, '0043': 28}").replace("'spx_wsa_en_pin': '1'","'spx_wsa_en_pin': '2'").replace('SPX: forced wcd-gpio pin 1 output-high','SPX: forced wcd-gpio pin 2 output-high')
s=s.replace("expected_pass = ",'''paired = re.compile(r'SPX enum diag slot=(\\d+).*?rc=0/0 words=[0-9a-f]{8}/[0-9a-f]{8}\\n.*?SPX enum diag slot=\\1 decoded=0217:(?:2010|2110) unique=[34] version=[0-9a-f]+ class=[0-9a-f]+')
trace = '\\n'.join(line for line in kernel.splitlines() if 'SPX enum diag slot=' in line)
pin2_diagnostic = (result['gpio_software_state_passed'] and native_path and
                   swr_params.get('spx_enum_diag') == 'Y' and
                   1 <= len(raw_trace) <= 8 and 1 <= len(decoded_trace) <= len(raw_trace) and
                   bool(paired.search(trace)) and power_pass and controller_pass and
                   touch_diag_passed and baseline)
assert result['pin2_enumeration_diagnostic_passed'] == pin2_diagnostic
assert result['pin2_diagnostic_controls_fallback'] is False
expected_pass = ''',1)
s=s.replace("'gpio_software_state_passed': result['gpio_software_state_passed'],", "'gpio_software_state_passed': result['gpio_software_state_passed'],\n          'pin2_enumeration_diagnostic_passed': pin2_diagnostic,\n          'pin2_diagnostic_controls_fallback': False,")
save('review-af-result.py',s)
print('Generated six AF helpers; exact AE payload paths preserved; no installation or selection')
