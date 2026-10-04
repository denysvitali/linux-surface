#!/usr/bin/python3
"""Freeze reviewed AK result and its current corrected DT source after return."""
import hashlib, json, os, shutil, subprocess
from pathlib import Path
os.umask(0o077)
REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
RUN=Path('/var/lib/spx-boot-diagnostics/attempts/20260930ak')
OUT=RUN/'post-result-records'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(p): return {str(q.relative_to(p)):sha(q) for q in sorted(p.rglob('*')) if q.is_file() and not q.is_symlink()}
assert os.geteuid()==0 and not OUT.exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='db98e8ac-8aa3-44d4-8899-47c4fab5fb07'
assert subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO,env=os.environ|{'GIT_OPTIONAL_LOCKS':'0'})==(RUN/'build/source.diff').read_bytes()
assert sha(REPO/'.config')==sha(RUN/'build/artifacts/.config')
review=json.loads((RUN/'independent-result-review.json').read_text())
assert review['scoped_failure_reasons']==[]
assert review['scoped_passed'] and review['fallback_stopped']
assert review['firmware_identity_match_passed'] and review['codec_mechanism_passed']
root=RUN/'final-result';h=json.loads((root/'sha256.json').read_text())
assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}
OUT.mkdir(mode=0o700)
for name in ('independent-result-review.json','touch-startup-review.json','enumeration-word-review.json','command-history-review.json','ai-aj-ak-comparison.json','finalizer-action.json'):
 shutil.copy2(RUN/name,OUT/name)
for name in ('RESULT-20260930ak.md','AUDIO-AFTER-AK-20260930.md','review-ak-touch.py','review-ak-enumeration.py','review-ak-command-history.py','snapshot-ak-post-result.py'):
 shutil.copy2(REPO/'tools/spx/boot-diagnostics'/name,OUT/name)
shutil.copy2(RUN/'build/source.diff',OUT/'source.diff')
shutil.copy2(REPO/'.config',OUT/'config')
shutil.copy2(REPO/'sound/soc/codecs/wsa881x.c',OUT/'wsa881x-before.c')
shutil.copy2(REPO/'drivers/soundwire/qcom.c',OUT/'qcom-before.c')
shutil.copy2(REPO/'arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi',OUT/'sc8180x-wcd9340.dtsi')
h=files(OUT);(OUT/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
assert files(OUT)==h|{'sha256.json':sha(OUT/'sha256.json')}
os.sync();print(json.dumps({'files':len(h),'manifest_sha256':sha(OUT/'sha256.json')},indent=2))
