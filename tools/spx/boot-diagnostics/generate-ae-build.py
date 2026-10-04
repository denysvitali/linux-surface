#!/usr/bin/python3
"""Generate AE's distinct build/assembly/archive helpers; no deployment."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent
BID = '86c3ff68-09a9-480c-9288-be9443254378'

def save(name, text):
    with (ROOT / name).open('x') as stream:
        stream.write(text)

text = (ROOT / 'build-aa.py').read_text()
text = text.replace('20260930aa', '20260930ae').replace('e0479717-1fe0-4a8f-a6ac-af198c4b703a', BID)
text = text.replace('Build the AA identity diagnostic from a pinned source/config snapshot once.', 'Build AE with eight diagnostic startup windows from a pinned snapshot once.')
text = text.replace("sources = ['sound/soc/codecs/wsa881x.c',", "sources = ['sound/soc/codecs/wsa881x.c',\n           'drivers/hid/spi-hid/spi-hid-core.c',\n           'drivers/hid/spi-hid/spi-hid-core.h',")
text = text.replace('AUDIO-ENUM-DIAG-20260930.md', 'TOUCH-AFTER-AD-20260930.md')
text = text.replace("before = (repo / '.config').read_text()", "logger_review = json.loads((stage / 'logger-source-review.json').read_text())\nassert source_sha['drivers/hid/spi-hid/spi-hid-core.c'] == logger_review['driver_sha256']\nassert logger_review['native_object_compile_exit_code'] == 0 and logger_review['other_source_diff_chunks_unchanged']\nbefore = (repo / '.config').read_text()")
text = text.replace('2265cf525d5019c52979abe6717772c560342ab44e61e4a796786369f2a96b13', '370566cc36db9d0463ca543586379cd73bb24fd5078962051ee1d14f0a0826fe')
text = text.replace('-spx-mainline-20260927y', '-spx-mainline-20260930aa')
text = text.replace("'bounded_enum_diag_default_off': True", "'bounded_enum_diag_default_off': True, 'startup_diag_windows': 8, 'startup_diag_events_per_window': 48")
text = text.replace('AA kernel, DTB, and modules built', 'AE kernel, DTB, and modules built')
save('build-ae.py', text)

text = (ROOT / 'assemble-aa.py').read_text().replace('20260930aa', '20260930ae').replace('e0479717-1fe0-4a8f-a6ac-af198c4b703a', BID)
text = text.replace("assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()", "assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()")
text = text.replace('Stage AA modules and build its private, logged initramfs once.', 'Stage AE modules and build its private, logged initramfs once.')
save('assemble-ae.py', text)

text = (ROOT / 'archive-aa.py').read_text().replace('20260930aa', '20260930ae').replace('e0479717-1fe0-4a8f-a6ac-af198c4b703a', BID)
text = text.replace("Z = BASE / '20260930z'", "Z = BASE / '20260930ad'")
text = text.replace("assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()", "assert 'spx_attempt=20260930ad' in Path('/proc/cmdline').read_text().split()")
start = text.index("assert review['scoped_failure_reasons']")
end = text.index("verification = json.loads", start)
text = text[:start] + '''assert review['scoped_passed'] and review['fallback_stopped']
assert review['boot_id'] == BID and review['native_force_off_path_passed']
assert sha(Z / 'independent-result-review.json') == '0c4f9fc0bc955bc872443dbd23aea3fbebc405f04b15caa7d6bacc36dfcd2cb8'
assert sha(Z / 'touch-startup-review.json') == '40171a0ea05bcc5a16546ae01278fd395310ee29dcfb8710a9e4e98b9728cbb4'
assert not json.loads((Z / 'touch-startup-review.json').read_text())['clean_touch_startup']
for directory in ('final-result', 'post-result-records'):
    root = Z / directory
    hashes = json.loads((root / 'sha256.json').read_text())
    assert files(root) == hashes | {'sha256.json': sha(root / 'sha256.json')}
assert subprocess.check_output(['systemctl', 'show', 'spx-ad-fallback.timer', '-p', 'ActiveState', '--value'], text=True).strip() != 'active'
parent = json.loads((Z / 'attempt.json').read_text())
for name, digest in (parent['sha256'] | parent['recovery_sha256'] | parent['runtime_sha256']).items():
    assert sha(Path(name)) == digest, name
''' + text[end:]
text = text.replace('ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a', '97983ecc8fc9a940787e6550071b03d1d8b63ccee00e75f2d10f452f82d7a187')
text = text.replace('archive-aa.py', 'archive-ae.py')
text = text.replace("shutil.copytree(STAGE, AA / 'build', symlinks=True)", "shutil.copytree(STAGE, AA / 'build', symlinks=True)\nshutil.copytree(Z / 'dtb-build', AA / 'dtb-build', symlinks=True)\nshutil.copy2(Z / 'dtb-sha256.json', AA / 'dtb-sha256.json')\nassert files(AA / 'dtb-build') == json.loads((AA / 'dtb-sha256.json').read_text())")
text = text.replace("'dtb_exact_z': True", "'dtb_exact_ab': True")
text = text.replace("'dtb_exact_ab': True, 'bounded_enum_diag_parameter_present': True,", "'dtb_exact_ab': True, 'bounded_enum_diag_parameter_present': True,\n          'dtb_manifest_sha256': sha(AA / 'dtb-sha256.json'),\n          'dtb_files_verified': len(files(AA / 'dtb-build')),")
text = text.replace("'parent_recovery_manifest_sha256': sha(Z / 'recovery-result/sha256.json')", "'parent_touch_review_sha256': sha(Z / 'touch-startup-review.json'),\n          'parent_post_result_manifest_sha256': sha(Z / 'post-result-records/sha256.json'),\n          'startup_diag_windows': 8, 'startup_diag_events_per_window': 48,\n          'startup_diag_record_lifetime_limit': 384, 'functional_policy_unchanged': True")
text = text.replace("Archive AA's verified diagnostic build without installing boot files.", "Archive AE's verified later-startup diagnostic build without installing boot files.")
save('archive-ae.py', text)
print('Generated AE build, assembly and archive helpers; no build or boot selected')
