#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reject malformed/stale NTP references using one captured packet; no network."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys

spec = importlib.util.spec_from_file_location('reference', Path(__file__).with_name('rtc-ntp-reference.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original = json.loads(Path(sys.argv[1]).read_text())
verdict = module.assess(original)
assert verdict['rtc_within_two_seconds_in_this_sample']
assert verdict['clock_writes'] == 0 and not verdict['hardware_acceptance_closed']


def packet_change(evidence, index, value):
    packet = bytearray.fromhex(evidence['response_hex'])
    packet[index] = value
    evidence['response_hex'] = packet.hex()


cases = {
    'client mode': lambda e: packet_change(e, 0, 0x23),
    'leap unsynchronized': lambda e: packet_change(e, 0, 0xe4),
    'unsupported version': lambda e: packet_change(e, 0, 0x14),
    'kiss of death': lambda e: packet_change(e, 1, 0),
    'invalid stratum': lambda e: packet_change(e, 1, 16),
    'wrong origin': lambda e: packet_change(e, 24, 0),
    'unsupported extension': lambda e: e.update(response_hex=e['response_hex'] + '00'),
    'truncated response': lambda e: e.update(response_hex=e['response_hex'][:-2]),
    'excessive RTT': lambda e: e.update(receive_boottime=e['send_boottime'] + 2),
    'system clock step': lambda e: e.update(receive_realtime=e['receive_realtime'] + 1),
}
for name, change in cases.items():
    evidence = copy.deepcopy(original)
    change(evidence)
    try:
        module.assess(evidence)
    except (AssertionError, struct.error):
        continue
    raise AssertionError('Accepted ' + name)
for name, offset, value in [('receive after transmit', 32, 0xffffffff),
                            ('stale reference', 16, module.NTP_EPOCH + 1),
                            ('excessive dispersion', 8, 65536)]:
    evidence = copy.deepcopy(original)
    packet = bytearray.fromhex(evidence['response_hex'])
    struct.pack_into('!I', packet, offset, value)
    evidence['response_hex'] = packet.hex()
    try:
        module.assess(evidence)
    except AssertionError:
        continue
    raise AssertionError('Accepted ' + name)
evidence = copy.deepcopy(original)
evidence['rtc']['rtc_epoch'] += 791
assert not module.assess(evidence)['rtc_within_two_seconds_in_this_sample']
print('Actual packet replay passed;13 malformed/stale packet cases and791s RTC offset rejected.')
print(json.dumps(verdict, indent=2))
