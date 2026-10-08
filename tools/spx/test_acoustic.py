"""Synthetic signal checks; no audio devices or recordings are used."""

import json
import math
import random
import struct

import audio
import unittest

from acoustic import quick_metrics, score_phase


RATE = 48000


def silence(seconds=1.2):
    return [0] * round(RATE * seconds)


def tone(frequencies, peak=100, seconds=1.2):
    return [round(sum(peak * math.sin(2 * math.pi * f * i / RATE)
                      for f in frequencies)) for i in range(round(RATE * seconds))]


def noise(rms=10, seconds=1.2, seed=1):
    rng = random.Random(seed)
    return [round(rng.gauss(0, rms)) for _ in range(round(RATE * seconds))]


def mix(*signals):
    return [sum(values) for values in zip(*signals)]


class AcousticTests(unittest.TestCase):
    def test_quiet_and_dc_do_not_pass(self):
        for samples in (silence(), [12] * len(silence())):
            self.assertFalse(score_phase(samples, silence(), [440])['passed'])

    def test_low_tone_above_normal_room_noise_passes(self):
        result = score_phase(mix(tone([440], peak=4), noise(seed=2)), noise(), [440])
        self.assertTrue(result['passed'], result)
        self.assertAlmostEqual(result['targets']['440']['rms'], 4 / math.sqrt(2), delta=0.4)
        json.dumps(result, allow_nan=False)

    def test_latency_and_zero_buffers_do_not_hide_tone(self):
        samples = silence(0.45) + tone([440]) + silence(0.8)
        result = score_phase(samples, silence(), [440])
        self.assertTrue(result['passed'], result)
        self.assertGreaterEqual(result['selected_window_seconds'][0], 0.4)

    def test_both_tones_must_be_concurrent(self):
        self.assertTrue(score_phase(tone([440, 660]), silence(), [440, 660])['passed'])
        sequential = tone([440], seconds=0.6) + tone([660], seconds=0.6)
        self.assertFalse(score_phase(sequential, silence(), [440, 660])['passed'])

    def test_missing_channel_fails(self):
        for frequency in (440, 660):
            result = score_phase(tone([frequency]), silence(), [440, 660])
            self.assertFalse(result['passed'])

    def test_wrong_tone_and_broadband_noise_fail(self):
        self.assertFalse(score_phase(tone([880]), silence(), [440])['passed'])
        self.assertFalse(score_phase(noise(200), noise(), [440])['passed'])

    def test_tone_with_excess_static_fails(self):
        result = score_phase(mix(tone([440]), noise(100, seed=2)), noise(), [440])
        self.assertFalse(result['passed'])
        self.assertIn('residual noise', result['reason'])

    def test_baseline_tone_cannot_pass_as_new_output(self):
        reference = tone([440], peak=20)
        self.assertFalse(score_phase(tone([440], peak=40), reference, [440])['passed'])

    def test_brief_impulse_and_tone_burst_fail(self):
        impulse = silence()
        impulse[len(impulse) // 2] = 30000
        self.assertFalse(score_phase(impulse, silence(), [440])['passed'])
        burst = silence(0.5) + tone([440], peak=20, seconds=0.1) + silence(0.6)
        self.assertFalse(score_phase(burst, silence(), [440])['passed'])

    def test_clipping_anywhere_fails_even_with_clean_tone(self):
        samples = tone([440]) + [32767]
        result = score_phase(samples, silence(), [440])
        self.assertFalse(result['passed'])
        self.assertEqual(result['metrics']['clipped'], 1)
        self.assertIn('clipping', result['reason'])

    def test_below_absolute_floor_fails(self):
        self.assertFalse(score_phase(tone([440], peak=1), silence(), [440])['passed'])

    def test_invalid_and_short_inputs_fail_closed(self):
        for samples, baseline, expected in (([], [], [440]),
                                             (silence(0.1), silence(), [440]),
                                             (silence(), silence(), []),
                                             (silence(), silence(), [880]),
                                             (silence(), silence(), [440, 440]),
                                             ([40000], silence(), [440])):
            result = score_phase(samples, baseline, expected)
            self.assertFalse(result['passed'])
            json.dumps(result, allow_nan=False)

    def test_monitor_metrics(self):
        result = quick_metrics([0, 3, -4])
        self.assertAlmostEqual(result['rms'], math.sqrt(25 / 3))
        self.assertEqual(result['peak'], 4)
        self.assertEqual(result['clipped'], 0)
        self.assertEqual(quick_metrics([])['samples'], 0)



class AlternatePairTests(unittest.TestCase):
    pair = [880, 1320]

    def test_actual_quiet_stereo_waveform_downmixed_to_mono_scores_end_to_end(self):
        waveform = audio.tone({0, 1}, frequencies=(880, 1320))
        samples = [(left + right) // 2 for left, right in struct.iter_unpack('<hh', waveform)]
        self.assertLessEqual(max(abs(sample) for sample in samples), 1433)
        result = score_phase(samples, silence(), self.pair)
        self.assertTrue(result['passed'], result)
        self.assertEqual(set(result['targets']), {'880', '1320'})
        for target in result['targets'].values():
            self.assertTrue(target['sustained'])
            self.assertGreaterEqual(target['baseline_rise_db'], 10)
            self.assertGreaterEqual(target['neighbor_rise_db'], 10)
        json.dumps(result, allow_nan=False)

    def test_alternate_admission_remains_exact_pair_only(self):
        for expected in ([880], [1320], [880, 660], [440, 1320], [440, 660, 880, 1320],
                         [880, 880], [880, 1760], [1320, 880], [880.0, 1320]):
            with self.subTest(expected=expected):
                result = score_phase(tone(self.pair), silence(), expected)
                self.assertFalse(result['passed'])
                self.assertEqual(result['reason'], 'invalid sample rate or expected frequencies')
        # Legacy single, paired and reversed contracts stay available.
        for expected in ([440], [660], [440, 660], [660, 440]):
            with self.subTest(expected=expected):
                self.assertTrue(score_phase(tone(expected), silence(), expected)['passed'])

    def test_missing_and_sequential_alternate_targets_fail(self):
        sequential = tone([880], seconds=.6) + tone([1320], seconds=.6)
        for samples in (tone([880]), tone([1320]), sequential):
            result = score_phase(samples, silence(), self.pair)
            self.assertFalse(result['passed'])
            self.assertNotIn('invalid sample rate', result['reason'])

    def test_ambient_pair_and_wrong_targets_do_not_pass(self):
        result = score_phase(tone(self.pair, peak=40), tone(self.pair, peak=20), self.pair)
        self.assertFalse(result['passed'])
        self.assertIn('spectral contrast', result['reason'])
        for expected, actual in ((self.pair, [440, 660]), ([440, 660], self.pair)):
            result = score_phase(tone(actual), silence(), expected)
            self.assertFalse(result['passed'])

    def test_clipping_and_excess_noise_reject_alternate_pair(self):
        for samples, baseline in ((tone(self.pair) + [32767], silence()),
                                  (tone(self.pair), silence() + [-32768])):
            result = score_phase(samples, baseline, self.pair)
            self.assertFalse(result['passed']); self.assertIn('clipping', result['reason'])
        result = score_phase(mix(tone(self.pair), noise(100, seed=2)), noise(), self.pair)
        self.assertFalse(result['passed']); self.assertIn('residual noise', result['reason'])


if __name__ == '__main__':
    unittest.main()
