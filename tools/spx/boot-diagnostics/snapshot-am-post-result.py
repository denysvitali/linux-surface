#!/usr/bin/python3
"""Freeze independently reviewed AM records and source before any next deployment."""
import json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from am_boot_guard import X, load, recovery, artifacts, files, sha
os.umask(0o077)
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
a = load()
r = json.loads((X/'independent-result-review.json').read_text())
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == r['boot_id']
assert os.uname().release == a['release']
env = recovery(a)
assert not env.get('next_entry', '')
artifacts(a)
root = X/'final-result'
h = json.loads((root/'sha256.json').read_text())
assert files(root) == h | {'sha256.json':sha(root/'sha256.json')}
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO, env=os.environ | {'GIT_OPTIONAL_LOCKS':'0'}) == (X/'build/source.diff').read_bytes()
assert sha(REPO/'.config') == sha(X/'build/artifacts/.config')
out = X/'post-result-records'
assert not out.exists()
out.mkdir(mode=0o700)
for n in ('independent-result-review.json', 'touch-startup-review.json', 'ak-al-am-comparison.json', 'finalizer-action.json', 'actual-native-continuation-review.json', 'attempt.json', 'working-recovery.json'):
    shutil.copy2(X/n, out/n)
for n in ('RESULT-20261001am.md', 'review-am-touch.py', 'compare-am-startup.py', 'snapshot-am-post-result.py', 'review-am-transition.py', 'snapshot-am-startup.py'):
    shutil.copy2(REPO/'tools/spx/boot-diagnostics'/n, out/n)
for n in ('LOCAL-PROGRESS.md', '.config', 'drivers/hid/spi-hid/spi-hid-core.c', 'drivers/hid/spi-hid/spi-hid-core.h', 'sound/soc/codecs/wsa881x.c', 'drivers/soundwire/qcom.c', 'arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi'):
    dst = out/'source'/n
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO/n, dst)
shutil.copy2(X/'build/source.diff', out/'source.diff')
h = files(out)
(out/'sha256.json').write_text(json.dumps(h, indent=2)+'\n')
assert files(out) == h | {'sha256.json':sha(out/'sha256.json')}
os.sync()
print(json.dumps(dict(files_verified=len(h), manifest_sha256=sha(out/'sha256.json')), indent=2))
