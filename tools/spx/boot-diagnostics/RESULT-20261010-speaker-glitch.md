boxes closed: 3 of 47; newly closed: none.

# +3 dB is clear with a same-stream gain change

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Problem:** user reports repeated bilateral playback-like glitches at +3 dB
on the same clip and slider setting, clear after returning to +1.5 dB.
Each earlier gain adjustment also restarted the full PipeWire/PCM path.
Old affected PCM completed1615/1615 buffers, no logged ALSA underrun or
feeder error; maximum digital peak9652/32768. The 204 ms maximum monitor
gap includes startup and is not correlated with the glitch. Current gain
writes change only PA gain bits; earlier6.18 records also used +3 dB.

**Change:** added bounded, serialized owner-controlled gain changes via
`/var/lib/spx-desktop-playback/pa-gain-step` (root-only file, values0/1/2).
The existing exact stereo checks verify the new gain and unchanged protection.
116 existing offline checks plus a new same-PCM gain-change check pass.
Started once at +1.5 dB, then changed live to +3 dB with PCM19468, its trigger,
PipeWire graph, buffers and digital gain unchanged. Used the user's prior
explicit lock override; camera-front's lock and hardware were untouched.
No generated tones, microphone capture, reboot or kernel/module change.

**Observed:** user replayed the same comparison and said "Now it's perfect."
The native PCM and trigger remained unchanged; both gains are +3 dB.

**Meaning:** +3 dB is usable in this session, contradicting the claim of a
repeatable hardware gain ceiling at +1.5 dB. The earlier session/restart is
a confound; the precise glitch mechanism remains unproven. Live gain control
avoids repeating that restart for volume adjustments. Leave +3 dB active;
no extra successful audio tests. Factory maximum, latency and automatic
startup remain open; no full A01/A03 acceptance claimed.
Evidence: gain-comparison-before/after.json in /var/lib/spx-desktop-playback/.
