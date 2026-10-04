#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One independent NTP query and RTC readback; never discipline either clock."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import struct
import subprocess
import time

NTP_EPOCH = 2208988800
PROBE = Path('/usr/local/lib/spx-boot-diagnostics/rtc-readonly-20261003ax')
PROBE_SHA = '155ea047bea75da77a7b8bb89fe10d854e235bfedb1b0cdbcb2cae0f0a654b13'


def timestamp(packet, offset):
    seconds, fraction = struct.unpack_from('!II', packet, offset)
    assert seconds >= NTP_EPOCH, 'Unsupported NTP era or zero timestamp'
    return seconds - NTP_EPOCH + fraction / 2**32


def assess(evidence):
    request, response = bytes.fromhex(evidence['request_hex']), bytes.fromhex(evidence['response_hex'])
    assert len(request) == len(response) == 48, 'Unexpected packet size/extensions'
    assert request[0] == 0x23 and response[0] & 7 == 4
    assert (response[0] >> 3) & 7 in (3, 4) and response[0] >> 6 != 3
    assert 1 <= response[1] <= 15, 'Unsynchronized server or kiss-of-death'
    assert response[24:32] == request[40:48] and any(response[24:32]), 'Origin mismatch'
    receive, transmit, reference = (timestamp(response, p) for p in (32, 40, 16))
    rtt = evidence['receive_boottime'] - evidence['send_boottime']
    assert 0 <= rtt <= 1, 'Round trip outside one-second bound'
    assert 0 <= transmit - receive <= rtt + .01
    assert 0 <= transmit - reference <= 1800
    root_delay = struct.unpack_from('!i', response, 4)[0] / 65536
    root_dispersion = struct.unpack_from('!I', response, 8)[0] / 65536
    precision = struct.unpack_from('!b', response, 3)[0]
    assert -40 <= precision <= 0
    uncertainty = max(0, root_delay) / 2 + root_dispersion + 2.0**precision
    assert uncertainty <= .5, 'Reported server uncertainty too large'
    wall_span = evidence['receive_realtime'] - evidence['send_realtime']
    assert abs(wall_span - rtt) < .01, 'System clock step during query'
    rtc = evidence['rtc']
    read_span = rtc['realtime_after'] - rtc['realtime_before']
    elapsed = evidence['receive_boottime'] - rtc['monotonic']
    assert 0 <= read_span <= 1 and read_span <= elapsed <= 5
    assert isinstance(rtc['rtc_epoch'], int) and rtc['rtc_epoch'] > 0
    # At receipt, server time is between its transmit timestamp and that time
    # plus the entire RTT. Project integer RTC readback to receipt, retaining
    # its one-second quantization and the entire ioctl bracket. The extra1ms
    # covers local projection rounding; this is not a drift-rate measurement.
    lower = rtc['rtc_epoch'] + elapsed - read_span - transmit - rtt - uncertainty - .001
    upper = rtc['rtc_epoch'] + 1 + elapsed - transmit + uncertainty + .001
    return {'server_stratum': response[1], 'server_receive_epoch': receive,
            'server_transmit_epoch': transmit, 'round_trip_seconds': rtt,
            'reported_server_uncertainty_seconds': uncertainty,
            'rtc_offset_lower_seconds': lower, 'rtc_offset_upper_seconds': upper,
            'rtc_within_two_seconds_in_this_sample': lower >= -2 and upper <= 2,
            'clock_writes': 0, 'network_time_authenticated': False,
            'hardware_acceptance_closed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server', help='Numeric IP of the previously recorded time source')
    args = parser.parse_args()
    address = ipaddress.ip_address(args.server)
    assert hashlib.sha256(PROBE.read_bytes()).hexdigest() == PROBE_SHA
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    evidence = {'boot_id': bid, 'release': subprocess.check_output(['uname', '-r'], text=True).strip(),
                'cmdline': Path('/proc/cmdline').read_text().strip(), 'server': str(address),
                'probe_sha256': PROBE_SHA, 'clock_writes': 0,
                'rtc': json.loads(subprocess.check_output([str(PROBE)], text=True, timeout=5))}
    try:
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3)
            sock.connect((str(address), 123))
            request = bytearray(48)
            request[0], request[2], request[3] = 0x23, 6, 236
            ns = time.time_ns()
            seconds, remainder = divmod(ns, 10**9)
            struct.pack_into('!II', request, 40, seconds + NTP_EPOCH, remainder * 2**32 // 10**9)
            evidence['request_hex'] = request.hex()
            evidence['send_realtime'] = time.time()
            evidence['send_boottime'] = time.clock_gettime(time.CLOCK_BOOTTIME)
            assert sock.send(request) == 48
            response = sock.recv(4096)
            evidence['receive_boottime'] = time.clock_gettime(time.CLOCK_BOOTTIME)
            evidence['receive_realtime'] = time.time()
            evidence['response_hex'] = response.hex()
        evidence['verdict'] = assess(evidence)
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    except Exception as error:
        evidence['failure'] = repr(error)
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
