#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit CPU rounding hypotheses for the retained conditional pixel; no GL."""
import json
import math
import struct


def single(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def half(value):
    return struct.unpack('e', struct.pack('e', value))[0]


def model(cast):
    # The captured source first multiplies the highp fragment coordinate, then
    # assigns fract() to default-precision d. This hypothesis keeps those first
    # operations binary32 and rounds subsequent storage/arithmetic as specified.
    coordinate = [293.5, 89.5]
    product = single(single(coordinate[0] * coordinate[1]) * single(.0001))
    d = cast(product - math.floor(product))
    trace = [d]
    for _ in range(5):
        value = cast((2 if d >= .5 else 3) * d)
        d = cast(value - math.floor(value))
        trace.append(d)
    return {'coordinate_hypothesis': coordinate, 'initial_product': product,
            'd_by_step': trace, 'linear_unorm8_rounding_hypothesis': round(d * 255)}


if __name__ == '__main__':
    result = {'binary32': model(single), 'binary16_after_highp_initial_expression': model(half),
              'retained_glmark_oracle': 0x25, 'retained_gles_actual': 0x1b,
              'driver_conformance_established': False, 'hardware_acceptance_closed': False,
              'limits': ['CPU hypotheses do not observe GPU instructions, actual fragment coordinates, '
                         'optimization order, color conversion or dithering.',
                         'A numerical model is not an independent software renderer control.']}
    result['binary16_hypothesis_reproduces_retained_failure'] = (
        result['binary16_after_highp_initial_expression']['linear_unorm8_rounding_hypothesis'] == 0x1b)
    print(json.dumps(result, indent=2))
