#!/usr/bin/env python3
"""Decode one V4L2 pBAA (MIPI packed BGGR10) frame to viewable PGM."""

import argparse
from array import array
from pathlib import Path


def percentile(histogram, sample_count, fraction):
    target = max(1, int(sample_count * fraction))
    total = 0
    for value, count in enumerate(histogram):
        total += count
        if total >= target:
            return value
    return len(histogram) - 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=2592)
    parser.add_argument("--height", type=int, default=1944)
    parser.add_argument("--stride", type=int, default=3248)
    parser.add_argument("--frame", type=int, default=-1,
                        help="zero-based frame index; -1 selects the last frame")
    args = parser.parse_args()

    if args.width % 4:
        parser.error("packed RAW10 width must be divisible by four")
    packed_row = args.width * 5 // 4
    if args.stride < packed_row:
        parser.error("stride is shorter than the packed row")

    raw = args.input.read_bytes()
    frame_size = args.stride * args.height
    if not raw or len(raw) % frame_size:
        parser.error(
            f"input size {len(raw)} is not a multiple of frame size {frame_size}"
        )
    frame_count = len(raw) // frame_size
    frame_index = args.frame if args.frame >= 0 else frame_count + args.frame
    if frame_index < 0 or frame_index >= frame_count:
        parser.error(f"frame {args.frame} is outside the {frame_count}-frame input")

    start = frame_index * frame_size
    frame = memoryview(raw)[start:start + frame_size]
    pixels = array("H")
    histogram = [0] * 1024

    for row_index in range(args.height):
        row_start = row_index * args.stride
        row = frame[row_start:row_start + packed_row]
        for offset in range(0, packed_row, 5):
            byte0, byte1, byte2, byte3, low_bits = row[offset:offset + 5]
            values = (
                byte0 << 2 | (low_bits & 0x03),
                byte1 << 2 | ((low_bits >> 2) & 0x03),
                byte2 << 2 | ((low_bits >> 4) & 0x03),
                byte3 << 2 | ((low_bits >> 6) & 0x03),
            )
            pixels.extend(values)
            for value in values:
                histogram[value] += 1

    # A linear 0..1023 mapping makes the unprocessed OV5693 frame nearly
    # black. Stretch the central 99% for a diagnostic preview while leaving
    # the original RAW10 file untouched for real processing.
    low = percentile(histogram, len(pixels), 0.005)
    high = percentile(histogram, len(pixels), 0.995)
    if high <= low:
        high = low + 1
    scale = 255.0 / (high - low)
    preview = bytearray(len(pixels))
    for index, value in enumerate(pixels):
        preview[index] = (
            0 if value <= low else
            255 if value >= high else
            int((value - low) * scale + 0.5)
        )

    header = f"P5\n{args.width} {args.height}\n255\n".encode("ascii")
    args.output.write_bytes(header + preview)
    print(
        f"decoded frame {frame_index}/{frame_count - 1}: "
        f"{args.width}x{args.height}, stretch {low}..{high}, output {args.output}"
    )


if __name__ == "__main__":
    main()
