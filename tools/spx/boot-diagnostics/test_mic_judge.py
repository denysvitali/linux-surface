"""Numerical checks for the acoustic measurement, without hardware or playback."""

import importlib.util
import math
from pathlib import Path
import random
import struct
import tempfile
import unittest
import wave

spec = importlib.util.spec_from_file_location(
    'mic_judge', Path(__file__).with_name('spx-mic-judge.py'))
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


class MeasurementTests(unittest.TestCase):
    def analyse(self, samples, rate=48000, channels=1):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'capture.wav')
            with wave.open(path, 'wb') as stream:
                stream.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
                stream.writeframes(struct.pack('<%dh' % len(samples), *samples))
            return judge.analyse(path)

    def tone(self, frequency, peak=16000, count=4096):
        return [round(peak * math.sin(2 * math.pi * frequency * i / 48000))
                for i in range(count)]

    def test_full_scale_sine_is_minus_three_dbfs_rms(self):
        result = self.analyse(self.tone(10500, 32767))
        self.assertAlmostEqual(result['hi'], -3.0106, places=3)
        self.assertAlmostEqual(result['peakdb'], 0, places=2)

    def test_parseval_for_padded_noise_with_dc(self):
        rng = random.Random(42)
        samples = [rng.randrange(-500, 501) + 200 for _ in range(3001)]
        mean = sum(samples) / len(samples)
        expected = judge.dbfs(math.sqrt(sum((x - mean) ** 2 for x in samples)
                                       / len(samples)))
        self.assertAlmostEqual(self.analyse(samples)['ac_rms'], expected, places=8)

    def test_both_high_bands_are_summed(self):
        samples = [a + b for a, b in zip(self.tone(10500, 8000),
                                         self.tone(18000, 8000))]
        result = self.analyse(samples)
        self.assertAlmostEqual(result['hi'], judge.dbfs(8000), places=3)
        self.assertAlmostEqual(result['hi'], result['ac_rms'], places=6)

    def test_nyquist_not_doubled_or_dropped(self):
        result = self.analyse([16000, -16000] * 2048)
        self.assertAlmostEqual(result['hi'], judge.dbfs(16000), places=8)
        # A doubled adjacent Hann bin can be slightly taller than Nyquist.
        self.assertAlmostEqual(result['peakdb'], judge.dbfs(16000), places=2)

    def test_boundary_is_in_one_band(self):
        result = self.analyse(self.tone(8000, count=3072))
        # Zero padding leaks some energy below the exact 8 kHz boundary.
        self.assertLessEqual(result['hi'], result['ac_rms'] + 1e-8)
        self.assertGreater(result['hi'], result['ac_rms'] - 2)

    def test_silence_and_short_wav(self):
        for samples in ([0] * 1024, [0], [0, 0]):
            result = self.analyse(samples)
            self.assertEqual(result['hi'], float('-inf'))
            self.assertEqual(judge.db_delta(result['hi'], result['hi']), 0)
        self.assertIsNone(self.analyse([]))
        self.assertEqual(judge.db_delta(-40, float('-inf')), float('inf'))

    def test_stereo_cannot_be_silently_cancelled(self):
        with self.assertRaisesRegex(SystemExit, 'expected mono'):
            self.analyse([100, -100] * 1024, channels=2)


if __name__ == '__main__':
    unittest.main()
