# SPDX-License-Identifier: GPL-2.0-only
"""Stage the upstream PMIC RTC and test one alarm while Linux stays awake."""
import datetime
import fcntl
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import time

PARENT = '/soc@0/spmi@c440000/pmic@0'
NODE = PARENT + '/rtc@6000'
RTC_RD_TIME = 0x80247009
RTC_WKALM_RD = 0x80287010
RTC_WKALM_SET = 0x4028700f
RTC_AIE_OFF = 0x7002


def stage(dtb):
    def get(node, prop):
        return subprocess.check_output(['fdtget', '-t', 's', str(dtb), node, prop], text=True).strip()
    assert get('/', 'model').startswith('Microsoft Surface Pro X')
    assert get(PARENT, 'compatible') == 'qcom,pm8150 qcom,spmi-pmic'
    children = subprocess.check_output(['fdtget', '-l', str(dtb), PARENT], text=True).splitlines()
    assert 'rtc@6000' not in children, 'RTC candidate already present'
    aliases = subprocess.check_output(['fdtget', '-p', str(dtb), '/aliases'], text=True).splitlines()
    assert 'rtc1' not in aliases, 'rtc1 already reserved'
    subprocess.run(['fdtput', '-c', str(dtb), NODE], check=True)
    for prop, kind, values in [
            ('compatible', 's', ['qcom,pm8941-rtc']),
            ('reg', 'x', ['6000', '6100']),
            ('reg-names', 's', ['rtc', 'alarm']),
            ('interrupts', 'x', ['0', '61', '1', '1'])]:
        subprocess.run(['fdtput', '-t', kind, str(dtb), NODE, prop, *values], check=True)
    subprocess.run(['fdtput', '-t', 's', str(dtb), '/aliases', 'rtc1', NODE], check=True)


def irq_count():
    rows = [line for line in Path('/proc/interrupts').read_text().splitlines()
            if 'pm8xxx_rtc_alarm' in line]
    if len(rows) != 1:
        raise RuntimeError('one PMIC RTC alarm IRQ required')
    counts = []
    for word in rows[0].split(':', 1)[1].split():
        if not word.isdigit():
            break
        counts.append(int(word))
    return sum(counts)


def alarm(fd):
    data = bytearray(40)
    fcntl.ioctl(fd, RTC_WKALM_RD, data)
    return struct.unpack('=BB2x9i', data)


def exercise(output, attempt, release, *, suspend=False):
    output.mkdir(parents=True, exist_ok=False)
    result = dict(complete=False, scope='one PMIC-alarm s2idle' if suspend else 'awake PMIC alarm; no suspend',
                  boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  release=os.uname().release)
    fd = None
    armed = False
    try:
        assert os.geteuid() == 0 and os.uname().release == release
        words = Path('/proc/cmdline').read_text().split()
        assert 'spx_boot=mainline-functional' in words and 'spx_attempt=' + attempt in words
        device = Path('/sys/class/rtc/rtc1')
        assert (device / 'device/of_node').resolve().as_posix().endswith(NODE)
        assert (device / 'device/driver').resolve().name == 'rtc-pm8xxx'
        assert (device / 'hctosys').read_text().strip() == '0'
        if suspend:
            prior = json.loads((output.parent / 'pmic-rtc/result.json').read_text())
            assert prior['complete'] and prior['boot_id'] == result['boot_id']
            assert (device / 'device/power/wakeup').read_text().strip() == 'enabled'
            assert Path('/sys/power/mem_sleep').read_text().strip() == '[s2idle]'
            assert '[none]' in Path('/sys/power/pm_test').read_text().split()
            assert Path('/sys/class/rtc/rtc0/name').read_text().startswith('surface_rtc ')
            assert subprocess.check_output(['systemctl', 'is-active',
                'spx-trial-return@' + attempt + '.timer'], text=True).strip() == 'active'
        fd = os.open('/dev/rtc1', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        initial = alarm(fd)
        assert initial[0] == 0, 'pre-existing enabled alarm; left untouched'
        assert initial[1] == 0, 'pre-existing pending alarm; left untouched'
        result['irq_before'] = irq_count()
        data = bytearray(36)
        fcntl.ioctl(fd, RTC_RD_TIME, data)
        current = struct.unpack('=9i', data)
        now = datetime.datetime(current[5] + 1900, current[4] + 1, current[3],
                                current[2], current[1], current[0], tzinfo=datetime.timezone.utc)
        target = now + datetime.timedelta(seconds=15 if suspend else 8)
        tm = (target.second, target.minute, target.hour, target.day, target.month - 1,
              target.year - 1900, (target.weekday() + 1) % 7, target.timetuple().tm_yday - 1, 0)
        # Record cleanup responsibility before the mutating ioctl.
        armed = True
        fcntl.ioctl(fd, RTC_WKALM_SET, struct.pack('=BB2x9i', 1, 0, *tm))
        assert alarm(fd)[0] == 1, 'alarm enable not observed'
        if suspend:
            result['phase'] = 'alarm-armed-before-suspend'
            (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            os.sync()
            wakecount = Path('/sys/power/wakeup_count')
            count = wakecount.read_text().strip()
            wakecount.write_text(count + '\n')
            # Standard wakeup-count handshake rejects an intervening wake event.
            mono = time.monotonic()
            boot = time.clock_gettime(time.CLOCK_BOOTTIME)
            result['suspend_uptime'] = boot
            Path('/sys/power/state').write_text('mem\n')
            slept = ((time.clock_gettime(time.CLOCK_BOOTTIME) - boot)
                     - (time.monotonic() - mono))
            result['sleep_seconds'] = slept
            assert slept >= 3, 'no meaningful s2idle interval observed'
        ready, _, _ = select.select([fd], [], [], 15)
        assert ready, 'no awake alarm event within 15 seconds'
        event = struct.unpack('@L', os.read(fd, struct.calcsize('@L')))[0]
        result['event'] = event
        result['irq_after'] = irq_count()
        assert event & 0x20 and event & 0x80, 'RTC_AF/RTC_IRQF missing'
        assert result['irq_after'] > result['irq_before'], 'alarm IRQ did not advance'
        result['delivered'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        if fd is not None:
            try:
                if armed:
                    fcntl.ioctl(fd, RTC_AIE_OFF)
                    result['alarm_disabled'] = alarm(fd)[0] == 0
                    assert result['alarm_disabled'], 'alarm cleanup did not disable it'
                result['complete'] = result.get('delivered', False) and result.get('alarm_disabled', False)
            except Exception as error:
                result['cleanup_error'] = str(error)
            finally:
                os.close(fd)
        result['phase'] = 'finished'
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
