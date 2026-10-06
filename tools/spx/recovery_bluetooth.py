#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Repair only an unconfigured fitted recovery controller; restore rfkill policy."""
from contextlib import contextmanager
from pathlib import Path
import re
import subprocess
import time

PRIVATE = Path('/usr/local/libexec/spx-bluetooth')
CONFIG = Path('/etc/spx-bluetooth/address')
RFKILL = Path('/sys/class/rfkill')


def missing_address(info):
    return (re.search(r'^Unconfigured controller \(hci0,UART\)$', info, re.M) is not None
            and re.search(r'^\s*manufacturer 29\s*$', info, re.M) is not None
            and re.search(r'^\s*missing options: public-address\s*$', info, re.M) is not None)


def validate_address(value):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise RuntimeError('invalid per-installation Bluetooth address')
    raw = bytes.fromhex(value.replace(':', ''))
    if raw in (b'\0' * 6, b'\xff' * 6) or raw[0] & 1:
        raise RuntimeError('Bluetooth address must be a nonzero unicast address')
    return value.upper()


def controller_info():
    # The device unit can precede management enumeration after UART setup.
    deadline = time.monotonic() + 30
    while True:
        info = subprocess.check_output(['btmgmt', 'extinfo'], text=True, timeout=5)
        if re.search(r'^\w.* controller \(hci0,UART\)$', info, re.M):
            return info
        if time.monotonic() >= deadline:
            raise RuntimeError('fitted UART management controller did not appear')
        time.sleep(.25)


@contextmanager
def blocked_controller():
    matches = [entry for entry in RFKILL.glob('rfkill*')
               if (entry / 'name').read_text().strip() == 'hci0'
               and (entry / 'type').read_text().strip() == 'bluetooth']
    if len(matches) != 1:
        raise RuntimeError('exactly one fitted Bluetooth rfkill device required')
    soft = matches[0] / 'soft'
    original = soft.read_text().strip()
    if original not in ('0', '1'):
        raise RuntimeError('invalid rfkill soft state')
    try:
        # Management cannot power off an unconfigured index. Target only hci0.
        if original == '0':
            soft.write_text('1\n')
        if soft.read_text().strip() != '1':
            raise RuntimeError('fitted controller did not accept rfkill block')
        yield
    finally:
        if original == '0':
            soft.write_text('0\n')
        if soft.read_text().strip() != original:
            raise RuntimeError('original fitted-controller rfkill state not restored')


def main():
    if 'spx_boot=known-good' not in Path('/proc/cmdline').read_text().split():
        print('Not a recovery boot; controller unchanged')
        return
    if not Path('/proc/device-tree/model').read_bytes().startswith(b'Microsoft Surface Pro X'):
        raise RuntimeError('fitted Surface Pro X controller required')
    info = controller_info()
    if not missing_address(info):
        print('No fitted unconfigured controller missing an address; unchanged')
        return
    address = validate_address(CONFIG.read_text().strip())
    lock = str(PRIVATE / 'spx-lock')
    owner = 'recovery-bluetooth'
    subprocess.run([lock, 'acquire', 'device', owner], check=True, timeout=5)
    try:
        # Recheck after taking exclusive ownership; never rewrite a configured radio.
        if not missing_address(subprocess.check_output(['btmgmt', 'extinfo'], text=True, timeout=5)):
            return
        with blocked_controller():
            subprocess.run(['btmgmt', '--index', '0', 'public-addr', address], check=True, timeout=5)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = subprocess.run(['btmgmt', '--index', '0', 'info'],
                                        capture_output=True, text=True, timeout=3)
                if result.returncode == 0 and re.search(r'\baddr ' + re.escape(address) + r'\b', result.stdout):
                    print('Recovery public address configured; rfkill preference restored on exit')
                    return
                time.sleep(.1)
            raise RuntimeError('controller configuration completion not observed')
    finally:
        subprocess.run([lock, 'release', 'device', owner], check=True, timeout=5)


if __name__ == '__main__':
    main()
