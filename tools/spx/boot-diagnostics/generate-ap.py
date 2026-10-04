#!/usr/bin/python3
"""Derive AP identity-only collection and guards from reviewed AO source."""
import ast,re
from pathlib import Path
src=Path(__file__).resolve().parent

def identity(text):
    for old,new in (('20261002ao','20261002ap'),('spx-ao-','spx-ap-'),('ao_boot_guard','ap_boot_guard'),('ao-finalize','ap-finalize'),('ao-return','ap-return'),('ao-reboot','ap-reboot'),('-ao.py','-ap.py'),('-ao-','-ap-'),('-ao.','-ap.'),('.ao-new','.ap-new'),('.ao-queue-new','.ap-queue-new'),('113-ap-exclude','114-ap-exclude')):
        text=text.replace(old,new)
    return re.sub(r'\bAO\b','AP',text)

for name in ('ao-finalize.py','review-ao-result.py','ao-return.py','ao-reboot-check.py','review-ao-handoff.py','verify-ao-boot-guards.py','check-ao-service-context.py','ao_boot_guard.py','queue-ao-once.py','review-ao-install.py'):
    target=name.replace('ao','ap') if name.startswith('ao') else name.replace('-ao','-ap')
    text=identity((src/name).read_text())
    if name in ('ao-reboot-check.py','review-ao-handoff.py'):
        text=text.replace('handoff attempt=20261001am','handoff attempt=20261002ao')
    if name=='ao_boot_guard.py':
        text=text.replace("p=BASE/'attempts/20261001am'", "p=BASE/'attempts/20261002ao'")
        text=text.replace("replace('spx_attempt=20261001am','spx_attempt=20261002ap')", "replace('spx_attempt=20261002ao','spx_attempt=20261002ap')+' ramoops.dyndbg=+p'")
        text=text.replace("count('spx_attempt=20261001am')", "count('spx_attempt=20261002ao')")
        text=text.replace("'spx-am-fallback.timer'","'spx-ao-fallback.timer'").replace("'spx-am-finalize.service'","'spx-ao-finalize.service'")
        old="assert subprocess.check_output(['git','-c','safe.directory='+str(repo),'diff','--binary','HEAD'],cwd=repo,env=os.environ|{'GIT_OPTIONAL_LOCKS':'0'})==(X/'build/source.diff').read_bytes()"
        assert old in text
        text=text.replace(old,"source_provenance(X/'source-provenance', X/'build/source.diff', repo)")
    if name=='verify-ao-boot-guards.py':
        text=text.replace('spx_attempt=20261001am','spx_attempt=20261002ao')
    if name=='review-ao-install.py':
        text=text.replace("for old,new in (('am-finalize.py','ap-finalize.py'),('review-am-result.py','review-ap-result.py')):","for old,new in (('ao-finalize.py','ap-finalize.py'),('review-ao-result.py','review-ap-result.py')):")
        start=text.index('    expected=(SRC/old)');end=text.index('\ndef assignment',start)
        text=text[:start]+"    expected=re.sub(r'\\bAO\\b','AP',(SRC/old).read_text().replace('20261002ao','20261002ap').replace('spx-ao-','spx-ap-'))\n    assert (SRC/new).read_text()==expected\n"+text[end:]
        text=text.replace('import ast, fcntl, json,','import ast, fcntl, json, re,')
        text=text.replace("SRC/'am-finalize.py'", "SRC/'ao-finalize.py'")
    ast.parse(text)
    assert not (src/target).exists(),target
    (src/target).write_text(text)
print('Ten AP helpers generated; original AO files unchanged.')
