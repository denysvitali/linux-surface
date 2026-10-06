#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Capability-only CDSP query; no process creation or workload invocation."""
import fcntl
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import time


NODE = '/soc/remoteproc@8300000/glink-edge/fastrpc'
GET_DSP_INFO = 0xC01C520D  # _IOWR('R', 13, seven uint32 words)
ATTRIBUTES = {1: 'unsigned_pd_support', 2: 'hvx_64b', 3: 'hvx_128b',
              4: 'vtcm_page_size', 5: 'vtcm_page_count', 6: 'architecture'}


def stage(dtb):
    def get(node, prop, kind='s'):
        return subprocess.check_output(['fdtget', '-t', kind, str(dtb), node, prop], text=True).strip()

    assert 'microsoft,surface-pro-x' in get('/', 'compatible').split()
    assert get(NODE, 'label') == 'cdsp'
    assert get(NODE, 'status') == 'disabled', 'capability trial requires the disabled opt-in node'
    cb = NODE + '/compute-cb@1'
    assert get(cb, 'compatible') == 'qcom,fastrpc-compute-cb'
    assert get(cb, 'reg', 'u') == '1'
    assert get(cb, 'iommus', 'x').split()[-2:] == ['1441', '0']
    subprocess.run(['fdtput', '-t', 's', str(dtb), NODE, 'status', 'okay'], check=True)
    assert get(NODE, 'status') == 'okay'


def translated_session():
    found = []
    for device in Path('/sys/bus/platform/devices').iterdir():
        node = device / 'of_node'
        compatible = node / 'compatible'
        if not compatible.is_file() or b'qcom,fastrpc-compute-cb\0' not in compatible.read_bytes():
            continue
        if (node.resolve().parent / 'label').read_bytes().rstrip(b'\0') != b'cdsp':
            continue
        assert (node / 'reg').read_bytes() == struct.pack('>I', 1)
        cells = struct.unpack('>III', (node / 'iommus').read_bytes())
        assert cells[1:] == (0x1441, 0)
        assert (device / 'driver').resolve().name == 'qcom,fastrpc-cb'
        group = (device / 'iommu_group').resolve(strict=True)
        kind = (group / 'type').read_text().strip()
        assert kind in ('DMA', 'DMA-FQ'), 'identity/unmanaged domains are forbidden'
        members = list((group / 'devices').iterdir())
        assert len(members) == 1 and members[0].resolve() == device.resolve()
        found.append(dict(device=str(device.resolve()), iommu_group=str(group),
                          domain_type=kind, session=1, stream_id='0x1441'))
    assert len(found) == 1, 'exactly one translated CDSP session is required'
    return found[0]


def query(output, attempt, release):
    """Caller holds the device lock and bounds this process to 25 seconds."""
    output.mkdir(mode=0o700)
    result = dict(complete=False, scope='GET_DSP_INFO only; no PD creation or compute',
                  attempt=attempt, release=release,
                  boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  capabilities={})

    def save():
        temporary = output / 'result.json.tmp'
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        os.replace(temporary, output / 'result.json')

    save()
    try:
        words = Path('/proc/cmdline').read_text().split()
        assert os.geteuid() == 0, 'coordinator must run this query as root'
        assert os.uname().release == release, 'query requires the matching mainline trial kernel'
        assert 'spx_attempt=' + attempt in words and 'spx_boot=mainline-functional' in words
        assert 'spx_cdsp=1' in words
        assert Path('/sys/devices/soc0/soc_id').read_text().strip() == '340'
        baseline = json.loads((output.parent / 'functional.json').read_text())
        assert baseline.get('complete') and baseline['boot_id'] == result['boot_id']
        prepared = json.loads((output.parent / 'prepared.json').read_text())
        assert prepared.get('cdsp_capabilities'), 'trial must explicitly enable capability transport'
        assert subprocess.check_output(['systemctl', 'is-active',
            'spx-trial-return@' + attempt + '.timer'], text=True, timeout=5).strip() == 'active'
        # Read the raw D-Bus uint64, avoiding systemctl's formatted timespan.
        raw = subprocess.check_output(['busctl', 'get-property', 'org.freedesktop.systemd1',
            '/org/freedesktop/systemd1/unit/spx_2dtrial_2dreturn_40' + attempt + '_2etimer',
            'org.freedesktop.systemd1.Timer', 'NextElapseUSecMonotonic'], text=True, timeout=5).split()
        assert raw[0] == 't' and int(raw[1]) / 1e6 - time.monotonic() >= 90
        result['session'] = translated_session()
        device = Path('/dev/fastrpc-cdsp-secure')
        metadata = device.stat()
        assert stat.S_ISCHR(metadata.st_mode) and metadata.st_uid == 0
        assert stat.S_IMODE(metadata.st_mode) & 0o077 == 0, 'keep the trial device private'
        save()
        descriptor = os.open(device, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            for attribute, name in ATTRIBUTES.items():
                payload = bytearray(struct.pack('<7I', 0, attribute, 0, 0, 0, 0, 0))
                # First call obtains the whole attribute array; later calls use its kernel cache.
                fcntl.ioctl(descriptor, GET_DSP_INFO, payload, True)
                unused, returned, value, *reserved = struct.unpack('<7I', payload)
                assert unused == 0 and returned == attribute and not any(reserved)
                result['capabilities'][name] = value
                save()
        finally:
            os.close(descriptor)
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == result['boot_id']
        result['complete'] = True
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        save()
    return result
