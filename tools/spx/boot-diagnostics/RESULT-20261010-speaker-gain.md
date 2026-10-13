boxes closed: 3 of 47; newly closed: none.

# Stereo amplifier gain: +1.5 dB clear; +3 dB requested

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Request:** full digital scale still sounds below expected loudness. User
agrees to a small equal amplifier-gain increase and listening comparison.

**Change:** `play-desktop --pa-gain-step 1` applies +1.5 dB to each native
WSA mixer after the verified initialization, while PCM still carries silence.
Startup and ongoing stereo checks require the selected exact gain shadow,
and keep all existing boost/protection, port, routing and compander checks.
Other action modes retain minimum PA gain. Explicit ordinary steps 0/1/2
mean 0/1.5/3 dB; default stays 0. User confirmed step1 remains clear with no audible distortion, then authorized
step2 (+3 dB) on both speakers.
The PCM geometry and low-latency userspace queues are unchanged.

**Verification:** 116 offline audio tests pass. Before restart, both amps
parked and FIFO empty. New PCM12699 runs; both native mixer values read1
(+1.5 dB), and runtime readiness records unity digital gain and PA gain1.5 dB.
No reboot or kernel/module change; no generated sound
or microphone capture. Factory maximum, acoustic distortion/balance and
latency remain unestablished. At +3 dB, both mixers read2 and runtime status records PA gain3.0 dB;
PCM13643 is running with unity digital gain. User reports an odd distortion at +3 dB, then clarifies it felt like a
playback glitch on both sides. This does not establish an amplifier limit.
Returned to the last subjectively clear +1.5 dB pending comparison.
Runtime service: `spx-desktop-playback`; status in
`/var/lib/spx-desktop-playback/serve-ready.json`. No reboot startup yet.

**Glitch evidence:** stopped +3 dB stream submitted/completed1615/1615 DSP
buffers with zero fallback. No ALSA underrun or feeder/monitor error logged;
maximum digital peak9652/32768 excludes clipping in this feeder. Maximum
monitor delivery gap204 ms includes startup and is not time-correlated with
the reported glitch. Source/network interruptions, PipeWire timing and analog
causes remain unresolved. No test sound or microphone capture added.
