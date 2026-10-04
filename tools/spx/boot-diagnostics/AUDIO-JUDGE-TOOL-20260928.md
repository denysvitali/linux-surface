# Spectral judge for the restored mic oracle (2026-09-28)

> Numerical conclusions superseded by AUDIO-CONTINUATION-20260930.md. Interior
> one-sided bins require weight 2; a full-scale sine is -3.01 dBFS RMS, and
> DMIC0's combined high-band floor is -87.6 dBFS. Acoustic sensitivity and
> the claimed digital-to-acoustic headroom have not been established.

Adds `tools/spx/boot-diagnostics/spx-mic-judge.py` so a capture is judged by
**band energy**, not by raw RMS, and the measurement is defensible. It closes
the method gap in `AUDIO-ORACLE-RESTORED-20260928.md`, which established that
the internal mic works but did not give a rule for reading it.

## Why band energy and not RMS

The SPX room floor is broadband analog noise concentrated below 300 Hz, and
mechanical/handling noise lives in the same place. A playback tone above ~8 kHz
sits in a band that is otherwise near-empty, so the presence of a tone is
unambiguous there. RMS alone can be raised by a bump on the desk; a tone in
the high band cannot be faked by that.

## The measurement, and its one rejected attempt

Band power is computed with an **unwindowed zero-padded DFT** and **exact
Parseval**: `band mean square = sum(|X[k]|^2) / (m*N)`. This needs no
calibration constant and has no bias, so it is equally correct for a pure tone
and for noise — which is precisely the comparison being made.

A Hann window was tried first and **rejected after validation**: its ENBW makes
a full-scale sine's band read about **+3 dBFS above full scale**, so tone and
noise bands are not comparable. A Hann spectrum is still used for *peak
frequency and amplitude*, where the familiar `2/(N*CG)` scale is correct, but
the band levels come from the Parseval path.

Validated against synthetic signals with known answers (48 kHz, 2 s):

| input | predicted | measured |
|-------|-----------|----------|
| digital silence | ~ -inf | -330 dBFS, decision "floor" |
| 10 kHz full-scale sine | high band -6 dBFS, peak bin -0.3 | -6.0 dBFS, 10000 Hz -0.3 |
| 8 kHz full-scale sine | high band ~ -6 dBFS | -6.2 dBFS, 8000 Hz -0.3 |
| 12 kHz at -20 dB + 1 kHz at -40 | high band -26, peaks -20/-40 | -26.0 dBFS, 12000 -20.0 / 1000 -40.3 |

The exactness is why the "expected -6, got -6.0" agreement is meaningful and
the earlier "+3.1 dBFS, impossible" reading was the tell that the instrument
was wrong.

## The measured floor (2026-09-28, Y boot b5f0a540, 2 s, DEC0 gain 84)

DMIC0, the reference channel: total **-78.6 dBFS**, but by band it is
concentrated low — 125-250 Hz -88.3, 500-1000 -96.8, **high (>=8 kHz) -93.2
dBFS**, loudest peak 177 Hz at -87.0. The 14.6 dB gap between the total and the
high band is exactly the low-frequency noise RMS was conflating with signal.

Cross-checks: DMIC1 high -88.1 (a touch hotter), ADC2 (= `Headset Mic`) high
-81.9 and a 3 kHz peak at -74.0 — the loudest input, but not an internal mic.

## Headroom is better than estimated

A 4000/32767 playback tone is -18.3 dBFS **digital**, but what the mic must
resolve is the *acoustic* level at the mic, so the honest comparison is the
high band, not the digital number. The 8 kHz+ band sits at **-93.2 dBFS**, so
the usable budget is **~75 dB**, not 61 dB. The oracle is comfortably above
threshold; the 20 dB decision cutoff is not marginal.

## Use

    spx-mic-capture.sh DMIC0 4        # capture (MM2, routing applied)
    spx-mic-judge.py  cap-DMIC0.wav --floor cap-quiet.wav
    spx-mic-judge.py  cap-play.wav  --floor cap-quiet.wav   # look for high-band rise

A >20 dB high-band rise over the same channel's own quiet capture is the
positive result. Capture on MM2 with the routing applied (see
`spx-mic-capture.sh`); re-apply routing after every reboot. Use a tone above
~8 kHz and a speaker-side DMIC, not ADC2. **Never play audio without the user
having asked for that specific run.**
