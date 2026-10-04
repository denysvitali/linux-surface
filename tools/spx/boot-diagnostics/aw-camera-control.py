#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Preserve AW normal rear-driver state, idle cleanup and sampled PMIC controls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from aw_camera_core import CCI, SENSOR, RAILS, LED, assess, decode

BASE = Path('/var/lib/spx-boot-diagnostics')
X = BASE / 'attempts/20261003aw'
AP = BASE / 'attempts/20261002ap/camera-pmic-metadata-20261003'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final', action='store_true', help='Preserve a separate read-only final-baseline snapshot')
    args = parser.parse_args()
    os.umask(0o077)
    assert os.geteuid() == 0
    spec = importlib.util.spec_from_file_location('provider', Path(__file__).with_name('aw-camera-provider.py'))
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    a = json.loads((X / 'attempt.json').read_text())
    before = provider.identity()
    assert a == json.loads((BASE / 'attempt.json').read_text())
    assert a['attempt'] == '20261003aw' and before['boot_id'] != a['preboot_id']
    assert before['release'] == a['release']
    assert before['cmdline'].split() == ['BOOT_IMAGE=/spx-trial-20261003aw/vmlinuz'] + a['cmdline'].split()
    out = X / ('camera-control-final-result' if args.final else 'camera-control-result')
    assert not out.exists()
    out.mkdir(mode=0o700)
    r = {'identity_before': before, 'time': time.time(),
         'collection_phase': 'final' if args.final else 'initial',
         'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
         'cci': [], 'sensors': [], 'providers': {}, 'pmic_reads': [],
         'camera_error_lines': [], 'privacy_leds': [], 'collector_hardware_writes': 0,
         'camera_functional_acceptance': False, 'observer_lookup_source': 'LED class uevent OF_FULLNAME',
         'limits': ['Normal DT-enabled drivers may have requested rails/clocks and performed sensor identification.',
                    'Collector performs no bus scan/read, stream, control, reset, rebind or module operation.',
                    'Normal binding implies the frozen normal probe ID check succeeded; returned ID bytes are not logged.',
                    'Sampled controls/idle states do not measure rails or prove firmware arbitration, physical sharing or capture.']}

    def device(p):
        fields = {'name': p.name, 'sysfs_path': str(p.resolve()),
                  'of_node': str((p / 'of_node').resolve()),
                  'driver': (p / 'driver').resolve().name if (p / 'driver').is_symlink() else None,
                  'power': {}}
        for key in ('control', 'runtime_status', 'runtime_active_time', 'runtime_suspended_time'):
            if (p / 'power' / key).is_file():
                fields['power'][key] = (p / 'power' / key).read_text().strip()
        for key in ('modalias', 'resource'):
            if (p / key).is_file():
                fields[key] = (p / key).read_text()
        return fields

    try:
        for p in Path('/sys/bus/platform/devices').iterdir():
            if (p / 'of_node').is_symlink() and str((p / 'of_node').resolve()).endswith(CCI):
                fields = device(p)
                fields['assigned_clock_rate_hz'] = int.from_bytes((p / 'of_node/assigned-clock-rates').read_bytes(), 'big')
                r['cci'].append(fields)
        for p in Path('/sys/bus/i2c/devices').iterdir():
            if (p / 'of_node').is_symlink() and str((p / 'of_node').resolve()).endswith(SENSOR):
                fields = device(p)
                fields['adapter_of_node'] = str((p.resolve().parent / 'of_node').resolve())
                r['sensors'].append(fields)
        dt = Path('/sys/firmware/devicetree/base')
        for p in Path('/sys/class/leds').glob('*'):
            names = re.findall(r'^OF_FULLNAME=(/[^\n]*)$', (p / 'uevent').read_text(), re.M)
            if names == [LED]:
                node = dt / LED.lstrip('/')
                assert node.is_dir() and (node / 'label').read_bytes() == (p.name + '\0').encode()
                gpio = (node / 'gpios').read_bytes()
                assert len(gpio) == 12
                gpio_h = int.from_bytes(gpio[:4], 'big')
                providers = [q.parent for q in dt.rglob('phandle') if q.read_bytes() == gpio[:4]]
                assert len(providers) == 1
                dev = (p / 'device').resolve()
                r['privacy_leds'].append({'name': p.name, 'of_node': str(node.resolve()),
                    'provider_driver': (dev / 'driver').resolve().name,
                    'brightness': (p / 'brightness').read_text().strip(),
                    'max_brightness': (p / 'max_brightness').read_text().strip(),
                    'trigger_selected': re.search(r'\[([^]]+)\]', (p / 'trigger').read_text())[1],
                    'phandle': int.from_bytes((node / 'phandle').read_bytes(), 'big'),
                    'sensor_led_phandle': int.from_bytes((dt / SENSOR.lstrip('/') / 'leds').read_bytes(), 'big'),
                    'sensor_led_names': (dt / SENSOR.lstrip('/') / 'led-names').read_bytes().rstrip(b'\0').decode().split('\0'),
                    'gpio_provider': '/' + str(providers[0].relative_to(dt)),
                    'gpio_pin': int.from_bytes(gpio[4:8], 'big'), 'gpio_flags': int.from_bytes(gpio[8:12], 'big')})
        gpio_dump = Path('/sys/kernel/debug/gpio').read_text()
        (out / 'gpio.txt').write_text(gpio_dump)
        block = next(b for b in gpio_dump.split('\n\n') if 'parent: platform/3100000.pinctrl' in b)
        r['privacy_gpio_line'] = next(l for l in block.splitlines() if re.match(r'\s*gpio11\s*:', l))
        pinmux = Path('/sys/kernel/debug/pinctrl/3100000.pinctrl/pinmux-pins').read_text()
        (out / 'pinmux-pins.txt').write_text(pinmux)
        r['front_privacy_pinmux_line'] = next(l for l in pinmux.splitlines() if l.startswith('pin 25 '))
        for p in Path('/sys/class/regulator').glob('regulator.*'):
            name = (p / 'name').read_text().strip()
            if name in RAILS:
                assert name not in r['providers'], name
                fields = {key: (p / key).read_text().strip() for key in (
                    'name', 'microvolts', 'min_microvolts', 'max_microvolts', 'state', 'num_users')}
                dev = (p / 'device').resolve()
                fields |= {'provider_driver': (dev / 'driver').resolve().name,
                           'provider_of_node': str((dev / 'of_node').resolve()),
                           'consumer_links': {q.name: os.readlink(q) for q in p.iterdir()
                                              if q.is_symlink() and q.name.startswith('consumer:')}}
                r['providers'][name] = fields
        regmap = Path('/sys/kernel/debug/regmap/0-01')
        assert (regmap / 'range').read_text() == '0-ffff\n'
        assert (regmap / 'name').read_text() == 'pmic-spmi\n'
        fd = os.open(regmap / 'registers', os.O_RDONLY | os.O_CLOEXEC)
        try:
            for name, (_, base, subtype, voltage) in provider.EXPECTED.items():
                for field, offset in provider.OFFSETS.items():
                    address = base + offset
                    r['pmic_reads'].append({'name': name, 'field': field, 'address': address,
                        'file_offset': address * 9, 'raw': os.pread(fd, 9, address * 9).decode('ascii')})
        finally:
            os.close(fd)
        for name, p in [('clock-summary.txt', Path('/sys/kernel/debug/clk/clk_summary')),
                        ('regulator-summary.txt', Path('/sys/kernel/debug/regulator/regulator_summary')),
                        ('devices-deferred.txt', Path('/sys/kernel/debug/devices_deferred')),
                        ('interrupts', Path('/proc/interrupts'))]:
            if p.is_file():
                (out / name).write_text(p.read_text())
        kernel = subprocess.check_output(['journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager'], text=True, timeout=90)
        (out / 'kernel.log').write_text(kernel)
        r['camera_error_lines'] = [line for line in kernel.splitlines() if re.search(
            r'(?:ov13858|ac4a000|i2c-qcom-cci|spx-camera-|spx:rear:privacy|camera-privacy-leds|leds-gpio).*?(?:fail|error|timed?\s*out|mismatch|cleanup incomplete)', line, re.I)]
        r['cci_version_lines'] = [line for line in kernel.splitlines() if 'CCI HW version =' in line]
    except Exception as error:
        r['failure'] = repr(error)
    finally:
        r['identity_after'] = provider.identity()
        reference_hash = provider.sha(AP / 'sha256.json')
        assert reference_hash == '6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0'
        for name, digest in json.loads((AP / 'sha256.json').read_text()).items():
            assert provider.sha(AP / name) == digest
        reference = decode(json.loads((AP / 'result.json').read_text())['reads'])
        r |= assess(r, reference)
        r['reference_manifest_sha256'] = reference_hash
        (out / 'report.json').write_text(json.dumps(r, indent=2) + '\n')
        for p in (Path(__file__), Path(__file__).with_name('aw_camera_core.py')):
            shutil.copy2(p, out / p.name)
        (out / 'sha256.json').write_text(json.dumps(
            {p.name: provider.sha(p) for p in out.iterdir() if p.is_file()}, indent=2) + '\n')
        os.sync()
    print(json.dumps({'control_passed': r['control_passed'], 'failure_reasons': r['failure_reasons'],
                      'manifest_sha256': provider.sha(out / 'sha256.json')}))
    raise SystemExit(0 if r['control_passed'] else 1)


if __name__ == '__main__':
    main()
