#!/usr/bin/env python3
"""Judge a mic capture against the room floor, by spectral band energy.

WHY: the internal mic gives an objective acoustic oracle with no listening
report and no USB mic, but only if the answer is read as spectral band energy
rather than raw RMS. The SPX room floor is broadband analog noise concentrated
below 300 Hz (77% of energy), and mechanical/handling noise lives there too, so
an RMS difference alone can mislead. A playback tone above ~8 kHz sits in a
band that is otherwise near-empty, which makes the test unambiguous.

MEASUREMENT, and why it is trustworthy: band power is computed with an
UNWINDOWED (rectangular) zero-padded DFT, because Parseval then gives

    band mean square = sum(w[k] * |X[k]|^2 for k in band) / (m * N)

where w is 2 for interior one-sided bins and 1 for DC/Nyquist. The sum over
all bins equals the time-domain mean square after DC removal. A full-scale
sine therefore measures -3.01 dBFS RMS. Rectangular-window leakage can move
energy across band boundaries; a high-band rise alone does not prove that a
speaker produced the requested tone.
Peak frequency and level come from a separate Hann-windowed spectrum, where the
familiar 2/(N*CG) scale is correct.

WHAT IT PRINTS: overall RMS/peak/DC, exact per-band RMS in real dBFS, the top
spectral peaks, and -- the decision -- the level of the HIGH band (>= 8 kHz),
the band to watch when judging a >8 kHz playback tone. A high-band rise of
more than ~20 dB over the same channel's own quiet reference is the positive
result to inspect for the requested tone. Acoustic sensitivity has not yet
been calibrated against a speaker known to work on this boot.

Usage:
  spx-mic-judge.py FILE.wav [FILE2.wav ...]     judge one or more captures
  spx-mic-judge.py FILE.wav --floor REF.wav     compare FILE against REF

Use spx-mic-capture.sh to take the captures. Constraints: capture on MM2
(plughw:0,1) with the ALSA mixer routing applied, re-applied after every
reboot; never play audio without the user having asked for that specific run.
"""
import argparse
import cmath
import math
import os
import struct
import wave

HIGHz = 8000.0                      # high band starts here; play tones above it
EDGES = [20, 60, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]
# Archived 2026-09-28 on Y boot b5f0a540, 2 s sweep, DEC0 gain 84.
ARCHIVED_RMS = {"DMIC0": -78.6, "DMIC1": -75.5, "ADC2": -63.3}


def load(path):
    with wave.open(path) as w:
        nch, sw, fr, nf = (w.getnchannels(), w.getsampwidth(),
                           w.getframerate(), w.getnframes())
        raw = w.readframes(nf)
    if sw != 2:
        raise SystemExit(f"{path}: expected 16-bit, got {sw * 8}-bit")
    v = struct.unpack("<%dh" % (len(raw) // 2), raw)
    if nch != 1:
        raise SystemExit(f"{path}: expected mono capture, got {nch} channels")
    if len(raw) != nf * nch * sw:
        raise SystemExit(f"{path}: truncated WAV samples")
    return list(v), fr, nch, nf


def fft(a):
    """Iterative in-place radix-2 Cooley-Tukey. len(a) must be a power of 2."""
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        wl = cmath.exp(complex(0.0, -2.0 * math.pi / length))
        for i in range(0, n, length):
            w = complex(1.0, 0.0)
            half = length // 2
            for k in range(half):
                u, t = a[i + k], a[i + k + half] * w
                a[i + k] = u + t
                a[i + k + half] = u - t
                w *= wl
        length <<= 1
    return a


def dbfs(amp):
    return 20 * math.log10(amp / 32768.0) if amp > 0 else float("-inf")


def db_delta(a, b):
    """a-b in dB, reported as an infinite rise rather than nan when b is -inf."""
    if a == float("-inf") and b == float("-inf"):
        return 0.0
    if a == float("-inf"):
        return float("-inf")
    return a - b


def analyse(path):
    x, fr, nch, nf = load(path)
    n = len(x)
    if not n:
        return None
    m = 1
    while m < n:
        m <<= 1
    mean = sum(x) / n

    # --- exact band power: unwindowed zero-padded DFT + exact Parseval -----
    buf = [complex(x[i] - mean, 0.0) for i in range(n)] + [0j] * (m - n)
    sp = fft(buf)
    p = [abs(sp[i]) ** 2 * (1 if i == 0 or 2 * i == m else 2)
         for i in range(m // 2 + 1)]

    def band_power(lo, hi):
        # Include only bins whose centres lie in [lo, hi). Include Nyquist
        # when hi reaches it, so a full-band sum retains the endpoint power.
        i0 = math.ceil(lo * m / fr)
        i1 = (len(p) if hi >= fr / 2 else math.ceil(hi * m / fr))
        return sum(p[i0:i1]) / (m * n)

    bands = []
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo >= fr / 2:
            break
        hi = min(hi, fr / 2)
        bands.append((lo, hi, dbfs(math.sqrt(band_power(lo, hi)))))
    hi_db = (dbfs(math.sqrt(band_power(HIGHz, fr / 2)))
             if HIGHz < fr / 2 else float("-inf"))
    ac_rms = dbfs(math.sqrt(sum(p) / (m * n)))

    # --- peak frequency/level: Hann window, familiar 2/(N*CG) amplitude ----
    window = ([1.0] * n if n < 3 else
              [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
               for i in range(n)])
    hb = [complex((x[i] - mean) * window[i], 0.0)
          for i in range(n)] + [0j] * (m - n)
    hs = fft(hb)
    window_sum = sum(window)
    spec = [(i * fr / m, abs(hs[i]) * (1 if 2 * i == m else 2) / window_sum)
            for i in range(1, m // 2 + 1)] or [(0.0, 0.0)]
    order = sorted(spec, key=lambda t: -t[1])
    dom, used = [], []
    for f, a in order:
        if any(abs(f - u) < max(40.0, fr / 400.0) for u in used):
            continue
        dom.append((round(f, 1), dbfs(a)))
        used.append(f)
        if len(dom) == 6:
            break
    pk_f, pk_a = max(spec, key=lambda t: t[1])
    return dict(path=path, fr=fr, nch=nch, secs=nf / fr, n=n, m=m,
                rms=dbfs(math.sqrt(sum(s * s for s in x) / n)),
                peak=max(abs(s) for s in x), dc=mean,
                nz=100.0 * sum(1 for s in x if s) / n,
                ac_rms=ac_rms, bands=bands, hi=hi_db, dom=dom,
                peakf=pk_f, peakdb=dbfs(pk_a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--floor", help="reference wav to compare against")
    args = ap.parse_args()

    fl = analyse(args.floor) if args.floor else None
    if fl:
        print(f"floor reference: {os.path.basename(fl['path'])}  "
              f"rms={fl['rms']:.1f} dBFS  high(>={HIGHz:.0f} Hz)={fl['hi']:.1f} dBFS\n")

    for f in args.files:
        a = analyse(f)
        if a is None:
            print(f"{f}: EMPTY / no samples\n")
            continue
        name = os.path.basename(f)
        print(f"{name}  {a['secs']:.1f}s  {a['fr']}Hz  {a['nch']}ch  "
              f"n={a['n']}  (fft {a['m']})")
        print(f"  rms={a['rms']:.1f} dBFS  peak={a['peak']}  dc={a['dc']:+.2f}  "
              f"nonzero={a['nz']:.1f}%")
        print(f"  loudest peak: {a['peakf']:.0f} Hz at {a['peakdb']:.1f} dBFS (amplitude)")
        for lo, hi, db in a["bands"]:
            print(f"    {lo:6.0f}-{hi:6.0f} Hz  {db:7.1f} dBFS"
                  f"{'   <-- high band' if lo >= HIGHz else ''}")
        print("  peaks: " + ", ".join(f"{f:.0f}Hz {d:.1f}" for f, d in a["dom"]))
        print(f"  HIGH(>={HIGHz:.0f} Hz) = {a['hi']:.1f} dBFS")

        if fl:
            if a['fr'] != fl['fr']:
                raise SystemExit("Capture and floor must have the same sample rate")
            dh = db_delta(a["hi"], fl["hi"])
            dr = db_delta(a["rms"], fl["rms"])
            ds = f"{dh:+.1f}"
            print(f"  vs floor: high {ds} dB, total rms {dr:+.1f} dB")
            print("  ==> HIGH-BAND RISE >20 dB; verify the requested tone" if dh > 20
                  else "  ==> no high-band rise >20 dB; acoustic output unproven")
        else:
            key = next((k for k in ARCHIVED_RMS if k in name), None)
            if key:
                print(f"  (archived 2026-09-28 rms for {key} was "
                      f"{ARCHIVED_RMS[key]} dBFS -> "
                      f"{a['rms'] - ARCHIVED_RMS[key]:+.1f} dB vs then)")
        print()


if __name__ == "__main__":
    main()
