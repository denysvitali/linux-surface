#!/usr/bin/python3
"""Archive device metadata for the port checklist; this is not a functional test."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path, help='New private evidence directory; never overwritten')
args = parser.parse_args()
os.umask(0o077)
assert os.geteuid() == 0
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
base = Path('/var/lib/spx-boot-diagnostics')
attempt = json.loads((base/'attempt.json').read_text())
assert os.uname().release == attempt['release']
assert 'spx_attempt='+attempt['attempt'] in Path('/proc/cmdline').read_text().split()
args.output.mkdir(mode=0o700, parents=False, exist_ok=False)

commands = {
    'uname': ['uname', '-a'],
    'usb': ['lsusb'],
    'storage': ['lsblk', '-o', 'NAME,TYPE,SIZE,MOUNTPOINTS'],
    'network': ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'],
    'grubenv': ['grub-editenv', '/boot/grub/grubenv', 'list'],
    'kernel': ['journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager'],
}
results = {}
for name, argv in commands.items():
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        results[name] = {'argv': argv, 'returncode': p.returncode}
        (args.output/(name+'.txt')).write_text(p.stdout)
        (args.output/(name+'.stderr')).write_text(p.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        results[name] = {'argv': argv, 'error': str(error)}

roots = {
    '/sys/bus/iio/devices': ('name',),
    '/sys/class/power_supply': ('type', 'status', 'online', 'capacity'),
    '/sys/class/drm': ('status', 'enabled', 'modes'),
    '/sys/class/backlight': ('brightness', 'actual_brightness', 'max_brightness'),
    '/sys/class/remoteproc': ('name', 'state'),
    '/sys/class/rtc': ('name',),
    '/sys/devices/system/cpu/cpufreq': ('scaling_driver', 'scaling_governor', 'cpuinfo_min_freq', 'cpuinfo_max_freq'),
    '/sys/class/thermal': ('type',),
    '/sys/class/bluetooth': (), '/sys/class/typec': (),
    '/sys/class/video4linux': (), '/sys/class/media': (),
    '/sys/class/wwan': (), '/sys/class/gnss': (), '/sys/class/tpm': (),
    '/sys/class/leds': (),
}
inventory = {}
for root, fields in roots.items():
    path = Path(root)
    if not path.exists():
        inventory[root] = {'exists': False, 'devices': {}}
        continue
    devices = {}
    for node in sorted(path.iterdir()):
        data = {}
        for field in fields:
            try:
                data[field] = (node/field).read_text().strip()
            except OSError:
                pass
        devices[node.name] = data
    inventory[root] = {'exists': True, 'devices': devices}

paths = {
    'cmdline': '/proc/cmdline', 'uptime': '/proc/uptime',
    'input-devices': '/proc/bus/input/devices', 'sound-cards': '/proc/asound/cards',
    'sleep-states': '/sys/power/state', 'mem-sleep': '/sys/power/mem_sleep',
    'touch-ready': '/sys/bus/spi/devices/spi0.0/ready',
}
for name, path in paths.items():
    try:
        (args.output/(name+'.txt')).write_bytes(Path(path).read_bytes())
    except OSError as error:
        results[name] = {'path': path, 'error': str(error)}
shutil.copy2(__file__, args.output/Path(__file__).name)
(args.output/'attempt.json').write_text(json.dumps(attempt, indent=2)+'\n')
report = {
    'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'boot_id': boot, 'attempt': attempt['attempt'], 'release': os.uname().release,
    'purpose': 'Read-only metadata inventory; enumeration is not functional acceptance',
    'commands': results, 'inventory': inventory,
    'input_events_read': False, 'hardware_state_changes_requested': False,
}
(args.output/'inventory.json').write_text(json.dumps(report, indent=2)+'\n')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
hashes = {p.name: sha(p) for p in sorted(args.output.iterdir()) if p.is_file()}
(args.output/'sha256.json').write_text(json.dumps(hashes, indent=2)+'\n')
assert all(sha(args.output/name) == digest for name, digest in hashes.items())
os.sync()
print(json.dumps({'directory': str(args.output), 'boot_id': boot,
                  'files_verified': len(hashes), 'manifest_sha256': sha(args.output/'sha256.json'),
                  'command_failures': [name for name,r in results.items() if r.get('returncode', 0) or 'error' in r]}, indent=2))
