# SPDX-License-Identifier: GPL-2.0-only
"""Offline RAW10 processing for the Surface camera capture helper."""
from array import array
from collections import Counter
import math
import subprocess
import sys


def unpack(frame, width, height, stride):
    """Decode all ten bits of pgAA, excluding row padding."""
    if width < 4 or width % 4 or height < 2 or height % 2:
        raise ValueError('invalid packed RAW10 dimensions')
    if stride < width * 5 // 4 or len(frame) < stride * height:
        raise ValueError('invalid RAW10 stride or truncated frame')
    samples = array('H')
    for row in range(height):
        start = row * stride
        for offset in range(start, start + width * 5 // 4, 5):
            low = frame[offset + 4]
            samples.extend((frame[offset + phase] << 2) | ((low >> (phase * 2)) & 3)
                           for phase in range(4))
    return samples


def demosaic(samples, width, height, bayer='GRBG'):
    """Convert linear Bayer data to RGB without discarding the low bits."""
    if len(samples) != width * height:
        raise ValueError('incorrect Bayer sample count')
    source = array('H', (value << 6 for value in samples))
    if sys.byteorder != 'little':
        source.byteswap()
    result = subprocess.run(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
         '-pixel_format', 'bayer_%s16le' % bayer.lower(),
         '-video_size', '%dx%d' % (width, height),
         '-i', 'pipe:0', '-frames:v', '1', '-pix_fmt', 'rgb48le',
         '-f', 'rawvideo', 'pipe:1'], input=source.tobytes(), capture_output=True,
        check=True, timeout=30)
    if len(result.stdout) != width * height * 6:
        raise ValueError('incomplete demosaiced frame')
    rgb = array('H')
    rgb.frombytes(result.stdout)
    if sys.byteorder != 'little':
        rgb.byteswap()
    return rgb


def colour_gains(samples, width, height, black, bayer='GRBG'):
    """Grey-world AWB in the linear domain, after a common black subtraction.

    This is an estimate, not a module calibration. As with libcamera's simple
    ISP, a scene dominated by one colour can bias it. Never infer neutral
    objects or invent a colour-correction matrix from an unlabelled scene.
    """
    if bayer not in ('GRBG', 'BGGR', 'GBRG', 'RGGB'):
        raise ValueError('unsupported Bayer order')
    channels = {'R': 0, 'G': 1, 'B': 2}
    sums = [0, 0, 0]
    counts = [0, 0, 0]
    for y in range(0, height, 2):
        row, next_row = y * width, (y + 1) * width
        for x in range(0, width, 2):
            for phase, offset in enumerate((row + x, row + x + 1,
                                            next_row + x, next_row + x + 1)):
                channel = channels[bayer[phase]]
                sums[channel] += max(0, samples[offset] - black)
                counts[channel] += 1
    sums = [total / count for total, count in zip(sums, counts)]
    if min(sums) == 0:
        return (1.0, 1.0, 1.0), False
    return (max(0.25, min(4.0, sums[1] / sums[0])), 1.0,
            max(0.25, min(4.0, sums[1] / sums[2]))), True


def srgb(value):
    """Encode a normalized linear value with the standard sRGB transfer."""
    value = max(0.0, min(1.0, value))
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def rotate(rgb, width, height, rotation):
    """Rotate RGB pixels, never Bayer phases, preserving aspect ratio."""
    if rotation not in (0, 90, 180, 270):
        raise ValueError('rotation must be 0, 90, 180 or 270 degrees clockwise')
    if len(rgb) != width * height * 3:
        raise ValueError('incorrect RGB buffer size')
    if rotation == 0:
        return bytes(rgb), width, height
    if rotation == 180:
        output = bytearray(len(rgb))
        for channel in range(3):
            output[channel::3] = rgb[channel::3][::-1]
        return bytes(output), width, height
    output = bytearray(len(rgb))
    for y in range(height):
        for x in range(width):
            dx, dy = (height - 1 - y, x) if rotation == 90 else (y, width - 1 - x)
            source, target = (y * width + x) * 3, (dy * height + dx) * 3
            output[target:target + 3] = rgb[source:source + 3]
    return bytes(output), height, width


def render(samples, width, height, destination, rotation=0, black=64, gains=None,
           bayer='GRBG'):
    """Render a display preview; report estimates separately from calibration.

    The provisional RAW10 black level is the simple ISP default (16 in the
    eight-MSB view), not a measured optical-black calibration. Callers can
    override it. Exposure normalization is common to all balanced channels.
    """
    if width < 4 or width % 4 or height < 2 or height % 2:
        raise ValueError('invalid GRBG dimensions')
    if len(samples) != width * height or any(not 0 <= v <= 1023 for v in samples):
        raise ValueError('invalid ten-bit Bayer samples')
    if not math.isfinite(black) or not 0 <= black < 1023:
        raise ValueError('black level must be in [0, 1023)')
    if rotation not in (0, 90, 180, 270):
        raise ValueError('invalid clockwise rotation')
    automatic = gains is None
    if automatic:
        gains, valid = colour_gains(samples, width, height, black, bayer)
    else:
        valid = True
    if len(gains) != 3 or any(not math.isfinite(g) or not 0 < g <= 16 for g in gains):
        raise ValueError('invalid RGB colour gains')
    linear = demosaic(samples, width, height, bayer)
    histograms = [Counter(linear[channel::3]) for channel in range(3)]
    balanced = Counter()
    for channel, histogram in enumerate(histograms):
        for value, count in histogram.items():
            balanced[max(0, value / 64 - black) * gains[channel]] += count
    threshold = int((len(linear) - 1) * 0.998)
    seen, white = 0, 0
    for value, count in sorted(balanced.items()):
        seen += count
        if seen > threshold:
            white = value
            break
    # A uniform scene is not evidence of darkness or a suitable exposure target.
    # Do not stretch constant buffers or amplify a frame with no AWB signal.
    normalize = valid and len(balanced) > 1 and white > 0
    white = white if normalize else 1023 - black
    tables = [bytes(round(255 * srgb(max(0, v / 64 - black) * gain / white))
                    for v in range(65536)) for gain in gains]
    rgb = bytearray(len(linear))
    for channel in range(3):
        rgb[channel::3] = bytes(tables[channel][v] for v in linear[channel::3])
    rgb, out_width, out_height = rotate(rgb, width, height, rotation)
    destination.write_bytes(b'P6\n%d %d\n255\n' % (out_width, out_height) + rgb)
    return dict(file=destination.name, bayer=bayer, raw_bits=10, black_level=black,
                black_level_calibrated=False, white_level=white, exposure_normalized=normalize,
                white_balance='grey-world' if automatic else 'manual', awb_valid=valid,
                gains=list(gains), transfer='sRGB', rotation=rotation,
                colour_calibrated=False)


def main():
    import argparse
    import json
    import os
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--width', required=True, type=int)
    parser.add_argument('--height', required=True, type=int)
    parser.add_argument('--stride', type=int)
    parser.add_argument('--msb8', action='store_true', help='saved high-byte Bayer, not packed RAW10')
    parser.add_argument('--rotation', type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument('--bayer', choices=('GRBG', 'BGGR', 'GBRG', 'RGGB'), default='GRBG')
    parser.add_argument('--black-level', type=float, default=64)
    parser.add_argument('--gains', nargs=3, type=float, metavar=('R', 'G', 'B'))
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve() or args.destination.exists():
        parser.error('destination must be new and different from the raw source')
    data = args.source.read_bytes()
    if args.msb8:
        if len(data) != args.width * args.height:
            parser.error('incorrect high-byte Bayer length')
        samples = array('H', (v << 2 for v in data))
    else:
        samples = unpack(data, args.width, args.height,
                         args.stride or args.width * 5 // 4)
    # Keep scene previews private from their creation, like their raw source.
    descriptor = os.open(args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    result = render(samples, args.width, args.height, args.destination,
                    rotation=args.rotation, black=args.black_level, gains=args.gains,
                    bayer=args.bayer)
    result['source_bits'] = 8 if args.msb8 else 10
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
