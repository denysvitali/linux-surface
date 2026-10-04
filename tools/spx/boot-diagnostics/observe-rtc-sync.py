#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Archive read-only B05 RTC/NTP/config evidence on the current known-good boot."""
import fcntl
import gzip
import json
import os
from pathlib import Path
import struct
import subprocess
import time
import calendar

from aw_boot_guard import X, files, sha


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot == 'fbc6d663-8269-4d2f-9aac-c4a687583b00'
    assert os.uname().release == '6.18.3-1-surface+'
    out = X / 'rtc-sync-investigation'
    assert not out.exists()
    out.mkdir(mode=0o700)
    samples = []
    for i in range(2):
        fd = os.open('/dev/rtc0', os.O_RDONLY)
        try:
            raw = bytearray(36)
            before, mono_before = time.time(), time.monotonic()
            fcntl.ioctl(fd, 0x80247009, raw)  # RTC_RD_TIME: read only.
            after, mono_after = time.time(), time.monotonic()
            sec, minute, hour, day, month, year, *_ = struct.unpack('9i', raw)
            epoch = calendar.timegm((year + 1900, month + 1, day, hour, minute, sec))
            samples.append({'realtime_before': before, 'realtime_after': after,
                            'monotonic_before': mono_before, 'monotonic_after': mono_after,
                            'rtc_epoch': epoch, 'offset_seconds_interval': [epoch - after, epoch + 1 - before],
                            'rtc_raw_tm': list(struct.unpack('9i', raw))})
        finally:
            os.close(fd)
        if i == 0:
            time.sleep(15)
    config = gzip.open('/proc/config.gz', 'rt').read()
    (out / 'running-config').write_text(config)
    for name, args in {
        'chrony-tracking': ['chronyc', 'tracking'],
        'chrony-sources': ['chronyc', 'sources'],
        'chrony-startup.log': ['journalctl', '-b', '-u', 'chronyd', '--no-pager', '-o', 'short-monotonic'],
        'kernel.log': ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic'],
        'timedatectl': ['timedatectl'],
        'chronyd-unit': ['systemctl', 'cat', 'chronyd.service'],
        'chrony-effective-config': ['chronyd', '-p']}.items():
        (out / name).write_text(subprocess.check_output(args, text=True, timeout=60))
    for name, path in {'chrony.conf': '/etc/chrony.conf', 'adjtime': '/etc/adjtime',
                       'rtc-driver.c': str(Path(__file__).resolve().parents[3] / 'drivers/rtc/rtc-surface.c'),
                       'ntp.c': str(Path(__file__).resolve().parents[3] / 'kernel/time/ntp.c'),
                       'rtc-Kconfig': str(Path(__file__).resolve().parents[3] / 'drivers/rtc/Kconfig'),
                       'observer.py': str(Path(__file__).resolve())}.items():
        (out / name).write_bytes(Path(path).read_bytes())
    assert '# CONFIG_RTC_SYSTOHC is not set' in config
    assert 'CONFIG_GENERIC_CMOS_UPDATE=y' not in config
    assert '\nrtcsync\n' in (out / 'chrony-effective-config').read_text()
    assert 'Leap status     : Normal' in (out / 'chrony-tracking').read_text()
    assert 'UTC' == (out / 'adjtime').read_text().splitlines()[-1]
    report = {'boot_id': boot, 'release': os.uname().release,
              'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
              'rtc_name': Path('/sys/class/rtc/rtc0/name').read_text().strip(),
              'rtc_device': str(Path('/sys/class/rtc/rtc0').resolve()),
              'rtc_hctosys': Path('/sys/class/rtc/rtc0/hctosys').read_text().strip(),
              'samples': samples, 'chrony_rtcsync_enabled': True,
              'rtc_systohc_compiled': False, 'generic_cmos_update_compiled': False,
              'rtc_or_system_time_written_by_observer': False,
              'hardware_acceptance_closed': False,
              'limits': ['Two short observations do not measure long-term drift or power-off retention.',
                         'Missing synchronization path explains why chrony rtcsync cannot correct this RTC; origin of the existing offset remains unproven.']}
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(files(out), indent=2) + '\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
