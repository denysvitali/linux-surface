# Audio after BP's desktop playback pass

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

The next useful desktop change is a persistent, clearly owned producer using
this validated startup/forwarding path, so normal applications can select the
existing `spx_speakers` output. The bounded test currently removes its temporary
sink/graph and does not install a daily-use bridge. Keep legacy 44x amplification
and channel dropping excluded. Generic sdm845 UCM uses SLIMBUS_0_RX instead of
working SLIMBUS_2_RX and cannot itself perform late initialization.

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
microphones still need coverage. No new trial or audio request is pending.
