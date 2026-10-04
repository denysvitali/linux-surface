#!/usr/bin/python3
"""Bounded B02 check of a disposable file on AP's encrypted root filesystem."""
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
from ap_boot_guard import X, load, recovery, artifacts, files, sha

os.umask(0o077)
BID = '7cc51af7-1dfb-4722-a23d-6e262a0e2c6f'
BLOCK = 1024 * 1024
BLOCKS = 128
MAX_CYCLES = 64  # At most 8 GiB each of writes and reads; one 128 MiB file.


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30)


def identity():
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
    assert os.uname().release == a['release']
    assert Path('/proc/cmdline').read_text().split() == [
        'BOOT_IMAGE=/spx-trial-20261001am/vmlinuz'] + a['cmdline'].split()


assert os.geteuid() == 0
a = load()
identity()
review = json.loads((X / 'independent-result-review.json').read_text())
assert review['boot_id'] == BID and review['scoped_passed'] and review['fallback_stopped']
assert command('systemctl', 'show', 'spx-ap-fallback.timer', '-p', 'ActiveState', '--value').strip() == 'inactive'
assert not recovery(a).get('next_entry', '')
artifacts(a)
assert shutil.disk_usage(X).free > 2 * 1024**3
out = X / 'storage-integrity'
out.mkdir(mode=0o700)  # Exclusive: never overwrite a previous result.
shutil.copy2(__file__, out / 'check-ap-storage.py')
for name, args in {
    'mount.json': ('findmnt', '-J', '-T', str(out), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'),
    'block-devices.json': ('lsblk', '-J', '-o', 'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS'),
    'uname': ('uname', '-a'),
}.items():
    (out / name).write_text(command(*args))
before = command('dmesg', '--raw')
(out / 'kernel-before.log').write_text(before)
(out / 'cmdline').write_text(Path('/proc/cmdline').read_text())
seed = os.urandom(32)
report = dict(attempt=a['attempt'], boot_id=BID, checklist_id='B02',
              baseline_manifest_sha256=review['result_manifest_sha256'],
              seed_hex=seed.hex(), block_bytes=BLOCK, file_bytes=BLOCK * BLOCKS,
              direct_write=True, direct_read=True, fsync_each_cycle=True,
              cycles=[], passed=False, limits=[
                  'A bounded file test cannot prove power-loss durability or exhaustive storage reliability.',
                  'No suspend/resume or final-candidate combined workload is tested.',
                  'Timing includes pattern generation and hashing; it is not a device benchmark.'])
payload = out / 'disposable.bin'
started = time.monotonic()
fd = None
try:
    # mmap supplies page-aligned buffers for O_DIRECT. Failure is recorded;
    # there is deliberately no silent fallback to cached I/O.
    with mmap.mmap(-1, BLOCK) as buf:
        for cycle in range(MAX_CYCLES):
            if cycle and time.monotonic() - started >= 60:
                break
            identity()
            fd = os.open(payload, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_DIRECT, 0o600)
            expected = []
            t = time.monotonic()
            for block in range(BLOCKS):
                pattern = hashlib.shake_256(seed + cycle.to_bytes(4, 'little') +
                                           block.to_bytes(4, 'little')).digest(BLOCK)
                buf[:] = pattern
                expected.append(hashlib.sha256(pattern).hexdigest())
                assert os.pwrite(fd, buf, block * BLOCK) == BLOCK
            os.fsync(fd)
            os.close(fd)
            fd = None
            written = time.monotonic()
            fd = os.open(payload, os.O_RDONLY | os.O_DIRECT)
            assert os.fstat(fd).st_size == BLOCK * BLOCKS
            actual = []
            for block in range(BLOCKS):
                assert os.preadv(fd, [buf], block * BLOCK) == BLOCK
                actual.append(hashlib.sha256(buf).hexdigest())
                assert actual[-1] == expected[block], (cycle, block)
            os.close(fd)
            fd = None
            report['cycles'].append(dict(cycle=cycle, write_fsync_seconds=written-t,
                                         read_verify_seconds=time.monotonic()-written,
                                         expected_sha256=expected, actual_sha256=actual))
            payload.unlink()
            print(f'cycle {cycle + 1}: 128 MiB direct write/fsync/readback verified', flush=True)
    identity()
    report['io_passed'] = bool(report['cycles'])
except Exception as exc:
    report['error'] = repr(exc)
finally:
    if fd is not None:
        os.close(fd)
    if payload.exists():
        payload.unlink()
    report['elapsed_seconds'] = time.monotonic() - started
    report['verified_bytes_each_direction'] = len(report['cycles']) * BLOCK * BLOCKS
    report['disposable_file_removed'] = not payload.exists()
    after = command('dmesg', '--raw')
    (out / 'kernel-after.log').write_text(after)
    report['kernel_log_prefix_preserved'] = after.startswith(before)
    delta = after[len(before):] if after.startswith(before) else after
    (out / 'kernel-delta.log').write_text(delta)
    fault = r'(?:I/O error|Buffer I/O|EXT4-fs (?:error|warning)|BTRFS.*(?:error|corrupt)|nvme.*(?:timeout|reset|error|abort)|(?:iommu|smmu).*fault|BUG:|Oops:|Call trace:|watchdog:.*lockup)'
    report['new_fault_lines'] = [s for s in delta.splitlines() if re.search(fault, s, re.I)]
    report['kernel_taint'] = Path('/proc/sys/kernel/tainted').read_text().strip()
    report['touch_ready_after'] = Path('/sys/bus/spi/devices/spi0.0/ready').read_text().strip()
    report['passed'] = bool(report.get('io_passed') and report['kernel_log_prefix_preserved']
                            and not report['new_fault_lines'] and report['kernel_taint'] == '0'
                            and report['touch_ready_after'] == 'ready' and 'error' not in report)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = files(out)
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    assert files(out) == hashes | {'sha256.json': sha(out / 'sha256.json')}
    os.sync()
print(json.dumps({k: v for k, v in report.items() if k != 'cycles'}, indent=2))
print('manifest_sha256=' + sha(out / 'sha256.json'))
sys.exit(0 if report['passed'] else 1)
