#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline colour, RAW10 packing and coordinate tests; no camera capture."""
from array import array
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import camera
import camera_render as render


def pack(samples, width, height, padding=0):
    frame = bytearray()
    for y in range(height):
        for x in range(0, width, 4):
            group = samples[y * width + x:y * width + x + 4]
            frame.extend(value >> 2 for value in group)
            frame.append(sum((value & 3) << (phase * 2) for phase, value in enumerate(group)))
        frame.extend(b'\xa5' * padding)
    return bytes(frame)


def bayer(width, height, r, g, b):
    return array('H', (g if x % 2 == y % 2 else r if y % 2 == 0 else b
                       for y in range(height) for x in range(width)))


def bggr(width, height, r, g, b):
    return array('H', (b if x % 2 == 0 and y % 2 == 0 else
                       r if x % 2 == 1 and y % 2 == 1 else g
                       for y in range(height) for x in range(width)))


class Raw10(unittest.TestCase):
    def test_all_low_bits_and_padding(self):
        samples = array('H', [0, 1, 2, 3, 1020, 1021, 1022, 1023] * 2)
        self.assertEqual(render.unpack(pack(samples, 8, 2, 7), 8, 2, 17), samples)

    def test_invalid_buffers(self):
        for width, height, stride, data in [(0, 2, 0, b''), (6, 2, 10, bytes(20)),
                                            (8, 3, 10, bytes(30)), (8, 2, 9, bytes(20)),
                                            (8, 2, 10, bytes(19))]:
            with self.subTest(width=width, height=height, stride=stride):
                with self.assertRaises(ValueError):
                    render.unpack(data, width, height, stride)

    def test_white_balance_after_black_subtraction(self):
        gains, valid = render.colour_gains(bayer(8, 8, 164, 264, 114), 8, 8, 64)
        self.assertTrue(valid)
        self.assertEqual(gains, (2.0, 1.0, 4.0))
        self.assertEqual(render.colour_gains(bayer(8, 8, 64, 64, 64), 8, 8, 64),
                         ((1.0, 1.0, 1.0), False))

        front_gains, valid = render.colour_gains(
            bggr(8, 8, 164, 264, 114), 8, 8, 64, 'BGGR')
        self.assertTrue(valid)
        self.assertEqual(front_gains, (2.0, 1.0, 4.0))

    def test_transfer_reference_points(self):
        self.assertEqual(render.srgb(0), 0)
        self.assertAlmostEqual(render.srgb(1), 1)
        self.assertAlmostEqual(render.srgb(.0031308), .040449936)
        self.assertAlmostEqual(render.srgb(.18), .4613561295)

    def test_coordinate_transforms_keep_rgb_triples(self):
        # Non-square input, every pixel/channel distinct.
        source = bytes(range(18))
        expected = {0: [0, 1, 2, 3, 4, 5], 90: [3, 0, 4, 1, 5, 2],
                    180: [5, 4, 3, 2, 1, 0], 270: [2, 5, 1, 4, 0, 3]}
        for angle, order in expected.items():
            output, width, height = render.rotate(source, 3, 2, angle)
            self.assertEqual((width, height), (3, 2) if angle in (0, 180) else (2, 3))
            self.assertEqual(output, b''.join(source[i * 3:i * 3 + 3] for i in order))
        with self.assertRaises(ValueError):
            render.rotate(source, 3, 2, 45)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required for demosaicing')
class Processing(unittest.TestCase):
    def test_rgb_order_and_ten_bit_precision(self):
        output = render.demosaic(bayer(8, 8, 801, 402, 163), 8, 8)
        self.assertEqual(set(tuple(output[i:i + 3]) for i in range(0, len(output), 3)),
                         {(801 << 6, 402 << 6, 163 << 6)})

    def test_front_bggr_rgb_order(self):
        output = render.demosaic(bggr(8, 8, 801, 402, 163), 8, 8, 'BGGR')
        self.assertEqual(set(tuple(output[i:i + 3]) for i in range(0, len(output), 3)),
                         {(801 << 6, 402 << 6, 163 << 6)})

    def test_neutral_fixture(self):
        width, height = 32, 24
        samples = bayer(width, height, 264, 464, 164)
        # Balanced flat grey must stay grey without forced contrast.
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'preview.ppm'
            result = render.render(samples, width, height, destination)
            payload = destination.read_bytes().split(b'\n', 3)[3]
            self.assertEqual(result['gains'], [2, 1, 4])
            self.assertTrue(result['awb_valid'])
            self.assertEqual(set(tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)),
                             {(173, 173, 173)})
            self.assertFalse(result['exposure_normalized'])
            self.assertFalse(result['colour_calibrated'])

    def test_auto_balance_keeps_primary_patches_coloured(self):
        width, height = 32, 32
        # Equal-area linear red/green/blue/grey, with a simulated sensor WB
        # imbalance of 1/2 red and 1/4 blue and a 64-count black pedestal.
        colours = [(800, 80, 80), (80, 800, 80), (80, 80, 800), (400, 400, 400)]
        samples = array('H')
        for y in range(height):
            for x in range(width):
                r, g, b = colours[(y // 16) * 2 + x // 16]
                samples.append(64 + (g if x % 2 == y % 2 else r // 2 if y % 2 == 0 else b // 4))
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'preview.ppm'
            result = render.render(samples, width, height, destination)
            self.assertEqual(result['gains'], [2, 1, 4])
            payload = destination.read_bytes().split(b'\n', 3)[3]
            for x, y, channel in [(8, 8, 0), (24, 8, 1), (8, 24, 2)]:
                offset = (y * width + x) * 3
                colour = payload[offset:offset + 3]
                self.assertEqual(colour[channel], 255)
                self.assertTrue(all(v < 100 for c, v in enumerate(colour) if c != channel))
            offset = (24 * width + 24) * 3
            self.assertEqual(tuple(payload[offset:offset + 3]), (188, 188, 188))

    def test_manual_gains_preserve_known_channels(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'preview.ppm'
            result = render.render(bayer(8, 8, 800, 400, 160), 8, 8, destination,
                                   black=0, gains=(1, 1, 1))
            payload = destination.read_bytes().split(b'\n', 3)[3]
            self.assertEqual(tuple(payload[:3]), (255, 188, 124))
            self.assertEqual(result['white_balance'], 'manual')

    def test_black_stays_black(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'preview.ppm'
            result = render.render(bayer(8, 8, 64, 64, 64), 8, 8, destination)
            self.assertEqual(set(destination.read_bytes().split(b'\n', 3)[3]), {0})
            self.assertFalse(result['awb_valid'])
            self.assertFalse(result['exposure_normalized'])

    def test_capture_analysis_keeps_last_complete_frame_and_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            frame = pack(bayer(8, 8, 264, 464, 164), 8, 8, 3)
            data = frame + bytes(11)
            raw = out / 'frames.raw'
            raw.write_bytes(data)
            result = camera.analyse(raw, 8, 8, 13, len(frame), out)
            self.assertEqual(len(result), 1)
            self.assertIn('processed_preview', result[0])
            self.assertIn('preview', result[0])
            self.assertEqual(raw.read_bytes(), data)

    def test_render_failure_does_not_discard_capture_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            frame = pack(bayer(8, 8, 264, 464, 164), 8, 8)
            raw = out / 'frames.raw'
            raw.write_bytes(frame)
            with patch('camera_render.demosaic', side_effect=ValueError('conversion failed')):
                result = camera.analyse(raw, 8, 8, 10, len(frame), out)
            self.assertIn('conversion failed', result[0]['processed_preview_error'])
            self.assertIn('preview', result[0])
            self.assertEqual(raw.read_bytes(), frame)


if __name__ == '__main__':
    unittest.main()
