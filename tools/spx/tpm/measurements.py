#!/usr/bin/env python3
"""Replay the existing TCG2 firmware log and compare static PCRs, read-only.

Wire structures: include/linux/tpm_eventlog.h; TCG PC Client Platform
Firmware Profile. Use an outer timeout for public TPM PCR_Read commands.
This validates recorded digest chains, not the trustworthiness of firmware.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct

from check import command

ALGORITHMS = {4: ('sha1', 20), 11: ('sha256', 32), 12: ('sha384', 48)}


def replay(blob):
    if not 32 <= len(blob) <= 16 * 1024 * 1024:
        raise ValueError('Invalid firmware log size')
    offset = 0

    def take(size):
        nonlocal offset
        if size < 0 or offset + size > len(blob):
            raise ValueError(f'Truncated firmware log at {offset}')
        data = blob[offset:offset + size]
        offset += size
        return data

    def number(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))

    pcr, kind = number('<II')
    take(20)
    size, = number('<I')
    spec = take(size)
    if pcr != 0 or kind != 3 or len(spec) < 29 or spec[:16] != b'Spec ID Event03\0':
        raise ValueError('Expected TCG2 Spec ID Event03 header')
    count, = struct.unpack_from('<I', spec, 24)
    if not 1 <= count <= 16 or len(spec) < 29 + count * 4:
        raise ValueError('Invalid Spec ID algorithm table')
    sizes = {}
    for i in range(count):
        alg, length = struct.unpack_from('<HH', spec, 28 + 4 * i)
        if alg in sizes or not 1 <= length <= 64:
            raise ValueError('Invalid digest algorithm size')
        if alg in ALGORITHMS and length != ALGORITHMS[alg][1]:
            raise ValueError('Incorrect standard digest size')
        sizes[alg] = length
    vendor_size = spec[28 + count * 4]
    if len(spec) != 29 + count * 4 + vendor_size:
        raise ValueError('Invalid Spec ID vendor information')
    chains, extends, events, files = {}, Counter(), Counter(), []
    locality = 0
    for alg in sizes:
        if alg not in ALGORITHMS:
            raise ValueError(f'Unsupported digest algorithm {alg:#x}')
    while offset < len(blob):
        pcr, kind, count = number('<III')
        if pcr >= 24 or not 1 <= count <= len(sizes):
            raise ValueError('Invalid event PCR/digest count')
        digests = {}
        for _ in range(count):
            alg, = number('<H')
            if alg not in sizes or alg in digests:
                raise ValueError('Invalid event digest algorithm')
            digests[alg] = take(sizes[alg])
        size, = number('<I')
        if size > 1024 * 1024:
            raise ValueError('Oversized event data')
        data = take(size)
        events[(pcr, kind)] += 1
        if pcr == 9 and kind == 13:
            files.append((data.rstrip(b'\0'), digests))
        if kind == 3:
            if data.startswith(b'StartupLocality\0'):
                if pcr != 0 or len(data) != 17 or data[16] not in (0, 3):
                    raise ValueError('Invalid StartupLocality event')
                if any(key[1] == 0 for key in chains):
                    raise ValueError('StartupLocality follows PCR0 extension')
                locality = data[16]
            continue
        # Dynamic/resettable PCRs need additional reset/session semantics.
        if pcr >= 16:
            continue
        for alg, digest in digests.items():
            key = (alg, pcr)
            initial = bytes(sizes[alg] - 1) + bytes([locality if pcr == 0 else 0])
            previous = chains.get(key, initial)
            chains[key] = hashlib.new(ALGORITHMS[alg][0], previous + digest).digest()
            extends[key] += 1
    if not chains:
        raise ValueError('No static PCR measurements')
    return chains, extends, events, files


def read_pcr(device, alg, pcr):
    selection = (1 << pcr).to_bytes(3, 'little')
    data = command(device, 0x17e, struct.pack('>IHB', 1, alg, 3) + selection)
    if len(data) < 20:
        raise ValueError('Short PCR_Read response')
    update, count, returned, size = struct.unpack_from('>IIHB', data)
    if (count, returned, size, data[11:14]) != (1, alg, 3, selection):
        raise ValueError('Unexpected PCR_Read selection')
    count, size = struct.unpack_from('>IH', data, 14)
    if count != 1 or size != ALGORITHMS[alg][1] or len(data) != 20 + size:
        raise ValueError('Invalid PCR_Read digest')
    return update, data[20:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--log', type=Path,
                        default=Path('/sys/kernel/security/tpm0/binary_bios_measurements'))
    parser.add_argument('--payload-directory', type=Path,
                        help='compare three trial boot payloads against GRUB PCR9 events')
    args = parser.parse_args()
    result = {'complete': False, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'kernel_release': os.uname().release, 'pcrs': []}
    try:
        blob = args.log.read_bytes()
        chains, extends, events, files = replay(blob)
        result.update(log_bytes=len(blob), event_count=sum(events.values()),
                      event_types={f'{pcr}:{kind:#x}': count for (pcr, kind), count in events.items()})
        with open('/dev/tpmrm0', 'r+b', buffering=0) as device:
            for (alg, pcr), expected in sorted(chains.items()):
                update, observed = read_pcr(device, alg, pcr)
                result['pcrs'].append(dict(algorithm=ALGORITHMS[alg][0], index=pcr,
                    extensions=extends[(alg, pcr)], expected=expected.hex(),
                    observed=observed.hex(), matches=observed == expected, update_counter=update))
        result['complete'] = all(p['matches'] for p in result['pcrs'])
        if args.payload_directory:
            root = args.payload_directory
            relative = root.relative_to('/boot')
            measurements = []
            for name in ('vmlinuz', 'initramfs.img', 'spx.dtb'):
                label = ('/' + str(relative / name)).encode()
                entries = [digests for path, digests in files if path == label]
                if len(entries) != 1 or 11 not in entries[0]:
                    raise ValueError(f'Missing or duplicate SHA256 payload measurement: {name}')
                actual = hashlib.sha256((root / name).read_bytes()).digest()
                measurements.append(dict(file=name, algorithm='sha256',
                    matches=actual == entries[0][11]))
            result['payload_measurements'] = measurements
            result['complete'] &= all(m['matches'] for m in measurements)
        if not result['complete']:
            result['error'] = 'Firmware log digest chain does not match live PCRs'
    except Exception as error:
        result['complete'] = False
        result['error'] = f'{type(error).__name__}: {error}'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in ('pcrs', 'event_types')}))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
