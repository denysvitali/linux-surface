#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce the missed short FD and exercise candidate/reference sampling equally."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from collect import drm_nodes, sampling_delay


def run(root, delay):
    target = root / 'mock-render'
    target.write_bytes(b'synthetic fixture, no hardware')
    code = ('import os,sys,time;time.sleep(.05);'
            'f=os.open(sys.argv[1],os.O_RDONLY);time.sleep(.20);os.close(f)')
    process = subprocess.Popen([sys.executable, '-c', code, str(target)])
    samples = []
    try:
        while process.poll() is None:
            nodes = drm_nodes(process.pid, str(root) + '/')
            samples.append(nodes)
            time.sleep(delay(bool(any(samples))))
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return samples


def main():
    with tempfile.TemporaryDirectory(prefix='spx-aw-fd-synthetic-') as temporary:
        root = Path(temporary)
        old = run(root, lambda _: 5)
        assert old == [[]], old
        tested = []
        for reference in (False, True):
            for validation in (False, True):
                for _ in range(3):
                    samples = run(root, lambda seen: sampling_delay(reference, validation, seen))
                    assert any(samples), (reference, validation, samples)
                    tested.append({'reference_smoke': reference, 'validation': validation,
                                   'samples': len(samples), 'fd_witnessed': True})
        assert sampling_delay(False, True, True) == sampling_delay(True, True, True) == .02
        assert sampling_delay(False, False, True) == 5
        assert sampling_delay(True, False, True) == .2
        assert sampling_delay(False, False, False) == .02
        assert drm_nodes(2147483647) == []
        print(json.dumps({'synthetic_only': True, 'hardware_acceptance_closed': False,
                          'original_missed_short_FD_reproduced': True,
                          'new_sampling_cases': tested, 'reference_candidate_validation_same': True}))


if __name__ == '__main__':
    main()
