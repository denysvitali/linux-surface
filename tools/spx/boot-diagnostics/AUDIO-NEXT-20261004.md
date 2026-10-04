# Audio: ordinary desktop bridge prepared for BQ

The user reports normal applications are silent on recovery boot
`ab15d0b8-0e5b-404b-a380-246b9878f4ca`, `6.18.3-1-surface+`. The default
`spx_speakers` sink has no hardware PCM owner: a stale September armed marker
skips the legacy bridge, while its orphan PA gate still starts. Those legacy
services are stopped and their bridge autostart disabled. Do not start the old
bridge: it applies 44-times amplification. Recovery lacks the native interfaces
used by the successful mainline path.

BQ (`20261004bq`) is installed and queued once with `serve`, using BP's unchanged
mainline kernel/DTB. The new helper first repeats the bounded desktop check,
then verifies the actual public sink through fixed stereo attenuation
1433/32768. After the microphone closes and capture routes restore, it retains
the same PCM for an eight-hour application session. The desktop slider starts
at 100% within that low output limit. Successful normal stop closes the attached
PCM before parking; errors park immediately. The existing return timer remains
armed beyond the session and moves to 61 seconds after completion/failure.

**Live BQ verification is pending.** Inspect `audio/serve-ready.json` and
`audio/serve-result.json` under its functional result directory. A ready file
must match the current boot and a live owned PCM; it requires both acoustic
passes and a closed recording. Do not re-arm a consumed request. Implementation
is `16793526c9f3`, wrapper `7ab2fef9e920`; 25 audio, 13 scorer and 4 queued-request
tests pass. Persistent boot selection, useful volume and lifecycle reliability
are not established by this prepared session.

BP passed microphone-verified desktop left/right/both tones and a second
application after five seconds idle, through a temporary public Pulse sink and
one initialized native ALSA PCM. Closing playback while amps remained attached
left both speaker paths disabled and an empty SoundWire FIFO. Physical parking
then kept the FIFO empty. See [BP](RESULT-20261004bp.md). A03a is closed;
full A01/A02/A03 remain open. BN supplies the amps-off acoustic control.

The working recipe is `audio.py desktop`: native sequential enumeration,
minimum PA gain, post-RUNNING late initialization, S16_LE/48 kHz/stereo,
period 2400/buffer 12000, unity-gain monitor forwarding. Keep WCD/ASM persistence
and fixed geometry. Each phase scores against two fixed seconds of quiet taken
before playback; thresholds and signal levels remain unchanged. Do not repeat
the earlier global startup-reference mistake or increase gain to hide noise.

BP removed its temporary sink/graph. BQ tests the missing ordinary-application
producer. Keep legacy 44x amplification and channel dropping excluded. Generic
sdm845 UCM uses SLIMBUS_0_RX instead of working SLIMBUS_2_RX and cannot itself
perform late initialization.

Before claiming lifecycle reliability, resolve the remaining WCD RX-port
overflow and ADM capture-COPP close timeout (-110), then test same-geometry
hardware reopen and repeated boot/resume. A second desktop application on the
same retained PCM is not a hardware reopen. Never reload the WCD clock provider
as a shortcut around parked ownership. Preserve immediate amp parking on
failures and the verified close-before-powerdown sequence on normal completion.

BN and BP returned on schedule. BL/BM/BO stopped unexpectedly before their
returns; the cause remains unknown. BO's incomplete Git/helper writes were
recovered exactly and connectivity verification passed. Keep changes committed
and synced before boots. BP's short successful run does not prove longer-term
stability. Useful volume, physical channel mapping/balance and other fitted
microphones still need coverage.
