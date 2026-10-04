#!/usr/bin/python3
"""Generate AE's guarded boot helpers; no installation or selection."""
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parent
BID = '86c3ff68-09a9-480c-9288-be9443254378'

def save(name, text):
    with (ROOT / name).open('x') as stream:
        stream.write(text)

text = (ROOT / 'deploy-aa.py').read_text().replace('20260930aa', '20260930ae').replace('spx-aa-', 'spx-ae-').replace('aa-', 'ae-').replace('-aa', '-ae').replace('99-ae', '103-ae').replace('AA ', 'AE ').replace('prepared AA;', 'prepared AE;')
text = text.replace('20260930z', '20260930ad').replace('e0479717-1fe0-4a8f-a6ac-af198c4b703a', BID)
text = text.replace("assert command('uname', '-r') == '6.18.3-1-surface+'", "assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260930aa+'")
text = text.replace("assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()", "assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()")
start = text.index("retired = AE") if 'retired = AE' in text else text.index("retired = AA")
end = text.index("preview = ", start)
text = text[:start] + '''parent_review = json.loads((Z / 'independent-result-review.json').read_text())
assert parent_review['boot_id'] == BID and parent_review['scoped_passed'] and parent_review['fallback_stopped']
assert sha(Z / 'independent-result-review.json') == archive['parent_result_review_sha256']
assert sha(Z / 'touch-startup-review.json') == archive['parent_touch_review_sha256']
assert archive['dtb_exact_ab'] and archive['functional_policy_unchanged']
assert archive['startup_diag_windows'] == 8 and archive['startup_diag_events_per_window'] == 48
assert command('systemctl', 'show', 'spx-ad-fallback.timer', '-p', 'ActiveState', '--value') != 'active'
for name, digest in (prior['sha256'] | prior['runtime_sha256']).items():
    assert sha(name) == digest, name
required_bytes = sum((AA / 'build' / name).stat().st_size for name in ('vmlinuz', 'initramfs.img')) + 1048576
space = os.statvfs('/boot')
assert space.f_bavail * space.f_frsize > required_bytes, 'insufficient /boot space'

cmdline = prior['cmdline'].replace('spx_attempt=20260930ad', 'spx_attempt=20260930ae')
assert set(cmdline.split()) - set(prior['cmdline'].split()) == {'spx_attempt=20260930ae'}
assert set(prior['cmdline'].split()) - set(cmdline.split()) == {'spx_attempt=20260930ad'}
entry = (Z / 'entry.cfg').read_text()
assert entry.count(' ' + prior['cmdline'] + '; then') == 1
entry = entry.replace(' ' + prior['cmdline'] + '; then', ' ' + cmdline + '; then')
entry = entry.replace('--id spx-trial-20260930ad', '--id spx-trial-20260930ae')
entry = entry.replace('set spx_diag_attempt=20260930ad', 'set spx_diag_attempt=20260930ae')
entry = entry.replace('SPX bounded boot diagnostic 20260930ad', 'SPX bounded boot diagnostic 20260930ae')
entry = entry.replace('Authorized one-shot AD silent touch startup metadata trial', 'Authorized one-shot AE silent later-startup metadata trial')
entry = entry.replace('/spx-trial-20260930aa/vmlinuz', '/spx-trial-20260930ae/vmlinuz')
entry = entry.replace('/spx-trial-20260930aa/initramfs.img', '/spx-trial-20260930ae/initramfs.img')
entry = entry.replace('/spx-trial-20260930ab/spx.dtb', '/spx-trial-20260930ae/spx.dtb')
assert entry.count('--id spx-trial-20260930ae') == 1
assert entry.count('spi_hid.startup_diag=1') == 1 and entry.count('soundwire_qcom.spx_force_attach=0') == 1
assert all(entry.count('/spx-trial-20260930ae/' + name) == 1 for name in ('vmlinuz', 'spx.dtb', 'initramfs.img'))
''' + text[end:]
text = text.replace('Distinct bounded existing-read enum logger; exact Z DTB and selectors; no playback', 'Distinct startup logger windows4->8; exact AB DTB and AD selectors; no playback')
text = text.replace('silent identity', 'silent later-startup metadata')
text = re.sub(r'\bAA\b', 'AE', text)
text = text.replace("assert sha(REPO / '.config') == archive['config_sha256']", "assert sha(REPO / '.config') == archive['config_sha256']\nbuild_review = json.loads((AE / 'independent-build-review.json').read_text())\nassert build_review['build_manifest_sha256'] == archive['build_manifest_sha256']\nassert build_review['driver_delta'] == 'SPI_HID_DIAG_WINDOWS4->8 only'\nassert build_review['config_delta'] == 'LOCALVERSION only'\nassert build_review['functional_driver_policy_unchanged'] and build_review['dtb_exact_ab']")
save('deploy-ae.py', text)

for old, new in (('ad-reboot-check.py', 'ae-reboot-check.py'), ('queue-ad-once.py', 'queue-ae-once.py'), ('review-ad-install.py', 'review-ae-install.py')):
    text = (ROOT / old).read_text().replace('20260930ad', '20260930ae').replace('spx-ad-', 'spx-ae-').replace('102-ad', '103-ae').replace('ad_timers', 'ae_timers').replace('AD ', 'AE ').replace('prepared AD;', 'prepared AE;')
    text = text.replace('2b761569-5b25-4ec5-a67e-f960c8fea28d', BID)
    text = text.replace("assert command('uname', '-r') == '6.18.3-1-surface+'", "assert command('uname', '-r') == '7.3.0-rc2-spx-mainline-20260930aa+'")
    text = text.replace("assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()", "assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()")
    if old == 'review-ad-install.py':
        text = text.replace("RELEASE = '7.3.0-rc2-spx-mainline-20260930aa+'", "RELEASE = '7.3.0-rc2-spx-mainline-20260930ae+'")
        text = text.replace("(X / 'dtb-build/source.diff').read_bytes()", "(X / 'build/source.diff').read_bytes()")
        start = text.index('script_names = ')
        end = text.index('\nfor name in script_names:', start)
        text = text[:start] + "script_names = ('build-ae.py', 'assemble-ae.py', 'archive-ae.py', 'review-ae-build.py', 'retire-unused-backup-for-ae.py', 'deploy-ae.py', 'review-ae-install.py', 'ae-finalize.py', 'queue-ae-once.py', 'ae-reboot-check.py', 'review-ae-result.py', 'generate-ae-boot.py', 'generate-ae-build.py')" + text[end:]
        text = text.replace('preserve known-good preboot state', 'preserve AD preboot state')
    text = text.replace('prepare-ad.py', 'build-ae.py').replace('deploy-ad.py', 'deploy-ae.py').replace('review-ad-install.py', 'review-ae-install.py').replace('ad-finalize.py', 'ae-finalize.py').replace('queue-ad-once.py', 'queue-ae-once.py').replace('ad-reboot-check.py', 'ae-reboot-check.py').replace('review-ad-result.py', 'review-ae-result.py')
    text = text.replace('from verified known-good after archived AC touch failure', 'from verified AD after archived fourth-open failure')
    save(new, text)

text = (ROOT / 'ad-finalize.py').read_text().replace('20260930ad', '20260930ae').replace('20260930aa', '20260930ae').replace('spx-ad-', 'spx-ae-')
text = text.replace('<= 192', '<= 384').replace('<= 4 and', '<= 8 and')
text = text.replace("'touch_diagnostic_limit_windows': 4", "'touch_diagnostic_limit_windows': 8")
text = text.replace("    (out / 'kernel.log').write_text(kernel)", "    (out / 'kernel.log').write_text(kernel)\n    (out / 'dmesg-raw.log').write_text(command('dmesg', '--raw'))")
text = text.replace("'touch_state': touch_state,", "'touch_state': touch_state,\n              'touch_startup_open_timeouts': kernel.count('spi_hid_ll_open: firmware did not become ready'),\n              'touch_startup_invalid_headers': kernel.count('Invalid input report sync constant'),\n              'touch_startup_clean': not any(x in kernel for x in ('spi_hid_ll_open: firmware did not become ready', 'Invalid input report sync constant', 'startup response polling timed out')),")
save('ae-finalize.py', text)
text = (ROOT / 'review-ad-result.py').read_text().replace('20260930ad', '20260930ae').replace('20260930aa', '20260930ae').replace("Rehash AD's", "Rehash AE's")
text = text.replace('<= 192', '<= 384').replace('<= 4 and', '<= 8 and')
text = text.replace("result['touch_diagnostic_limit_windows'] == 4", "result['touch_diagnostic_limit_windows'] == 8")
text = text.replace('expected_pass = ', "assert result['touch_startup_open_timeouts'] == kernel.count('spi_hid_ll_open: firmware did not become ready')\nassert result['touch_startup_invalid_headers'] == kernel.count('Invalid input report sync constant')\nassert result['touch_startup_clean'] == (not any(x in kernel for x in ('spi_hid_ll_open: firmware did not become ready', 'Invalid input report sync constant', 'startup response polling timed out')))\nexpected_pass = ", 1)
text = text.replace("'touch_startup_windows': windows,", "'touch_startup_windows': windows,\n          'touch_startup_clean': result['touch_startup_clean'],\n          'touch_startup_open_timeouts': result['touch_startup_open_timeouts'],\n          'touch_startup_invalid_headers': result['touch_startup_invalid_headers'],")
save('review-ae-result.py', text)
print('Generated six AE boot helpers; no installation or selection')
