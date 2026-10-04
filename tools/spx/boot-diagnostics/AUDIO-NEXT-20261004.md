# Desktop audio after BO's stopped test

BN passed automatic left/right/both acoustic verification on mainline; the
amps-off control removed the tones. BO forwarded one real desktop application's
left tone through PipeWire/PulseAudio into that native stream, but stopped on
insufficient contrast against the earlier startup reference. See [BO](RESULT-20261004bo.md).
Full A01/A02/A03 acceptance remains open.

The bounded `audio.py desktop` action is implemented. It initializes one fresh
S16_LE/48 kHz/stereo PCM, period 2400/buffer 12000, and forwards a temporary public
Pulse sink at unity gain. All applications explicitly select this test sink;
the default output is unchanged. Legacy bridges and hardware probing stay off.
Temporary graph overrides are removed afterwards. Keep WCD/ASM persistence and
fixed geometry; never reload the WCD clock provider to repair parked ownership.

The next trial uses two fixed seconds of quiet immediately before each tone,
chosen before playback, with unchanged tone levels, 10 dB contrast, clipping
and noise limits. It checks left/right/both, five seconds idle and a second app,
all within the 45-second desktop session and continuous DMIC1 monitoring.
Retain the same native PCM owner across applications. On normal completion,
close PCM while amps remain attached, require ports/PA off and an empty FIFO,
then park GPIOs. Abort still parks immediately; monitor queue production stops
before the PCM consumer closes so cleanup cannot invent a forwarding stall.

External power is connected. BO's later unexplained interruption left incomplete
filesystem writes; the exact Git commit/history and helper were restored and
connectivity verification passed. Next trial returns 61 seconds after results
are saved. This bounded return does not resolve the unexpected-stop cause or
establish long-term stability. Do not blindly re-arm a consumed test.

A successful bounded result would support a subsequent persistent desktop bridge
and same-geometry reopen test. Generic sdm845 UCM still uses the wrong playback
route, SLIMBUS_0_RX instead of the working SLIMBUS_2_RX, and cannot perform the
required post-RUNNING late initialization by itself. The installed old bridge's
44x gain and channel drop must remain excluded. Useful volume, balance, physical
channel mapping, other microphones and reboot/resume need separate coverage.
