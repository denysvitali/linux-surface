#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare all12 measured pixels to explicit half conversion rounding hypotheses."""
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def single(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def half_rtz(value):
    assert math.isfinite(value) and abs(value) <= 65504
    bits = struct.unpack('H', struct.pack('e', value))[0]
    rounded = struct.unpack('e', struct.pack('H', bits))[0]
    if abs(rounded) > abs(value):
        bits -= 1
    return struct.unpack('e', struct.pack('H', bits))[0]


def model(precision):
    casts = []

    def cast(value, color=False):
        converted = half_rtz(value) if precision == 'mediump' or color else single(value)
        relative_error = abs(converted - value) / abs(value) if value else 0
        if precision == 'mediump' or color:
            assert relative_error <= 2**-10
        casts.append({'input': value, 'output': converted, 'color_assignment': color,
                      'relative_error': relative_error})
        return converted

    product = single(single(293.5 * 89.5) * single(.0001))
    d = cast(product - math.floor(product))
    trace = [d]
    for _ in range(5):
        value = cast((2 if d >= .5 else 3) * d)
        d = cast(value - math.floor(value))
        trace.append(d)
    # ESSL1.00 gl_FragColor is mediump, including with highp local arithmetic.
    pixels = [round(cast(value, color=True) * 255) for value in trace]
    return {'d_by_step': trace, 'pixels': pixels, 'conversion_hypotheses': casts}


def main():
    root = Path(sys.argv[1])
    expected = json.loads((root / 'sha256.json').read_text())
    assert not any(p.is_symlink() for p in root.rglob('*'))
    assert {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()} == (
        expected | {'sha256.json': sha(root / 'sha256.json')})
    report = json.loads((root / 'result.json').read_text())
    measured = json.loads((root / 'stdout.json').read_text())
    assert report['precision_readback'] == measured and report['diagnostic_completed']
    assert measured['medium_float_precision'] == 10
    models = {p: model(p) for p in ('mediump', 'highp')}
    for sample in measured['samples']:
        pixel = models[sample['precision']]['pixels'][sample['steps']]
        assert sample['rgba'] == [pixel, pixel, pixel, 255]
    assert len(measured['samples']) == 12
    print(json.dumps({'boot_id': report['boot_id'], 'readback_manifest_sha256': sha(root / 'sha256.json'),
        'models': models, 'all_twelve_pixels_match': True,
        'mediump_matches_retained_glmark_failed_pixel': models['mediump']['pixels'][-1] == 27,
        'highp_within_original_oracle_per_channel_tolerance': abs(models['highp']['pixels'][-1] - 37) <= 5,
        'actual_shader_instruction_rounding_traced': False,
        'driver_conformance_established': False, 'hardware_acceptance_closed': False,
        'limits': ['Exact agreement supports the explicit RTZ conversion model; it is not instruction tracing.',
                  'Measured on returned known-good only; no new mainline precision diagnostic run.',
                  'Original glmark2 default-precision Failure remains unchanged.']}, indent=2))


if __name__ == '__main__':
    main()
