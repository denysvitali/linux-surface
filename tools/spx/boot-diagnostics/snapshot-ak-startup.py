#!/usr/bin/python3
"""Freeze AK's startup chronology and read-only driver state before finalization."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

os.umask(0o077)
RUN = Path('/var/lib/spx-boot-diagnostics/attempts/20260930ak')
BID = 'db98e8ac-8aa3-44d4-8899-47c4fab5fb07'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=90)

assert os.geteuid() == 0
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
a = json.loads((RUN / 'attempt.json').read_text())
assert a == json.loads(Path('/var/lib/spx-boot-diagnostics/attempt.json').read_text())
assert Path('/proc/cmdline').read_text().split() == ['BOOT_IMAGE=/spx-trial-20260930ak/vmlinuz'] + a['cmdline'].split()
for name, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
    assert sha(name) == digest, name
assert cmd('uname', '-r').strip() == a['release']
assert cmd('systemctl', 'show', 'spx-ak-fallback.timer', '-p', 'ActiveState', '--value').strip() == 'active'
env = cmd('grub-editenv', '/boot/grub/grubenv', 'list')
assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
assert 'BootNext:' not in cmd('efibootmgr')
out = RUN / 'startup-discovery'
assert not out.exists()
out.mkdir(mode=0o700)
kernel = cmd('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
dmesg = cmd('dmesg', '--raw')
(out / 'kernel.log').write_text(kernel)
(out / 'dmesg-raw.log').write_text(dmesg)
(out / 'journal.log').write_text(cmd('journalctl', '-b', '-o', 'short-monotonic', '--no-pager'))
(out / 'interrupts').write_text(Path('/proc/interrupts').read_text())
(out / 'input-devices').write_text(Path('/proc/bus/input/devices').read_text())
(out / 'iptsd-state').write_text(cmd('systemctl', 'show', 'iptsd@*.service', '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts'))
(out / 'grubenv').write_text(env)
(out / 'cmdline').write_text(Path('/proc/cmdline').read_text())
(out / 'boot-id').write_text(BID + '\n')
with (out / 'kernel.export').open('wb') as stream:
    subprocess.run(['journalctl', '-b', '-k', '-o', 'export', '--no-pager'], stdout=stream, check=True, timeout=90)
state = {}
for name in ('ready', 'bus_error_count', 'regulator_error_count', 'logic_error_count', 'device_initiated_reset_count'):
    state[name] = (Path('/sys/bus/spi/devices/spi0.0') / name).read_text().strip()
params = {'startup_diag': Path('/sys/module/spi_hid/parameters/startup_diag').read_text().strip()}
assert params['startup_diag'] == 'Y'
windows = {}
for line in dmesg.splitlines():
    if 'spi_hid spi0.0: startup-diag:' not in line:
        continue
    fields = dict(re.findall(r'([a-z-]+)=([a-z0-9-]+)', line))
    windows.setdefault(fields['window'], []).append(fields | {'line': line})
assert 1 <= len(windows) <= 8 and all(1 <= int(n) <= 8 for n in windows)
assert sum(map(len, windows.values())) <= 384
assert all(len(events) <= 48 for events in windows.values())
summary = {}
for number, records in windows.items():
    summary[number] = {'record_count': len(records), 'terminal_event': records[-1]['event'],
                       'terminal_fields': {k: v for k, v in records[-1].items() if k != 'line'},
                       'accepted_reports': [int(r['value']) for r in records if r['event'] == 'report'],
                       'gated_irqs': [r for r in records if r['event'] == 'irq' and r['powered'] == '0'],
                       'powered_irqs': sum(r['event'] == 'irq' and r['powered'] == '1' for r in records)}
report = {'attempt': '20260930ak', 'boot_id': BID, 'uptime': Path('/proc/uptime').read_text().strip(),
          'touch_state': state, 'touch_params': params, 'startup_windows': summary,
          'diagnostic_records': sum(map(len, windows.values())),
          'open_timeouts': dmesg.count('spi_hid_ll_open: firmware did not become ready'),
          'no_live_restart_rebind_reset_or_pcm': True,
          'payload_recovery_runtime_files_verified': sum(map(len, (a['sha256'], a['recovery_sha256'], a['runtime_sha256']))),
          'limits': ['Ready state is a software observation; startup reliability requires more than one boot.',
                     'Logger is bounded to eight windows and48 records each; logging may affect timing.',
                     'Software gated IRQ does not establish usable firmware traffic or electrical rail state.',
                     'Raw dmesg/jiffies are retained because journal reception times can lag kernel records.']}
(out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
(out / 'windows.json').write_text(json.dumps(windows, indent=2) + '\n')
shutil_source = REPO / 'tools/spx/boot-diagnostics/snapshot-ak-startup.py'
(out / 'snapshot-ak-startup.py').write_bytes(shutil_source.read_bytes())
hashes = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
(out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
assert all(sha(out / name) == digest for name, digest in hashes.items())
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
os.sync()
print(json.dumps({'boot_id': BID, 'touch_state': state, 'windows': {n: {k: v for k,v in s.items() if k != 'gated_irqs'} for n,s in summary.items()},
                  'diagnostic_records': report['diagnostic_records'], 'files_verified': len(hashes), 'manifest_sha256': sha(out / 'sha256.json')}, indent=2))
