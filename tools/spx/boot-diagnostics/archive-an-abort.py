#!/usr/bin/python3
"""Preserve AN's fail-closed preboot abort without retrying its selection."""
import json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from an_boot_guard import X, load, preboot, files, sha, command
os.umask(0o077)
a = load()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == a['preboot_id']
assert (X/'reboot-requested').exists()
assert (X/'reboot-check-failed-unqueued').read_text().strip() == a['preboot_id']
for name in ('reboot-check-passed.json', 'grubenv.immediate-preboot.txt', 'outgoing-identity-marker.txt', 'final-result'):
    assert not (X/name).exists(), name
assert command('systemctl', 'show', 'spx-trial-20261002an-reboot.service', '-p', 'Result', '--value') == 'exit-code'
assert command('systemctl', 'show', 'spx-trial-20261002an-reboot.timer', '-p', 'ActiveState', '--value') != 'active'
preboot(a)
out = X/'preboot-abort'
assert not out.exists()
out.mkdir(mode=0o700)
for name in ('attempt.json', 'reboot-requested', 'reboot-check-failed-unqueued', 'queue-review.json', 'grubenv.queued.txt', 'reboot-check.py', 'installed-review.json', 'deployment-sources-sha256.json'):
    shutil.copy2(X/name, out/name)
shutil.copy2('/usr/local/lib/spx-boot-diagnostics/an_boot_guard.py', out/'an_boot_guard.py')
log = command('journalctl', '-b', '-u', 'spx-trial-20261002an-reboot.service', '-o', 'short-monotonic', '--no-pager')
assert 'parent_pass' in log and 'returned non-zero exit status 129' in log
(out/'guard-journal.log').write_text(log+'\n')
repo = '/home/dvitali/Documents/git/linux-surface-next'
# Run in the same manager context: no sudo caller identity inherited by Git.
checks = []
for fixed in (False, True):
    args = ['systemd-run', '--quiet', '--wait', '--pipe', '/usr/bin/git']
    if fixed:
        args += ['-c', 'safe.directory='+repo]
    args += ['-C', repo, 'diff', '--binary', 'HEAD']
    p = subprocess.run(args, capture_output=True, timeout=90)
    (out/('fixed' if fixed else 'original')).with_suffix('.stderr').write_bytes(p.stderr)
    if fixed:
        assert p.returncode == 0 and p.stdout == (X/'build/source.diff').read_bytes()
    else:
        assert p.returncode == 129 and b'Not a git repository' in p.stderr
    checks.append(dict(fixed=fixed, returncode=p.returncode, exact_archived_source_diff=fixed))
(out/'kernel.log').write_text(command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')+'\n')
(out/'grubenv.txt').write_text(command('grub-editenv', '/boot/grub/grubenv', 'list')+'\n')
report = dict(attempt=a['attempt'], actual_boot_id=a['preboot_id'], boot_occurred=False,
    selection_cleared=True, known_good_default=True, full_recovery_and_payloads_verified=True,
    reason='Git rejects worktree ownership in systemd root context without SUDO_UID',
    fix='Command-local safe.directory for this exact repository; retain byte-exact source validation',
    service_context_checks=checks, original_request_marker_retained=True, next_attempt='20261002ao')
(out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
shutil.copy2(__file__, out/Path(__file__).name)
h = files(out)
(out/'sha256.json').write_text(json.dumps(h, indent=2)+'\n')
assert files(out) == h | {'sha256.json':sha(out/'sha256.json')}
preboot(a)
os.sync()
print(json.dumps(report | dict(files_verified=len(h), manifest_sha256=sha(out/'sha256.json')), indent=2))
