#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the prepared precision diagnostic only after AX's verified actual return."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time

BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261003ax'
PREP = BASE / 'gpu-workloads/20261003-precision-readback-preparation'
FIXTURE = Path('/usr/local/lib/spx-gles-precision/20261003')
OUT = BASE / 'gpu-workloads/20261003-precision-readback-result'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    assert not any(p.is_symlink() for p in root.rglob('*'))
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    current = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert os.uname().release == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    recovery = json.loads((X / 'return-result/result.json').read_text())
    assert recovery['returned_boot_id'] == current and recovery['trial_boot_id'] != current
    assert recovery['baseline_recomputed_exact'] and recovery['original_rtc_copy_exact']
    assert not recovery['hardware_acceptance_closed']
    assert 'saved_entry=spx-known-good\n' in subprocess.check_output(
        ['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert 'next_entry=\n' in subprocess.check_output(
        ['grub-editenv', '/boot/grub/grubenv', 'list'], text=True)
    assert sha(PREP / 'sha256.json') == '0a849371782b9bd0ad27a903e459e0cb8d7562b45bbfe948e734e0dcd1b4f0f2'
    h = json.loads((PREP / 'sha256.json').read_text())
    assert files(PREP) == h | {'sha256.json': sha(PREP / 'sha256.json')}
    for name in ('gles-precision-readback', 'gles-precision-readback.c'):
        assert sha(FIXTURE / name) == h[name]
        assert (FIXTURE / name).stat().st_uid == 0 and not (FIXTURE / name).stat().st_mode & 0o022
    for parent in (FIXTURE, FIXTURE.parent, FIXTURE.parent.parent):
        assert parent.stat().st_uid == 0 and not parent.stat().st_mode & 0o022
    assert not OUT.exists() and not OUT.with_suffix('.partial').exists()
    out = OUT.with_suffix('.partial')
    out.mkdir(mode=0o700)
    shutil.copy2(Path(__file__), out / Path(__file__).name)
    initial_taint = Path('/proc/sys/kernel/tainted').read_text().strip()
    assert initial_taint == '4096'
    user = pwd.getpwnam('dvitali')
    report = {'boot_id': current, 'release': os.uname().release,
              'cmdline': Path('/proc/cmdline').read_text().strip(),
              'started_boottime': time.clock_gettime(time.CLOCK_BOOTTIME),
              'source_sha256': sha(FIXTURE / 'gles-precision-readback.c'),
              'binary_sha256': sha(FIXTURE / 'gles-precision-readback'),
              'diagnostic_completed': False, 'hardware_acceptance_closed': False,
              'fd_samples': [], 'initial_taint': initial_taint}
    process = None
    try:
        with (out / 'stdout.json').open('w') as stdout, (out / 'stderr.log').open('w') as stderr:
            process = subprocess.Popen([str(FIXTURE / 'gles-precision-readback')],
                user=user.pw_uid, group=user.pw_gid, extra_groups=os.getgrouplist(user.pw_name, user.pw_gid),
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, stdout=stdout, stderr=stderr)
            deadline = time.monotonic() + 30
            while process.poll() is None:
                assert time.monotonic() < deadline, 'Diagnostic timeout'
                try:
                    nodes = sorted({str(p.resolve()) for p in Path(f'/proc/{process.pid}/fd').iterdir()
                                    if str(p.resolve()).startswith('/dev/dri/')})
                except FileNotFoundError:
                    nodes = []
                if nodes:
                    assert nodes == ['/dev/dri/renderD128'], nodes
                    report['fd_samples'].append({'boottime': time.clock_gettime(time.CLOCK_BOOTTIME), 'nodes': nodes})
                time.sleep(.005)
            report['returncode'] = process.wait()
        assert report['returncode'] == 0
        assert report['fd_samples'], 'No observed render FD'
        result = json.loads((out / 'stdout.json').read_text())
        assert result['renderer'] == 'FD680' and result['size'] == [800, 600]
        assert result['read_pixel'] == [293, 89] and not result['hardware_acceptance_closed']
        assert [(r['precision'], r['steps']) for r in result['samples']] == [
            (p, s) for p in ('mediump', 'highp') for s in range(6)]
        assert all(len(r['rgba']) == 4 and r['rgba'][0] == r['rgba'][1] == r['rgba'][2]
                   and r['rgba'][3] == 255 and all(isinstance(v, int) and 0 <= v <= 255 for v in r['rgba'])
                   for r in result['samples'])
        report.update(diagnostic_completed=True, precision_readback=result)
    except Exception as error:
        report['failure'] = repr(error)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        report['finished_boottime'] = time.clock_gettime(time.CLOCK_BOOTTIME)
        report['final_taint'] = Path('/proc/sys/kernel/tainted').read_text().strip()
        if report['final_taint'] != initial_taint or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != current:
            report.update(diagnostic_completed=False, failure='Boot identity or taint changed')
        (out / 'kernel.log').write_text(subprocess.check_output(
            ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'], text=True, timeout=30))
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
        os.sync()
        out.rename(OUT)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
