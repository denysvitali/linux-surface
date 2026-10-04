"""Bounded, uncalibrated acoustic checks for the SPX 440/660 Hz speaker test.

Input is mono signed 16-bit PCM. A quiet reference must use the same microphone,
gain and sample rate as the phase. The search tolerates leading/trailing silence
and capture latency; it does not infer a microphone's physical speaker position.
"""

import math
import statistics


WINDOW_SECONDS = 0.4
STEP_SECONDS = 0.1
MIN_TONE_RMS = 1.0
MIN_TONE_RISE_DB = 10.0
NOISE_FLOOR_RMS = 20.0
NOISE_RISE_FACTOR = 2.0
CLIP_LEVEL = 32760
LIMITATIONS = [
    'PCM levels are not calibrated sound pressure or a listening-quality rating.',
    'Tone identity does not establish physical speaker placement or stereo balance.',
    'Uses nominal 440/660 Hz; clock or pitch errors can make output inconclusive.',
    'Noise is checked in the sustained window and by the phase median; brief '
    'noise bursts outside that window need separate monitoring.',
]


def quick_metrics(samples):
    """Cheap PCM counts for capture monitoring; clipped is a sample count."""
    n = len(samples)
    if not n:
        return {'rms': 0.0, 'ac_rms': 0.0, 'peak': 0, 'dc': 0.0,
                'clipped': 0, 'clipped_fraction': 0.0, 'samples': 0}
    mean = sum(samples) / n
    power = sum(x * x for x in samples) / n
    clipped = sum(abs(x) >= CLIP_LEVEL for x in samples)
    return {'rms': math.sqrt(power),
            'ac_rms': math.sqrt(max(0.0, power - mean * mean)),
            'peak': max(abs(x) for x in samples), 'dc': mean,
            'clipped': clipped, 'clipped_fraction': clipped / n, 'samples': n}


def _tone_rms(samples, frequency, rate):
    # Goertzel magnitude expressed as the RMS of a coherent sinusoid. At the
    # default rate, both test tones have integral cycles in 0.1/0.4 s windows.
    coefficient = 2.0 * math.cos(2.0 * math.pi * frequency / rate)
    first = second = 0.0
    for sample in samples:
        current = sample + coefficient * first - second
        second, first = first, current
    power = first * first + second * second - coefficient * first * second
    return math.sqrt(max(0.0, 2.0 * power)) / len(samples)


def _rise_db(value, reference):
    # A small measurement floor keeps the result finite/strict-JSON friendly.
    return 20.0 * math.log10(max(value, 1e-9) / max(reference, 0.1))


def _measure(samples, expected, rate, neighbors=False):
    metrics = quick_metrics(samples)
    centered = [x - metrics['dc'] for x in samples]
    tones = {f: _tone_rms(centered, f, rate) for f in expected}
    residual = math.sqrt(max(0.0, metrics['ac_rms'] ** 2 -
                             sum(value * value for value in tones.values())))
    nearby = {}
    if neighbors:
        for frequency in expected:
            nearby[frequency] = max(_tone_rms(centered, frequency + delta, rate)
                                    for delta in (-50, -25, 25, 50))
    return tones, residual, nearby


def score_phase(samples, baseline, expected, rate=48000):
    """Return tone/noise evidence for one finite left, right or both phase.

    A passing 0.4 s window must contain all expected tones concurrently, each
    >=1 count RMS and >=10 dB above both quiet-reference and neighboring bins.
    All four 0.1 s subwindows must sustain each tone, rejecting brief impulses
    and sequential single tones masquerading as stereo. Residual noise may be
    at most twice the quiet-reference residual, with a 20-count RMS allowance
    for normal room noise. Any near-rail sample anywhere in the phase fails.

    These are conservative engineering thresholds, not calibrated acceptance
    limits for loudness, distortion, speech quality or physical channel mapping.
    No amplitude escalation or hardware action is performed by this module.
    """
    result = {'passed': False, 'reason': '', 'targets': {},
              'selected_window_seconds': None, 'residual_rms': None,
              'baseline_residual_rms': None, 'residual_limit_rms': None,
              'phase_median_residual_rms': None, 'metrics': {},
              'baseline_metrics': {}, 'limitations': list(LIMITATIONS)}
    if (not isinstance(rate, int) or rate < 2000 or not expected or
            len(expected) != len(set(expected)) or
            any(f not in (440, 660) for f in expected)):
        result['reason'] = 'invalid sample rate or expected frequencies'
        return result
    if any(not isinstance(x, int) or not -32768 <= x <= 32767
           for series in (samples, baseline) for x in series):
        result['reason'] = 'expected signed 16-bit integer PCM samples'
        return result
    result['metrics'] = quick_metrics(samples)
    result['baseline_metrics'] = quick_metrics(baseline)
    if result['metrics']['clipped'] or result['baseline_metrics']['clipped']:
        result['reason'] = 'clipping in phase or quiet reference'
        return result
    step = round(rate * STEP_SECONDS)
    window = step * 4
    if len(samples) < window or len(baseline) < window:
        result['reason'] = 'phase and quiet reference need at least 0.4 seconds'
        return result

    quiet = [_measure(baseline[start:start + window], expected, rate)
             for start in range(0, len(baseline) - window + 1, step)]
    quiet_tones = {f: max(item[0][f] for item in quiet) for f in expected}
    quiet_residual = statistics.median(item[1] for item in quiet)
    noise_limit = max(NOISE_FLOOR_RMS, quiet_residual * NOISE_RISE_FACTOR)
    result['baseline_residual_rms'] = quiet_residual
    result['residual_limit_rms'] = noise_limit

    candidates, residuals = [], []
    for start in range(0, len(samples) - window + 1, step):
        segment = samples[start:start + window]
        tones, residual, nearby = _measure(segment, expected, rate, neighbors=True)
        targets, failures, margins = {}, [], []
        for frequency in expected:
            level = tones[frequency]
            baseline_db = _rise_db(level, quiet_tones[frequency])
            neighbor_db = _rise_db(level, nearby[frequency])
            targets[str(frequency)] = {
                'frequency_hz': frequency, 'rms': level,
                'baseline_rms': quiet_tones[frequency],
                'neighbor_rms': nearby[frequency],
                'baseline_rise_db': baseline_db, 'neighbor_rise_db': neighbor_db,
                'sustained': False,
            }
            margins.append(min(_rise_db(level, MIN_TONE_RMS),
                               baseline_db - MIN_TONE_RISE_DB,
                               neighbor_db - MIN_TONE_RISE_DB))
            if level < MIN_TONE_RMS:
                failures.append(f'{frequency} Hz below absolute tone floor')
            elif min(baseline_db, neighbor_db) < MIN_TONE_RISE_DB:
                failures.append(f'{frequency} Hz lacks 10 dB spectral contrast')
        if not failures:
            # Hold every target present across the same four subwindows. A
            # short pulse cannot earn a pass by raising one FFT-bin magnitude.
            blocks = [_measure(segment[i:i + step], expected, rate)[0]
                      for i in range(0, window, step)]
            for frequency in expected:
                minimum = min(block[frequency] for block in blocks)
                sustained = minimum >= max(MIN_TONE_RMS, tones[frequency] / 2)
                targets[str(frequency)]['minimum_subwindow_rms'] = minimum
                targets[str(frequency)]['sustained'] = sustained
                if not sustained:
                    failures.append(f'{frequency} Hz not sustained for 0.4 seconds')
        if residual > noise_limit:
            failures.append('excess residual noise outside expected tones')
        residuals.append(residual)
        candidates.append({'passed': not failures, 'reason': '; '.join(failures),
                           'targets': targets, 'residual_rms': residual,
                           'selected_window_seconds': [start / rate,
                                                       (start + window) / rate],
                           'margin': min(margins)})

    median_residual = statistics.median(residuals)
    best = max(candidates, key=lambda candidate: (candidate['passed'], candidate['margin']))
    result.update({key: value for key, value in best.items() if key != 'margin'})
    result['phase_median_residual_rms'] = median_residual
    if median_residual > noise_limit:
        result.update(passed=False, reason='excess residual noise across phase')
    elif result['passed']:
        result['reason'] = 'sustained expected tones detected above quiet reference'
    return result
