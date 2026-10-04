#!/usr/bin/python3
"""Archive exact AM artifacts only after its verified actual hardware pass."""
import json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from am_boot_guard import BASE, X as P, load, recovery, artifacts, files, links, sha, command
os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
X = BASE/'attempts/20261002an'
a = load()
bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
review = json.loads((P/'independent-result-review.json').read_text())
assert bid == review['boot_id'] == '6dfad462-25b7-4e5e-90fc-3bd18c1c3095'
assert review['scoped_passed'] and review['fallback_stopped'] and not review['scoped_failure_reasons']
assert os.uname().release == a['release']
assert Path('/proc/cmdline').read_text().split() == ['BOOT_IMAGE=/spx-trial-20261001am/vmlinuz'] + a['cmdline'].split()
assert not recovery(a).get('next_entry', '')
artifacts(a)
assert command('systemctl','show','spx-am-fallback.timer','-p','ActiveState','--value') != 'active'
assert not X.exists()
manifests = {}
for n in ('final-result', 'post-result-records', 'startup-discovery', 'boot-transition-review'):
    root = P/n
    h = json.loads((root/'sha256.json').read_text())
    assert files(root) == h | {'sha256.json':sha(root/'sha256.json')}
    manifests[n] = sha(root/'sha256.json')
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO,env=os.environ | {'GIT_OPTIONAL_LOCKS':'0'}) == (P/'build/source.diff').read_bytes()
assert sha(REPO/'.config') == sha(P/'build/artifacts/.config')
assert files(P/'build') == json.loads((P/'build-sha256.json').read_text())
assert links(P/'build') == json.loads((P/'build-symlinks.json').read_text())
assert files(P/'dtb-build') == json.loads((P/'dtb-sha256.json').read_text())
X.mkdir(mode=0o700)
for n in ('build', 'dtb-build'):
    shutil.copytree(P/n, X/n, symlinks=True)
for n in ('build-sha256.json', 'build-symlinks.json', 'dtb-sha256.json', 'working-recovery.json'):
    shutil.copy2(P/n, X/n)
assert files(X/'build') == json.loads((X/'build-sha256.json').read_text())
assert links(X/'build') == json.loads((X/'build-symlinks.json').read_text())
assert files(X/'dtb-build') == json.loads((X/'dtb-sha256.json').read_text())
report = json.loads((P/'archive-review.json').read_text())
report.update(attempt='20261002an', preboot_id=bid, preboot_cmdline=Path('/proc/cmdline').read_text().strip(), parent_attempt='20261001am', parent_attempt_definition_sha256=sha(P/'attempt.json'), parent_result_review_sha256=sha(P/'independent-result-review.json'), parent_manifests_sha256=manifests, functional_delta='none; exact AM artifacts/source/config/selectors; attempt marker only', comparison='Direct AM -> AN handoff after independently verified AM pass', parent_archive_review_sha256=sha(P/'archive-review.json'), parent_touch_review_sha256=sha(P/'touch-startup-review.json'), boot_selected=False, deployed=False, playback_requested=False, callback_executed_on_hardware=False)
report['parent_post_result_manifest_sha256'] = manifests['post-result-records']
report['parent_result_manifest_sha256'] = manifests['final-result']
report['inherited_source_quiesce_review_manifest_sha256'] = report.pop('parent_reboot_quiesce_review_manifest_sha256')
(X/'archive-review.json').write_text(json.dumps(report,indent=2)+'\n')
shutil.copy2(__file__, X/'prepare-an.py')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
os.sync()
print(json.dumps(report,indent=2))
