#!/usr/bin/env python3
"""The chart analyser must recover known defects from simulated, distorted captures."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location('camera_chart', Path(__file__).with_name('camera_chart.py'))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

CANVAS = (1024, 768)
QUAD = [(70, 60), (960, 85), (80, 700), (935, 725)]   # TL TR BL BR of the chart in the frame (tilted)


def camera(gain=(1, 1, 1), exponent=1.0, vignette=0.0, noise=0.0, quad=QUAD, seed=1):
    """Chart seen through a camera with a linear-light gain, tone exponent, vignette and noise."""
    chart = cc.render(ppm=3)
    cw, ch = chart.size
    dst = [quad[0], quad[1], quad[3], quad[2]]                       # TL TR BR BL
    src = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
    hm = cc.homography(dst, src)                                      # frame pixel -> chart pixel
    coeffs = tuple(hm.flatten()[:8])
    warped = chart.transform(CANVAS, Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(90, 90, 90))
    a = np.asarray(warped, float)
    lin = cc.to_linear(a) * np.array(gain)
    lin = np.clip(lin, 0, 1) ** exponent
    if vignette:
        y, x = np.mgrid[0:CANVAS[1], 0:CANVAS[0]]
        r = np.hypot((x - CANVAS[0] / 2) / (CANVAS[0] / 2), (y - CANVAS[1] / 2) / (CANVAS[1] / 2)) / np.sqrt(2)
        lin = lin * (1 - vignette * r ** 2)[..., None]
    out = 255 * np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.clip(lin, 0, None) ** (1 / 2.4) - 0.055)
    out = out + np.random.default_rng(seed).normal(0, noise, out.shape)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


class ChartTests(unittest.TestCase):
    def analyse(self, img):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'frame.png'
            img.save(p)
            return cc.analyze(p, Path(d) / 'out')

    def test_markers_found_on_a_tilted_frame(self):
        r = self.analyse(camera())
        # ring centres sit inset from the chart corners; check their ordering
        tl, tr, bl, br = r['markers']
        self.assertLess(tl[0], tr[0]); self.assertLess(bl[0], br[0])
        self.assertLess(tl[1], bl[1]); self.assertLess(tr[1], br[1])

    def test_a_perfect_camera_scores_well(self):
        r = self.analyse(camera())
        self.assertEqual(r['neutrality']['verdict'], 'neutral')
        self.assertLess(r['colour']['deltaE2000_mean'], 3.0)
        self.assertAlmostEqual(r['tone']['luminance_exponent_vs_nominal'], 1.0, delta=0.08)
        self.assertTrue(r['tone']['monotonic'])

    def test_a_colour_cast_is_reported(self):
        r = self.analyse(camera(gain=(1.0, 1.0, 0.7)))
        self.assertEqual(r['neutrality']['verdict'], 'colour cast')
        self.assertLess(r['neutrality']['B_over_G'], 0.9)

    def test_a_wrong_tone_curve_shows_in_the_exponent(self):
        flat = self.analyse(camera(exponent=0.8))['tone']['luminance_exponent_vs_nominal']
        steep = self.analyse(camera(exponent=1.25))['tone']['luminance_exponent_vs_nominal']
        self.assertLess(flat, 0.9)
        self.assertGreater(steep, 1.1)

    def test_noise_is_measured_in_codes(self):
        quiet = self.analyse(camera(noise=0.5))['noise']['sigma_codes_grey_field'][1]
        noisy = self.analyse(camera(noise=6.0))['noise']['sigma_codes_grey_field'][1]
        self.assertLess(quiet, 2.0)
        self.assertAlmostEqual(noisy, 6.0, delta=1.5)

    def test_a_clipped_white_patch_is_flagged(self):
        r = self.analyse(camera(gain=(2.5, 2.5, 2.5)))
        self.assertGreater(r['clipping']['white_patch'], 0.5)

    def test_missing_chart_is_an_error_not_a_guess(self):
        blank = Image.fromarray(np.full((480, 640, 3), 120, np.uint8))
        with tempfile.TemporaryDirectory() as d:
            blank.save(Path(d) / 'b.png')
            with self.assertRaisesRegex(RuntimeError, 'ring markers'):
                cc.analyze(Path(d) / 'b.png')

    def test_flat_field_vignette_and_black_level(self):
        y, x = np.mgrid[0:480, 0:640]
        r = np.hypot((x - 320) / 320, (y - 240) / 240) / np.sqrt(2)
        lum = 200 * (1 - 0.3 * r ** 2)
        img = Image.fromarray(np.stack([lum * 1.0, lum * 1.0, lum * 0.9], -1).astype(np.uint8))
        with tempfile.TemporaryDirectory() as d:
            img.save(Path(d) / 'f.png')
            f = cc.flat_field(Path(d) / 'f.png')
            self.assertGreater(f['worst_vignette_pct'], 15)
            Image.fromarray(np.full((48, 64, 3), (2, 3, 2), np.uint8)).save(Path(d) / 'k.png')
            k = cc.black_level(Path(d) / 'k.png')
            self.assertEqual([round(v) for v in k['mean_rgb']], [2, 3, 2])


if __name__ == '__main__':
    unittest.main()
