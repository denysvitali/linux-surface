boxes closed: 3 of 47; newly closed: none.

# Desktop speakers connected; latency and useful volume remain open

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** added `audio.py play-desktop`, reusing native enumeration,
stereo mixer routing, late initialization and cleanup. It connects the public
PipeWire monitor to the native speaker PCM without tones or microphone capture.
The existing acoustic test modes remain unchanged. Runtime service
`spx-desktop-playback` owns playback; no automatic startup after reboot yet.
The other coordinator released the device before hardware activation; this
session acquired its own lock. No reboot, kernel reload or display change.

**Observed:** user confirms both speakers audible, but quiet at maximum slider
and roughly 500 ms or more delayed. The intentional night limit is 1433/32768
(4.37%) digital amplitude with minimum PA gain. Initial queues included a
12000-frame/250 ms ALSA backlog plus 35520 bytes/185 ms in the feeder pipe.

Reduced ordinary desktop pipes from 65536 to 4096 bytes and the Python monitor
queue from 200 to 20 ms, retaining the DSP's existing mapped buffer geometry.
Stopped cleanly at the hardware level (amps parked, FIFO zero); desktop-unit
stop reported an error and was completed explicitly before restart. Reopened
successfully: both codecs initialized; native PCM running, same 2400/12000
geometry. Three subsequent samples show 7200 frames/150 ms ALSA backlog and
an empty feeder pipe. This is queue occupancy, not measured acoustic latency.
The quieter gain is unchanged. 114 existing offline checks and two new handoff
checks pass; no physical microphone recording was performed.

**Meaning/next:** user requested this latency problem be recorded as unresolved;
target is no perceptible delay. Full A01/A03 remain open.
The latency improvement needs user observation; 150 ms queued is still too
high for interactive audio. Smaller DSP periods/buffers require a fresh
mapping: the parked playback client retains the old region offsets/count,
so changing ALSA geometry alone on this boot risks mismatched DMA layout.
Use a coordinated fresh session/boot for that change; do not interrupt the
current DP trial or unload the live card. Keep the night volume cap.
Runtime status: `/var/lib/spx-desktop-playback/serve-ready.json`.
