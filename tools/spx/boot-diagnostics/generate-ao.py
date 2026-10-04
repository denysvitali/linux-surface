#!/usr/bin/python3
"""Derive fresh AO from unbooted AN; preserve AM payload/release and strict scope."""
from pathlib import Path
import ast
s=Path(__file__).resolve().parent
names=('prepare-an.py','deploy-an.py','an_boot_guard.py','an-return.py','an-reboot-check.py','an-finalize.py','review-an-result.py','review-an-install.py','verify-an-boot-guards.py','queue-an-once.py','review-an-handoff.py','freeze-an-prequeue.py')
for name in names:
    target=name.replace('an','ao') if name.startswith('an') else name.replace('-an','-ao')
    text=(s/name).read_text().replace('20261002an','20261002ao').replace('spx-an-','spx-ao-').replace('an_boot_guard','ao_boot_guard').replace('an-finalize','ao-finalize').replace('an-return','ao-return').replace('an-reboot','ao-reboot').replace('-an.py','-ao.py').replace('-an-','-ao-').replace('-an.','-ao.').replace('.an-new','.ao-new').replace('.an-queue-new','.ao-queue-new').replace('AN','AO').replace('112-ao-exclude','113-ao-exclude')
    # Git's sudo ownership exception is absent under systemd. Scope trust to this repo.
    text=text.replace("['git','diff','--binary','HEAD']", "['git','-c','safe.directory='+str("+('REPO' if name=='prepare-an.py' else 'repo')+"),'diff','--binary','HEAD']")
    if name in ('prepare-an.py','deploy-an.py'):
        text=text.replace('from am_boot_guard import BASE, X as P, load, recovery, artifacts, files, links, sha, command', 'from an_boot_guard import BASE, X as ABORTED, load, recovery, artifacts, files, links, sha, command\nP = BASE/\'attempts/20261001am\'')
        var='a' if name=='prepare-an.py' else 'prior'
        text=text.replace(var+' = load()', '''aborted = load()
assert (ABORTED/'reboot-check-failed-unqueued').read_text().strip() == aborted['preboot_id']
assert not (ABORTED/'reboot-check-passed.json').exists()
abort_root = ABORTED/'preboot-abort'
assert files(abort_root) == json.loads((abort_root/'sha256.json').read_text()) | {'sha256.json':sha(abort_root/'sha256.json')}
assert json.loads((abort_root/'report.json').read_text())['boot_occurred'] is False
assert not recovery(aborted).get('next_entry', '')
artifacts(aborted)
'''+var+" = json.loads((P/'attempt.json').read_text())")
        text=text.replace('artifacts('+var+')','''for path,digest in ('''+var+"['sha256'] | "+var+"['recovery_sha256'] | "+var+"['runtime_sha256']).items(): assert sha(path) == digest, path")
        if name=='deploy-an.py':
            text=text.replace("assert 'next_entry=' in command('grub-editenv','/boot/grub/grubenv','list').splitlines()", "assert not dict(line.split('=',1) for line in command('grub-editenv','/boot/grub/grubenv','list').splitlines() if '=' in line).get('next_entry','')")
    assert not (s/target).exists(), target
    ast.parse(text)
    (s/target).write_text(text)
print('Generated twelve AO scripts; AN retained unchanged.')
