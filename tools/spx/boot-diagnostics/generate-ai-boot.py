#!/usr/bin/python3
"""Generate AI's distinct silent right-side diagnostic installation and judges."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
BID='b1485998-0a40-46b7-bd77-88796fa99a89'
def save(n,s):
 with (ROOT/n).open('x') as f:f.write(s)
s=(ROOT/'deploy-ae.py').read_text().replace('20260930ae','20260930ai').replace('20260930ad','20260930ah').replace('86c3ff68-09a9-480c-9288-be9443254378',BID)
for a,b in [('spx-ad-','spx-ah-'),('spx-ae-','spx-ai-'),('103-ae','107-ai'),('ae-finalize.py','ai-finalize.py'),('ae-reboot-check.py','ai-reboot-check.py'),('custom-before-ae','custom-before-ai'),('custom.cfg.ae-new','custom.cfg.ai-new'),('attempt-ae.new','attempt-ai.new')]:s=s.replace(a,b)
s=s.replace('20260930aa+','20260930ae+').replace('dtb_exact_ab','dtb_exact_ag')
s=s.replace('SPI_HID_DIAG_WINDOWS4->8 only','default-off software command history only')
s=s.replace("cmdline = prior['cmdline'].replace('spx_attempt=20260930ah', 'spx_attempt=20260930ai')", "cmdline = prior['cmdline'].replace('spx_attempt=20260930ah', 'spx_attempt=20260930ai').replace('wcd934x.spx_wsa_en_pin=1', 'wcd934x.spx_wsa_en_pin=2') + ' soundwire_qcom.spx_cmd_diag=1'")
s=s.replace("{'spx_attempt=20260930ai'}", "{'spx_attempt=20260930ai', 'wcd934x.spx_wsa_en_pin=2', 'soundwire_qcom.spx_cmd_diag=1'}")
s=s.replace("{'spx_attempt=20260930ah'}", "{'spx_attempt=20260930ah', 'wcd934x.spx_wsa_en_pin=1'}")
s=s.replace('Authorized one-shot AD silent touch startup metadata trial','Authorized one-shot AH silent corrected-topology pin1 control').replace('Authorized one-shot AE silent later-startup metadata trial','Authorized one-shot AI silent right command-history diagnostic')
s=s.replace('/spx-trial-20260930aa/vmlinuz','/spx-trial-20260930ae/vmlinuz').replace('/spx-trial-20260930aa/initramfs.img','/spx-trial-20260930ae/initramfs.img').replace('/spx-trial-20260930ab/spx.dtb','/spx-trial-20260930ag/spx.dtb')
s=s.replace('Distinct startup logger windows4->8; exact AB DTB and AD selectors; no playback','Distinct default-off command history; exact AG DTB; pin2/native0; no playback').replace('silent later-startup metadata','silent right command-history diagnostic')
s=re.sub(r'\bAE\b','AI',s).replace('os.umask(0o077)',"os.umask(0o077)\nos.environ['GIT_OPTIONAL_LOCKS']='0'")
save('deploy-ai.py',s)

for old,new in [('ah-reboot-check.py','ai-reboot-check.py'),('queue-ah-once.py','queue-ai-once.py'),('review-ah-install.py','review-ai-install.py')]:
 s=(ROOT/old).read_text().replace('20260930ah','20260930ai').replace('spx-ah-','spx-ai-').replace('106-ah','107-ai').replace('prepared AH;','prepared AI;').replace('AH selected','AI selected').replace('43efd328-c5ba-48bf-9edf-797ccf268b1f',BID)
 s=s.replace("== '6.18.3-1-surface+'", "== '7.3.0-rc2-spx-mainline-20260930ae+'").replace("'spx_boot=known-good' in", "'spx_attempt=20260930ah' in")
 if old=='review-ah-install.py':
  s=s.replace("RELEASE = '7.3.0-rc2-spx-mainline-20260930ae+'", "RELEASE = '7.3.0-rc2-spx-mainline-20260930ai+'").replace("(X / 'dtb-build/source.diff')", "(X / 'build/source.diff')")
  start=s.index('script_names = ');end=s.index('\nfor name in script_names:',start)
  s=s[:start]+"script_names = ('prepare-ai-build.py', 'build-ai.py', 'assemble-ai.py', 'archive-ai.py', 'review-ai-build.py', 'retire-unused-backup-for-ai.py', 'generate-ai-boot.py', 'deploy-ai.py', 'review-ai-install.py', 'ai-finalize.py', 'queue-ai-once.py', 'ai-reboot-check.py', 'review-ai-result.py', 'RESULT-20260930ah.md', 'AUDIO-AFTER-AH-20260930.md', 'COMMAND-HISTORY-20260930.md')"+s[end:]
 s=s.replace('Select AH once after verified AG fallback return','Select AI once after verified AH result and distinct build').replace('ah_timers','ai_timers').replace('Verify AH exact artifact reuse and preserve known-good preboot state','Verify AI distinct artifacts and preserve AH preboot state')
 s=s.replace('os.umask(0o077)',"os.umask(0o077)\nos.environ['GIT_OPTIONAL_LOCKS']='0'")
 save(new,s)

# Pure bounded classifier, embedded identically in collector and independent reviewer.
parser='''def command_history_summary(kernel, params):
    lines = [line.split('SPX cmd diag ', 1)[1] for line in kernel.splitlines()
             if 'qcom-soundwire' in line and 'SPX cmd diag ' in line]
    dumps, malformed = [], []
    header = re.compile(r'history count=(\\d+) submission-only')
    record = re.compile(r'seq=(\\d+) submitted_ns=(\\d+) op=([RW]) packed=([0-9a-f]{8}) bridge_rc=(-?\\d+)')
    for line in lines:
        h, r = header.fullmatch(line), record.fullmatch(line)
        if h:
            dumps.append({'declared_count': int(h[1]), 'records': []})
        elif r and dumps:
            packed = int(r[4], 16)
            dumps[-1]['records'].append({'sequence': int(r[1]), 'submitted_ns': int(r[2]),
                'op': r[3], 'packed': r[4], 'bridge_rc': int(r[5]),
                'address': packed & 0xffff, 'command_id': (packed >> 16) & 15,
                'device_number': (packed >> 20) & 15, 'data_or_length': packed >> 24})
        else:
            malformed.append(line)
    good = not malformed and len(dumps) <= 2 and len(lines) <= 34
    for d in dumps:
        rs = d['records']
        good = good and 1 <= d['declared_count'] <= 16 and len(rs) == d['declared_count']
        good = good and all(b['sequence'] == a['sequence'] + 1 and
                            b['submitted_ns'] >= a['submitted_ns'] for a, b in zip(rs, rs[1:]))
    return {'enabled': params.get('spx_cmd_diag') == 'Y', 'well_formed': bool(good),
            'line_count': len(lines), 'dumps': dumps, 'malformed_lines': malformed,
            'maximum_lines': 34, 'hardware_acknowledgment_verified': False}


'''
for old,new in [('ag-finalize.py','ai-finalize.py'),('review-ag-result.py','review-ai-result.py')]:
 s=(ROOT/old).read_text().replace('20260930ag','20260930ai').replace('20260930ae','20260930ai').replace('spx-ag-','spx-ai-')
 pos=s.index('def sha(');s=s[:pos]+parser+s[pos:]
 if old=='ag-finalize.py':
  s=s.replace("'soundwire_qcom.spx_enum_diag=1', 'spi_hid.startup_diag=1']", "'soundwire_qcom.spx_enum_diag=1', 'soundwire_qcom.spx_cmd_diag=1', 'spi_hid.startup_diag=1']")
  s=s.replace('    right_init = ', "    cmd_history = command_history_summary(kernel, swr_params)\n    cmd_diag_passed = cmd_history['enabled'] and cmd_history['well_formed']\n    right_init = ",1)
  s=s.replace('passed = (right_init >= 1 and', 'passed = (cmd_diag_passed and right_init >= 1 and',1)
  s=s.replace("(out / 'result.json').write_text", "(out / 'command-history.json').write_text(json.dumps(cmd_history, indent=2) + '\\n')\n    (out / 'result.json').write_text",1)
  s=s.replace("'right_wsa_cold_init_markers': right_init,", "'right_wsa_cold_init_markers': right_init,\n              'command_diagnostic_passed': cmd_diag_passed,\n              'command_history': cmd_history,")
  s=s.replace('Archive AG right firmware matching','Archive AI right command-history diagnostic')
 else:
  s=s.replace('expected_pass = ', "cmd_history = command_history_summary(kernel, swr_params)\nassert json.loads((result_root / 'command-history.json').read_text()) == cmd_history == result['command_history']\ncmd_diag_passed = cmd_history['enabled'] and cmd_history['well_formed']\nassert result['command_diagnostic_passed'] == cmd_diag_passed\nexpected_pass = ",1)
  s=s.replace('expected_pass = (touch_diag_passed', 'expected_pass = (cmd_diag_passed and touch_diag_passed',1)
  s=s.replace("('bounded touch startup diagnostic', touch_diag_passed),", "('bounded command diagnostic', cmd_diag_passed),\n    ('bounded touch startup diagnostic', touch_diag_passed),",1)
  s=s.replace("'right_wsa_cold_init_markers': right_init,", "'right_wsa_cold_init_markers': right_init,\n          'command_diagnostic_passed': cmd_diag_passed,\n          'command_history': cmd_history,")
  s=s.replace("Rehash AG's right firmware matching", "Rehash AI's right command-history diagnostic")
 save(new,s)
print('Generated six AI helpers; strict AG right/native no-error scope preserved plus bounded diagnostic')
