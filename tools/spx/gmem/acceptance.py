#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""A680 GMEM-base acceptance: loaded msm identity plus unpatched-driver pixel tests.

The system-wide Turnip workaround hides the defect, so every run here builds its
own environment from scratch and names the driver explicitly. Caller holds the
device lock. A failed pixel comparison is a result, not an exception.
"""
import json
import os
from pathlib import Path
import re
import struct
import subprocess

DISTRO_ICD = '/usr/share/vulkan/icd.d/freedreno_icd.json'
INSTALLED_TEST = '/usr/local/lib/spx-turnip/spx-vk-partial-load-store'
GMEM_BASE = 0x200000
STORE_LOG = re.compile(r'SPX store_cp_blit:.*gmem_offset=0x([0-9a-f]+) va=0x([0-9a-f]+)')
TAIL = 4000


def msm_build_id(note='/sys/module/msm/notes/.note.gnu.build-id'):
    data = Path(note).read_bytes()
    name_size, desc_size, kind = struct.unpack_from('<III', data)
    assert kind == 3, 'not a GNU build-id note'
    start = 12 + (name_size + 3) // 4 * 4
    return data[start:start + desc_size].hex()


def module_build_id(path):
    """GNU build ID of a module file, as reported by readelf."""
    text = subprocess.check_output(['readelf', '-n', str(path)], text=True)
    found = re.findall(r'Build ID: ([0-9a-f]+)', text)
    assert len(found) == 1, 'module must carry exactly one GNU build ID'
    return found[0]


def plan(diagnostic_test, diagnostic_icd):
    """(name, environment, argv); environment never inherits the caller's."""
    base = {'PATH': '/usr/bin:/bin', 'HOME': '/root'}
    runs = []
    for debug in ('gmem', 'gmem,unaligned_store'):
        runs.append(('distro-' + debug.replace(',', '+'),
                     dict(base, VK_DRIVER_FILES=DISTRO_ICD, TU_DEBUG=debug), [INSTALLED_TEST]))
    runs.append(('diagnostic-no-clear-full',
                 dict(base, VK_DRIVER_FILES=str(diagnostic_icd), TU_DEBUG='gmem',
                      SPX_NO_COND='1', SPX_LOG_STORE='1'),
                 [str(diagnostic_test), '--single', '1', '1', '2877', '1917', '--no-clear']))
    return runs


def judge(name, code, output):
    """Return (passed, notes) from one run's exit status and combined output."""
    notes = []
    device = re.search(r'(?m)^Device: ([^\r\n]+)', output)
    if not device or 'turnip' not in device.group(1).lower():
        notes.append('hardware Turnip device line missing')
    if code != 0 or not re.search(r'(?m)^PASS;', output):
        notes.append('exit %s without PASS' % code)
        for line, count in re.findall(r'(?m)^([0-9]+x[0-9]+ frame=-?[0-9]+: ([0-9]+)/[0-9]+ pixels differ)', output):
            if count.lstrip('0'):
                notes.append(line)
                break
    if name.startswith('diagnostic'):
        stores = STORE_LOG.findall(output)
        if not stores:
            notes.append('no GMEM tile-store log lines: slow store path not exercised')
        for offset, va in stores:
            if int(va, 16) - int(offset, 16) != GMEM_BASE:
                notes.append('GMEM base is 0x%x, not 0x%x' % (int(va, 16) - int(offset, 16), GMEM_BASE))
                break
    return not notes, notes


def exercise(output, attempt, release, expected_build_id, diagnostic_test, diagnostic_icd, run=subprocess.run):
    output.mkdir(mode=0o700)
    result = dict(complete=False, accepted=False, attempt=attempt, release=release,
                  scope='unpatched-driver partial LOAD/STORE and unconditional no-clear GMEM store; '
                        'not general Vulkan conformance',
                  expected_msm_build_id=expected_build_id,
                  boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(), runs={})

    def save():
        temporary = output / 'result.json.tmp'
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        os.replace(temporary, output / 'result.json')

    save()
    try:
        words = Path('/proc/cmdline').read_text().split()
        assert os.geteuid() == 0 and os.uname().release == release
        assert 'spx_attempt=' + attempt in words and 'spx_boot=mainline-functional' in words
        result['loaded_msm_build_id'] = msm_build_id()
        result['identity_matches'] = result['loaded_msm_build_id'] == expected_build_id
        save()
        for name, environment, argv in plan(diagnostic_test, diagnostic_icd):
            proc = run(['timeout', '--kill-after=3s', '90s'] + argv, env=environment,
                       capture_output=True, text=True, timeout=100)
            text = proc.stdout + proc.stderr
            (output / (name + '.log')).write_text(text)
            passed, notes = judge(name, proc.returncode, text)
            result['runs'][name] = dict(returncode=proc.returncode, passed=passed, notes=notes,
                                        tail=text[-TAIL:])
            save()
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == result['boot_id']
        result['complete'] = True
        result['accepted'] = result['identity_matches'] and all(r['passed'] for r in result['runs'].values())
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        save()
    return result
