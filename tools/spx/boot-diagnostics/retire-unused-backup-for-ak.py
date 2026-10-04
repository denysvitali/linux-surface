#!/usr/bin/python3
"""Preserve and retire the inactive AA slot to make room for distinct AK."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
os.umask(0o077)
base = Path('/var/lib/spx-boot-diagnostics')
run = base / 'attempts/20260930ak'
slot = Path('/boot/spx-trial-20260930aa')
out = run / 'retired-unused-backup'
bid = 'd3b9f9b1-7e95-4963-8225-adf840755102'
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cmd(*args):
    return subprocess.check_output(args,text=True,timeout=90)
assert os.geteuid() == 0 and not out.exists() and not (run / 'deploy-started').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
assert cmd('uname','-r').strip() == '6.18.3-1-surface+'
assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
archive = json.loads((run / 'archive-review.json').read_text())
review = json.loads((run / 'independent-build-review.json').read_text())
assert archive['preboot_id'] == bid and review['detached_boost_guard_verified']
assert review['build_manifest_sha256'] == archive['build_manifest_sha256']
for name,digest in json.loads((run / 'build-sha256.json').read_text()).items():
    assert sha(run / 'build' / name) == digest,name
parent = json.loads((base / 'attempts/20260930aj/attempt.json').read_text())
assert parent == json.loads((base / 'attempt.json').read_text())
protected = {}
for attempt in ('20260930ae','20260930ag','20260930ai','20260930aj'):
    a = json.loads((base / 'attempts' / attempt / 'attempt.json').read_text())
    protected.update(a['sha256'] | a['recovery_sha256'])
protected.update(parent['runtime_sha256'])
assert all(not p.startswith(str(slot) + '/') for p in protected)
for p,d in protected.items():
    assert sha(p) == d,p
configs = [Path('/boot/grub/grub.cfg'),Path('/boot/grub/custom.cfg')]
assert all(slot.name not in p.read_text() for p in configs)
for p in Path('/etc/grub.d').iterdir():
    if p.is_file() and os.access(p,os.X_OK):
        assert slot.name not in p.read_text(),p
assert slot.name not in Path('/proc/cmdline').read_text()
assert 'set default="spx-known-good"' in configs[0].read_text()
env = cmd('grub-editenv','/boot/grub/grubenv','list')
assert 'saved_entry=spx-known-good' in env.splitlines() and 'next_entry=' in env.splitlines()
assert 'BootNext:' not in cmd('efibootmgr')
assert {p.name for p in slot.iterdir()} == {'vmlinuz','initramfs.img','spx.dtb'}
old = json.loads((base / 'attempts/20260930aa/attempt.json').read_text())
payloads = {p.name:sha(p) for p in sorted(slot.iterdir())}
assert {str(slot / n):d for n,d in payloads.items()} == old['sha256']
space = os.statvfs('/boot')
available = space.f_bavail * space.f_frsize
required = sum((run / 'build' / n).stat().st_size for n in ('vmlinuz','initramfs.img')) + 1048576
size = sum(p.stat().st_size for p in slot.iterdir())
assert available < required < available + size
out.mkdir(mode=0o700)
shutil.copytree(slot,out / slot.name)
assert all(sha(out / slot.name / n) == d for n,d in payloads.items())
for p in configs:
    shutil.copy2(p,out / p.name)
shutil.copy2(__file__,out / 'retire-unused-backup-for-ak.py')
report = {'preboot_id':bid,'original_slot':str(slot),'archive_slot':str(out / slot.name),
          'payload_sha256':payloads,'size_bytes':size,'available_before_bytes':available,
          'required_ak_bytes_with_margin':required,'active_configs_and_running_boot_do_not_reference_slot':True,
          'active_AE_AG_AI_AJ_and_recovery_payloads_preserved':True,
          'restore_instruction':'Copy the verified archived slot directory to original_slot before using any historical GRUB entry referring to it.'}
(out / 'report.json').write_text(json.dumps(report,indent=2)+'\n')
hashes = {str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
(out / 'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
assert all(sha(out / n) == d for n,d in hashes.items())
os.sync()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
assert cmd('grub-editenv','/boot/grub/grubenv','list') == env
for n,d in payloads.items():
    assert sha(slot / n) == d
for n in payloads:
    (slot / n).unlink()
slot.rmdir()
assert all(sha(out / slot.name / n) == d for n,d in payloads.items())
for p,d in protected.items():
    assert sha(p) == d,p
space = os.statvfs('/boot')
assert space.f_bavail * space.f_frsize > required
os.sync()
print(json.dumps(report | {'archive_files':len(hashes),'manifest_sha256':sha(out / 'sha256.json')},indent=2))
