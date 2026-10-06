#!/usr/bin/env python3
"""Bounded public TPM2 capability, PCR-read and GetRandom client.

Run under an outer timeout. Wire formats follow the kernel TPM2 selftest.
No authorization, persistent objects, provisioning or PCR writes are used.
"""
import argparse
import json
import os
from pathlib import Path
import struct


def command(device, opcode, payload):
    request = struct.pack('>HII', 0x8001, 10 + len(payload), opcode) + payload
    if device.write(request) != len(request):
        raise RuntimeError('Short TPM command write')
    response = device.read(4096)
    if len(response) < 10:
        raise RuntimeError('Short TPM response')
    tag, length, status = struct.unpack('>HII', response[:10])
    if tag != 0x8001 or length != len(response) or status:
        raise RuntimeError(f'Invalid TPM response: tag={tag:#x}, length={length}, status={status:#x}')
    return response[10:]


def capability(device, kind, first, count):
    data = command(device, 0x17a, struct.pack('>III', kind, first, count))
    more, returned_kind, entries = struct.unpack('>BII', data[:9])
    if returned_kind != kind or more not in (0, 1) or entries > count:
        raise RuntimeError('Invalid capability header')
    return entries, data[9:]


def check(device):
    count, data = capability(device, 6, 0x100, 64)
    if len(data) != count * 8:
        raise RuntimeError('Invalid property response length')
    properties = dict(struct.unpack('>II', data[i:i + 8]) for i in range(0, len(data), 8))
    if properties.get(0x100) != 0x322e3000:
        raise RuntimeError('Firmware does not report TPM2 family')
    manufacturer = struct.pack('>I', properties[0x105]).decode('ascii', errors='replace')
    bank_count, data = capability(device, 5, 0, 16)
    banks = {}
    for _ in range(bank_count):
        algorithm, size = struct.unpack('>HB', data[:3])
        if not 1 <= size <= 4 or len(data) < 3 + size:
            raise RuntimeError('Invalid PCR selection size')
        banks[algorithm] = data[3:3 + size]
        data = data[3 + size:]
    if data:
        raise RuntimeError('Trailing PCR capability data')
    algorithm = next((a for a in (0xb, 4) if a in banks and banks[a][0] & 1), None)
    if algorithm is None:
        raise RuntimeError('No supported active PCR0 bank')
    data = command(device, 0x17e, struct.pack('>IHB', 1, algorithm, 3) + b'\x01\x00\x00')
    update, selection_count, returned_algorithm, size = struct.unpack('>IIHB', data[:11])
    if selection_count != 1 or returned_algorithm != algorithm or size != 3 or data[11:14] != b'\x01\x00\x00':
        raise RuntimeError('Unexpected PCR response selection')
    digest_count, digest_size = struct.unpack('>IH', data[14:20])
    digest = data[20:]
    if digest_count != 1 or digest_size != len(digest) or digest_size != (32 if algorithm == 0xb else 20):
        raise RuntimeError('Invalid PCR digest')
    random_samples = []
    for _ in range(2):
        data = command(device, 0x17b, struct.pack('>H', 32))
        size = struct.unpack('>H', data[:2])[0]
        if not 0 < size <= 32 or size != len(data) - 2:
            raise RuntimeError('Invalid GetRandom response')
        random_samples.append(data[2:])
    if random_samples[0] == random_samples[1] or any(not any(s) for s in random_samples):
        raise RuntimeError('Repeated or zero GetRandom output')
    return {'manufacturer': manufacturer, 'properties': properties,
            'pcr_banks': {a: s.hex() for a, s in banks.items()},
            'pcr0_algorithm': algorithm, 'pcr0': digest.hex(), 'pcr_update': update,
            'getrandom_lengths': [len(s) for s in random_samples],
            'getrandom_different_nonzero': True, 'complete': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--device', default='/dev/tpmrm0', choices=('/dev/tpmrm0', '/dev/tpm0'))
    args = parser.parse_args()
    result = {'complete': False, 'device': args.device,
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'kernel_release': os.uname().release}
    try:
        with open(args.device, 'r+b', buffering=0) as device:
            result.update(check(device))
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps(result, indent=2))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
