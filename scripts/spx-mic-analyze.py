#!/usr/bin/env python3
"""Score a guarded-run mic capture (<run>/mic-DMIC1.wav, 48 kHz mono S16).

The harness starts arecord ~0.3 s before aplay; the aplay vector is
0-3 s digital zero, 3-8 s 440 Hz (right), 8-11 s zero (capture ends at 9 s).
Prints: room floor (pre-open), STATIC (zero-prefix rms with the PA on),
tone-window rms, 440 Hz fundamental and harmonics, and a static index in dB
relative to the room floor.  stdlib only.
Usage: spx-mic-analyze.py <wav> [capture_lead_s=0.3]
"""
import sys, wave, struct, math
path = sys.argv[1]; lead = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
w = wave.open(path); fs = w.getframerate()
v = struct.unpack('<%dh' % w.getnframes(), w.readframes(w.getnframes()))
def rms(x): return math.sqrt(sum(a*a for a in x)/len(x)) if x else 0.0
def g(f, x):
    k = 2*math.cos(2*math.pi*f/fs); s1 = s2 = 0.0
    for s in x:
        s0 = s + k*s1 - s2; s2 = s1; s1 = s0
    return math.sqrt(max(s1*s1+s2*s2-k*s1*s2, 0))/len(x)*math.sqrt(2) if x else 0.0
def seg(a, b): return v[int((a+lead)*fs):int((b+lead)*fs)]
room = rms(v[:int(max(lead-0.05, 0.1)*fs)]) if lead >= 0.15 else float("nan")
zero = seg(0.8, 2.8); tone = seg(3.5, 7.8)
sz, st = rms(zero), rms(tone)
f0 = g(440, tone); h = [g(f, tone) for f in (880, 1320, 1760)]
nb = max(g(f, tone) for f in (330, 400, 480, 560))
db = lambda a, b: (20*math.log10(max(a, 1e-9)/max(b, 1e-9)) if b == b else float("nan"))
print(f"SPX MIC-ANALYZE {path}")
print(f"  room floor (pre-open)      rms={room:7.1f}")
print(f"  STATIC (zero prefix, PA on) rms={sz:7.1f}   static index = {db(sz, room):+.1f} dB vs room")
print(f"  tone window                rms={st:7.1f}   440Hz={f0:.2f} harmonics(880/1320/1760)={h[0]:.2f}/{h[1]:.2f}/{h[2]:.2f} neighbours={nb:.2f}")
print(f"  tone-vs-static             {db(st, sz):+.1f} dB;  440Hz/neighbours ratio={f0/max(nb,1e-9):.1f}  -> {'TONE DETECTED' if f0 > 5*nb and f0 > 1 else 'no tone'}")
