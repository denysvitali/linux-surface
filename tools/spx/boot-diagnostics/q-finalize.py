#!/usr/bin/python3
"""Archive Q's 600-second PIO result before allowing its fallback to stop."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
ATTEMPT = '20260927q'
RELEASE = '7.3.0-rc2-spx-mainline-20260922p+'
BASE = Path('/var/lib/spx-boot-diagnostics')
RUN = BASE / 'attempts' / ATTEMPT
BOOT = Path('/proc/sys/kernel/random/boot_id')


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def manifest(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def main():
    assert os.geteuid() == 0
    bid = BOOT.read_text().strip()
    assert command('uname', '-r').strip() == RELEASE
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    assert 600 <= uptime < 900, uptime
    assert not (RUN / 'final-result').exists()
    a = json.loads((RUN / 'attempt.json').read_text())
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == ATTEMPT and a['release'] == RELEASE
    cmdline = Path('/proc/cmdline').read_text().split()
    assert cmdline == ['BOOT_IMAGE=/spx-trial-20260922p/vmlinuz'] + a['cmdline'].split()
    selectors = ['spx_attempt=20260927q', 'spx_diag_window=600',
                 'slim_qcom_ngd_ctrl.spx_probe_stage=7',
                 'slim_qcom_ngd_ctrl.spx_stage7_step=7',
                 'slim_qcom_ngd_ctrl.spx_pio_mode=1',
                 'slim_qcom_ngd_ctrl.spx_pio_cap_retries=0',
                 'slim_qcom_ngd_ctrl.spx_pin_after_qmi=1']
    assert all(cmdline.count(token) == 1 for token in selectors)
    taint = Path('/proc/sys/kernel/tainted').read_text().strip()
    env = command('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert not any(line.startswith('next_entry=') and line != 'next_entry='
                   for line in env.splitlines())
    assert 'BootNext:' not in command('efibootmgr')
    assert command('systemctl', 'is-active', 'spx-q-fallback.timer').strip() == 'active'
    assert command('systemctl', 'show', 'spx-diag-long-return.timer',
                   '-p', 'ActiveState', '--value').strip() != 'active'
    assert command('systemctl', 'show', 'spx-diag-return.timer',
                   '-p', 'ActiveState', '--value').strip() != 'active'
    for name, digest in (a['sha256'] | a['recovery_sha256'] | a['runtime_sha256']).items():
        assert sha(Path(name)) == digest, name
    build_manifest = json.loads((RUN / 'build-sha256.json').read_text())
    assert len(build_manifest) == 985
    assert set(build_manifest) == set(manifest(RUN / 'build'))
    for name, digest in build_manifest.items():
        assert sha(RUN / 'build' / name) == digest, name
    module_manifest = json.loads((RUN / 'build/module-sha256.json').read_text())
    module_root = Path('/usr/lib/modules') / RELEASE
    assert len(module_manifest) == 202
    assert set(module_manifest) == set(manifest(module_root))
    for name, digest in module_manifest.items():
        assert sha(module_root / name) == digest, name

    kernel = command('journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager')
    journal = command('journalctl', '-b', '-o', 'short-monotonic', '--no-pager')
    required = ['SPX: stage 7 controlled power-up step=7',
                'SPX: stage 7 QMI power-on acked by ADSP',
                'SPX: stage 7 PIO NGD_CFG readback=0x1 int_stat=0x0',
                'SPX: PIO poll thread started',
                'SPX: stopping after controlled stage 7 before SLIM registration',
                'SPX: child probe: enable done']
    markers = {item: kernel.count(item) for item in required}
    done = kernel.count('SPX: stage 7 PIO capability exchange DONE')
    timed_out = kernel.count('SPX: PIO capability exchange timed out')
    worker = kernel.count('SLIM SAT: Rcvd master capability')
    fifo = kernel.count('SPX: PIO TX first-ever FIFO write:')
    bad = re.findall(r'^.*(?:\bOops:|Kernel panic|\bBUG:|Call trace:|GPU.*hangcheck|'
                     r'GMU.*(?:fault|watchdog)|PIO TX.*(?:NACKed|error|timed out)|'
                     r'PIO RX disabled|unexpected IRQ|remoteproc.*crash).*$'
                     , kernel, re.M | re.I)
    graph = 'OpenGL ES profile renderer: FD680' in journal
    network = command('nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status')
    wifi = 'wlan0:wifi:connected' in network.splitlines()
    touch_path = Path('/sys/bus/spi/devices/spi0.0/ready')
    touch = touch_path.is_file() and touch_path.read_text().strip() == 'ready'
    cards = Path('/proc/asound/cards').read_text()
    no_cards = cards.strip() == '--- no soundcards ---'
    capability = ('done' if done == 1 and timed_out == 0 else
                  'timeout' if timed_out == 1 and done == 0 else 'inconclusive')
    healthy = all(value == 1 for value in markers.values()) and not bad
    passed = (capability == 'done' and healthy and graph and wifi and touch
              and no_cards and taint == '0')

    # Refresh then copy one consistent collector snapshot under its lock.
    subprocess.run(['/usr/local/lib/spx-boot-diagnostics/collect.sh'], check=True,
                   timeout=90)
    assert BOOT.read_text().strip() == bid
    out = RUN / ('final-result.partial.' + bid)
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / 'finalize.py')
    (out / 'kernel.log').write_text(kernel)
    (out / 'journal.log').write_text(journal)
    with (out / 'journal.export').open('wb') as stream:
        subprocess.run(['journalctl', '-b', '-o', 'export', '--no-pager'],
                       stdout=stream, check=True, timeout=90)
    collector = BASE / 'boots' / bid
    with (collector / 'collect.lock').open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        shutil.copytree(collector, out / 'collector', symlinks=True,
                        ignore=shutil.ignore_patterns('collect.lock'))
    initrd = Path('/boot/spx-diagnostics') / bid
    if initrd.is_dir():
        shutil.copytree(initrd, out / 'initrd', symlinks=True)
    else:
        (out / 'initrd-missing').write_text('No per-boot initramfs log directory\n')
    (out / 'grubenv').write_text(env)
    (out / 'network').write_text(network)
    (out / 'interrupts').write_text(Path('/proc/interrupts').read_text())
    (out / 'cmdline').write_text(' '.join(cmdline) + '\n')
    params_dir = Path('/sys/module/slim_qcom_ngd_ctrl/parameters')
    params = ({p.name: p.read_text().strip() for p in params_dir.iterdir()}
              if params_dir.is_dir() else {})
    (out / 'audio-params.json').write_text(json.dumps(params, indent=2) + '\n')
    result = {'attempt': ATTEMPT, 'boot_id': bid, 'release': RELEASE,
              'uptime_seconds': uptime, 'capability': capability,
              'required_markers': markers, 'master_worker_entries': worker,
              'first_fifo_markers': fifo, 'kernel_fault_lines': bad,
              'fd680_renderer': graph, 'wifi_connected': wifi, 'spi_hid_ready': touch,
              'no_soundcards': no_cards, 'kernel_taint': taint,
              'passed_scoped_baseline': passed,
              'recovery_return_performed_at_snapshot': False,
              'fallback_action': 'stop only after this archive verifies' if passed
                                 else 'leave 900-second fallback armed',
              'limits': ['Capability DONE would establish the staged waiter, not codec traffic or playback.',
                         'No live parameter change, runtime resume or device rebind was attempted.']}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    hashes = manifest(out)
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    assert set(hashes) == set(manifest(out)) - {'sha256.json'}
    for name, digest in hashes.items():
        assert sha(out / name) == digest, name
    assert BOOT.read_text().strip() == bid
    assert command('systemctl', 'is-active', 'spx-q-fallback.timer').strip() == 'active'
    os.sync()
    out.rename(RUN / 'final-result')
    action = {'boot_id': bid, 'result_sha256': sha(RUN / 'final-result/result.json'),
              'manifest_sha256': sha(RUN / 'final-result/sha256.json'),
              'files_verified': len(hashes), 'fallback_stopped': False}
    if passed:
        subprocess.run(['systemctl', 'stop', 'spx-q-fallback.timer'], check=True,
                       timeout=30)
        action['fallback_stopped'] = (command('systemctl', 'show',
            'spx-q-fallback.timer', '-p', 'ActiveState', '--value').strip() != 'active')
        assert action['fallback_stopped']
    (RUN / 'finalizer-action.json').write_text(json.dumps(action, indent=2) + '\n')
    os.sync()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
