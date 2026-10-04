#!/usr/bin/python3
"""Create AD helpers from frozen AC guards; does not install or select a boot."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BID = '2b761569-5b25-4ec5-a67e-f960c8fea28d'

def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)

def save(name, text):
    with (ROOT / name).open('x') as stream:
        stream.write(text)

text = (ROOT / 'prepare-ac.py').read_text()
# Preserve the kernel release AA and actual AB DTB paths.
text = text.replace("AB=BASE/'20260930ab'; AC=BASE/'20260930ac'", "AB=BASE/'20260930ac'; AC=BASE/'20260930ad'")
text = text.replace('094a2a10-d6cd-4e86-ba50-dd99bff8c6dd', BID)
text = once(text, "assert cmd('uname','-r')==RELEASE", "assert cmd('uname','-r')=='6.18.3-1-surface+'")
text = once(text, "assert 'spx_attempt=20260930ab' in Path('/proc/cmdline').read_text().split()", "assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()")
start = text.index("review=json.loads((AB/'independent-result-review.json').read_text())")
end = text.index("env=cmd('grub-editenv'", start)
text = text[:start] + '''review=json.loads((AB/'independent-result-review.json').read_text())
assert review['boot_id']=='ef072ab7-3596-41c1-bf4f-ff4a5164737f'
assert not review['scoped_passed'] and not review['fallback_stopped']
assert review['native_force_off_path_passed']
assert review['scoped_failure_reasons']==['graphics/Wi-Fi/touch baseline']
assert sha(AB/'independent-result-review.json')=='bebcec4f022e23588d1162748e2991c1c43000b90f357c483ca309b24e0bb84e'
result=json.loads((AB/'final-result/result.json').read_text())
assert not result['spi_hid_ready'] and result['fd680_renderer'] and result['wifi_connected']
for directory in ('final-result','recovery-return','touch-failure-snapshot'):
 root=AB/directory
 assert files(root)==json.loads((root/'sha256.json').read_text())|{'sha256.json':sha(root/'sha256.json')}
recovery=json.loads((AB/'recovery-return/report.json').read_text())
assert recovery['recovery_boot_id']==BID and recovery['userspace_fallback_return_verified']
assert sha(AB/'recovery-return/sha256.json')=='739c6264c1762499f014b692c947c0519823c7c848ee9f72064ceb5ec0e404d9'
assert cmd('systemctl','show','spx-ac-fallback.timer','-p','ActiveState','--value')!='active'
''' + text[end:]
text = once(text, "'attempt':'20260930ac'", "'attempt':'20260930ad'")
text = text.replace('Exact AB payloads; only force_attach 1 -> 0 and attempt marker', 'Exact AC payloads; only startup_diag 0 -> 1 and attempt marker')
text = once(text, "'boot_selected':False,'playback_requested':False", "'prior_recovery_manifest_sha256':sha(AB/'recovery-return/sha256.json'),\n 'boot_selected':False,'playback_requested':False")
text = text.replace("('prepare-ac.py','AUDIO-AFTER-AB-20260930.md','RESULT-20260930ab.md')", "('prepare-ad.py','generate-ad.py','AUDIO-AFTER-AC-20260930.md','RESULT-20260930ac.md','archive-ac-return.py')")
text = text.replace('Archive exact AB artifacts for the one-selector AC native attachment trial.', 'Archive exact AC artifacts for AD after verified failed-touch return.')
save('prepare-ad.py', text)

text = (ROOT / 'deploy-ac.py').read_text()
text = text.replace("Y = BASE / 'attempts/20260930ab'", "Y = BASE / 'attempts/20260930ac'")
text = text.replace("Z = BASE / 'attempts/20260930ac'", "Z = BASE / 'attempts/20260930ad'")
text = text.replace('094a2a10-d6cd-4e86-ba50-dd99bff8c6dd', BID)
text = once(text, "assert command('uname', '-r') == RELEASE", "assert command('uname', '-r') == '6.18.3-1-surface+'")
text = once(text, "assert 'spx_attempt=20260930ab' in Path('/proc/cmdline').read_text().split()", "assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()")
text = once(text, "assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']", "assert parent_review['boot_id'] == 'ef072ab7-3596-41c1-bf4f-ff4a5164737f'\nassert not parent_review['scoped_passed'] and not parent_review['fallback_stopped']\nassert parent_review['scoped_failure_reasons'] == ['graphics/Wi-Fi/touch baseline']\nassert parent_review['native_force_off_path_passed']\nrecovery = json.loads((Y / 'recovery-return/report.json').read_text())\nassert recovery['recovery_boot_id'] == BID and recovery['userspace_fallback_return_verified']\nassert sha(Y / 'recovery-return/sha256.json') == reuse['prior_recovery_manifest_sha256']\nfor name, digest in json.loads((Y / 'recovery-return/sha256.json').read_text()).items():\n    assert sha(Y / 'recovery-return' / name) == digest, name")
start = text.index("cmdline = prior['cmdline']")
end = text.index("preview = Z / 'entry.preview.cfg'", start)
text = text[:start] + '''cmdline = prior['cmdline'].replace('spx_attempt=20260930ac', 'spx_attempt=20260930ad').replace('spi_hid.startup_diag=0', 'spi_hid.startup_diag=1')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930ad', 'spi_hid.startup_diag=1'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930ac', 'spi_hid.startup_diag=0'}
entry = (Y / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260930ac', '--id spx-trial-20260930ad')
entry = entry.replace('set spx_diag_attempt=20260930ac', 'set spx_diag_attempt=20260930ad')
entry = entry.replace('SPX bounded boot diagnostic 20260930ac', 'SPX bounded boot diagnostic 20260930ad')
entry = entry.replace('Authorized one-shot AC silent force-off native attachment trial', 'Authorized one-shot AD silent touch startup metadata trial')
assert entry.count('--id spx-trial-20260930ad') == 1
assert entry.count('spi_hid.startup_diag=1') == 1
assert entry.count('soundwire_qcom.spx_force_attach=0') == 1
assert entry.count('devicetree /spx-trial-20260930ab/spx.dtb') == 1
assert entry.count('linux /spx-trial-20260930aa/vmlinuz') == 1
assert entry.count('initrd /spx-trial-20260930aa/initramfs.img') == 1
''' + text[end:]
# From this point all attempt references are AD; parent artifacts remain AC.
head, tail = text.split("preview = Z / 'entry.preview.cfg'", 1)
tail = tail.replace('20260930ac', '20260930ad').replace('ac-', 'ad-').replace('-ac', '-ad').replace('101-ad', '102-ad').replace('AC ', 'AD ')
tail = tail.replace('prepared AC;', 'prepared AD;').replace('exact AB payloads', 'exact AC payloads').replace('silent native attachment', 'silent touch startup metadata')
tail = tail.replace("'parent_attempt': '20260930ab'", "'parent_attempt': '20260930ac'")
tail = tail.replace('Exact AB artifacts; force_attach 1 -> 0; no PCM or playback', 'Exact AC artifacts; startup_diag 0 -> 1; no PCM or playback')
text = head + "preview = Z / 'entry.preview.cfg'" + tail
text = text.replace("'spx-ab-fallback.timer'", "'spx-ac-fallback.timer'")
text = text.replace('Install silent AC native attachment entry and bounded timers, unselected.', 'Install AD bounded touch metadata entry and timers, unselected.')
save('deploy-ad.py', text)

for old, new in (('ac-reboot-check.py', 'ad-reboot-check.py'),
                 ('queue-ac-once.py', 'queue-ad-once.py'),
                 ('review-ac-install.py', 'review-ad-install.py')):
    text = (ROOT / old).read_text().replace('20260930ac', '20260930ad').replace('spx-ac-', 'spx-ad-').replace('101-ac', '102-ad').replace('ac_', 'ad_').replace('AC ', 'AD ')
    text = text.replace('prepared AC;', 'prepared AD;')
    text = text.replace('094a2a10-d6cd-4e86-ba50-dd99bff8c6dd', BID)
    text = text.replace("assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260930aa+'", "assert command('uname', '-r') == '6.18.3-1-surface+'")
    text = text.replace("assert 'spx_attempt=20260930ab' in Path('/proc/cmdline').read_text().split()", "assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()")
    text = text.replace('prepare-ac.py', 'prepare-ad.py').replace('deploy-ac.py', 'deploy-ad.py').replace('review-ac-install.py', 'review-ad-install.py').replace('ac-finalize.py', 'ad-finalize.py').replace('queue-ac-once.py', 'queue-ad-once.py').replace('ac-reboot-check.py', 'ad-reboot-check.py').replace('review-ac-result.py', 'review-ad-result.py')
    text = text.replace('Recheck AB selection and artifact hashes immediately before reboot.', 'Recheck AD selection and artifact hashes immediately before reboot.')
    text = text.replace('Select reviewed silent AB identity matching trial once from verified AA.', 'Select AD once from verified known-good after archived AC touch failure.')
    text = text.replace("Verify AB's DT-only installation and preserve AA preboot state.", "Verify AD installation and preserve known-good preboot state.")
    # Install reviewer retains AA as the module release, independent of live recovery release.
    save(new, text)

text = (ROOT / 'ac-finalize.py').read_text().replace('20260930ac', '20260930ad').replace('spx-ac-', 'spx-ad-')
text = once(text, "'soundwire_qcom.spx_enum_diag=1']", "'soundwire_qcom.spx_enum_diag=1', 'spi_hid.startup_diag=1']")
anchor = "    passed = (native_path_passed"
idx = text.index(anchor)
addition = '''    # Existing bounded SPI-HID logger: no additional device transfers here.
    touch_params = readable_parameters(Path('/sys/module/spi_hid/parameters'))
    touch_state = {}
    for name in ('ready', 'bus_error_count', 'logic_error_count',
                 'regulator_error_count', 'device_initiated_reset_count'):
        field = touch_path.parent / name
        try:
            touch_state[name] = field.read_text().strip()
        except OSError as error:
            touch_state[name] = {'read_errno': error.errno}
    touch_diag = [line for line in kernel.splitlines()
                  if 'spi_hid spi0.0:' in line and 'startup-diag:' in line]
    touch_windows = {}
    for line in touch_diag:
        m = re.search(r'startup-diag: window=(\\d+) event=([a-z-]+)', line)
        if m:
            touch_windows.setdefault(m.group(1), []).append(m.group(2))
    touch_diag_passed = (touch_params.get('startup_diag') == 'Y' and
                         1 <= len(touch_diag) <= 192 and
                         sum(map(len, touch_windows.values())) == len(touch_diag) and
                         1 <= len(touch_windows) <= 4 and
                         all(1 <= int(w) <= 4 and len(events) <= 48 and
                             events[0] == 'begin' and events.count('begin') == 1
                             for w, events in touch_windows.items()))
''' 
text = text[:idx] + addition + text[idx:]
text = once(text, 'passed = (native_path_passed and', 'passed = (touch_diag_passed and native_path_passed and')
text = once(text, "    (out / 'gpio').write_text(gpio)", "    (out / 'gpio').write_text(gpio)\n    (out / 'touch-state.json').write_text(json.dumps(touch_state, indent=2) + '\\n')\n    (out / 'touch-params.json').write_text(json.dumps(touch_params, indent=2) + '\\n')\n    (out / 'touch-startup.log').write_text('\\n'.join(touch_diag) + '\\n')\n    (out / 'input-devices').write_text(Path('/proc/bus/input/devices').read_text())\n    (out / 'iptsd-state').write_text(command('systemctl', 'show', 'iptsd@*.service', '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts'))")
text = once(text, "'passed_scoped_baseline': passed,", "'passed_scoped_baseline': passed,\n              'touch_startup_diagnostic_passed': touch_diag_passed,\n              'touch_startup_diagnostic_lines': len(touch_diag),\n              'touch_startup_windows': touch_windows,\n              'touch_state': touch_state,\n              'touch_diagnostic_limit_windows': 4,\n              'touch_diagnostic_limit_events_per_window': 48,")
save('ad-finalize.py', text)

text = (ROOT / 'review-ac-result.py').read_text().replace('20260930ac', '20260930ad')
text = text.replace("Rehash and interpret AA's silent identity boot result.", "Rehash AD's native attachment and bounded touch diagnostic result.")
idx = text.index('expected_pass = (native_path')
addition = '''touch_params = json.loads((result_root / 'touch-params.json').read_text())
touch_lines = [line for line in kernel.splitlines()
               if 'spi_hid spi0.0:' in line and 'startup-diag:' in line]
windows = {}
for line in touch_lines:
    fields = dict(re.findall(r'([a-z-]+)=([a-z0-9-]+)', line))
    assert 'window' in fields and 'event' in fields
    windows.setdefault(fields['window'], []).append(fields['event'])
touch_diag_passed = (touch_params.get('startup_diag') == 'Y' and
                     1 <= len(touch_lines) <= 192 and 1 <= len(windows) <= 4 and
                     all(1 <= int(w) <= 4 and len(events) <= 48 and events[0] == 'begin'
                         and events.count('begin') == 1 for w, events in windows.items()))
assert result['touch_startup_diagnostic_passed'] == touch_diag_passed
assert result['touch_startup_diagnostic_lines'] == len(touch_lines)
assert result['touch_startup_windows'] == windows
assert result['touch_diagnostic_limit_windows'] == 4 and result['touch_diagnostic_limit_events_per_window'] == 48
assert (result_root / 'touch-startup.log').read_text() == '\\n'.join(touch_lines) + '\\n'
touch_state = json.loads((result_root / 'touch-state.json').read_text())
assert result['touch_state'] == touch_state
assert result['spi_hid_ready'] == (touch_state.get('ready') == 'ready')
'''
text = text[:idx] + addition + text[idx:]
text = once(text, 'expected_pass = (native_path and', 'expected_pass = (touch_diag_passed and native_path and')
text = once(text, "    ('GPIO software state',", "    ('bounded touch startup diagnostic', touch_diag_passed),\n    ('GPIO software state',")
text = once(text, "'scoped_failure_reasons': reasons,", "'scoped_failure_reasons': reasons,\n          'touch_startup_diagnostic_passed': touch_diag_passed,\n          'touch_startup_diagnostic_lines': len(touch_lines),\n          'touch_startup_windows': windows,")
save('review-ad-result.py', text)
print('Generated seven AD helpers; AC scripts untouched; no installation or selection')
