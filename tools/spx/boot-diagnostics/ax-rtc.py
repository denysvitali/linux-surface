#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Observe AX RTC/NTP from startup through2600s without writing either clock."""
import gzip
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from ax_rtc_core import assess

X = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ax')
RUNTIME = Path('/usr/local/lib/spx-boot-diagnostics')
RELEASE = '7.3.0-rc2-spx-mainline-20261003ax+'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    a = json.loads((X / 'attempt.json').read_text())
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    cmdline = Path('/proc/cmdline').read_text().strip()
    assert os.uname().release == a['release'] == RELEASE
    assert cmdline.split() == ['BOOT_IMAGE=/spx-trial-20261003ax/vmlinuz'] + a['cmdline'].split()
    assert bid != a['preboot_id']
    out = X / 'rtc-result.partial'
    assert not out.exists() and not (X / 'rtc-result').exists()
    out.mkdir(mode=0o700)
    probe = RUNTIME / 'rtc-readonly-20261003ax'
    config = gzip.open('/proc/config.gz', 'rb').read()
    assert config == (X / 'build/artifacts/.config').read_bytes()
    assert sha(probe) == a['rtc_probe_sha256']
    identity = {'boot_id': bid, 'release': RELEASE, 'cmdline': cmdline,
                'config_sha256': hashlib.sha256(config).hexdigest(), 'probe_sha256': sha(probe)}
    evidence = dict(identity, attempt='20261003ax',
                    rtc_name=Path('/sys/class/rtc/rtc0/name').read_text().strip(),
                    rtc_device=str(Path('/sys/class/rtc/rtc0').resolve()),
                    hctosys=Path('/sys/class/rtc/rtc0/hctosys').read_text().strip(),
                    rtc_systohc_enabled=b'\nCONFIG_RTC_SYSTOHC=y\n' in config,
                    systohc_device='rtc0' if b'\nCONFIG_RTC_SYSTOHC_DEVICE="rtc0"\n' in config else '',
                    observer_time_writes=0, samples=[])
    report = {'scoped_passed': False, 'hardware_acceptance_closed': False}
    try:
        while True:
            assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
            sample = json.loads(subprocess.check_output([str(probe)], text=True, timeout=5))
            tracking = subprocess.check_output(['chronyc', '-c', 'tracking'], text=True, timeout=5).strip()
            columns = next(csv.reader([tracking]))
            assert len(columns) == 14, tracking
            sample.update(ntp_tracking_csv=tracking, ntp_stratum=int(columns[2]),
                          ntp_reference_epoch=float(columns[3]),
                          ntp_system_offset_seconds=float(columns[4]),
                          ntp_leap_status=columns[13])
            sample['taint'] = Path('/proc/sys/kernel/tainted').read_text().strip()
            evidence['samples'].append(sample)
            temporary = out / 'progress.new.json'
            temporary.write_text(json.dumps(evidence, indent=2) + '\n')
            temporary.replace(out / 'progress.json')
            if sample['monotonic'] >= 2600:
                break
            time.sleep(min(15, max(.1, 2600 - sample['monotonic'])))
        report.update(assess(evidence, identity))
    except BaseException as error:
        report['failure'] = repr(error)
    finally:
        for name, args in {'chrony-tracking': ['chronyc', 'tracking'],
                           'chrony-startup.log': ['journalctl', '-b', '-u', 'chronyd', '--no-pager', '-o', 'short-monotonic'],
                           'kernel.log': ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic']}.items():
            result = subprocess.run(args, capture_output=True, text=True, timeout=30)
            (out / name).write_text(result.stdout + result.stderr)
            if result.returncode:
                report.update(scoped_passed=False, failure=f'{name} exit{result.returncode}')
        (out / 'progress.json').write_text(json.dumps(evidence, indent=2) + '\n')
        (out / 'result.json').write_text(json.dumps(dict(report, **identity), indent=2) + '\n')
        manifest = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
        (out / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
        os.sync()
        out.rename(X / 'rtc-result')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
