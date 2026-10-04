# Desktop audio after BN's acoustic pass

**BN passed automatic speaker/microphone feedback on mainline.** Left 440 Hz,
right 660 Hz and both together were detected by DMIC1; the same digital tones
disappeared with the amplifiers off. Both native codecs passed late initialization
after cycling the actual machine speaker endpoints. See [BN](RESULT-20261004bn.md).
This was automatic startup after a warm reboot; cold power-on and repeatability
are not established. Full A01/A02/A03 acceptance remains open.

The user authorized bounded automated speaker/microphone tests and informed
retries. Announce capture, retain minimum PA gain and bounded levels/durations,
and park amplifiers afterwards. No new listening confirmation is required for
each run. Battery was 10% and discharging after BN; recharge before more trials.

The next concrete change belongs in `tools/spx/audio.py`: a bounded desktop
source for the existing `OwnedPCM`, adapted from the sibling tree's
`scripts/spx-retained-desktop.py`. Forward `spx_speakers.monitor` at unity gain
into the same fresh PCM that passed native initialization and late init. Keep
S16_LE/48 kHz/stereo, period 2400/buffer 12000, with one ALSA owner throughout.
Retain the current WCD/ASM stream persistence settings and their fixed geometry.

The installed `51-spx-speaker-mono.conf` already defines a stereo null sink
despite its filename. Permit the PipeWire/Pulse/WirePlumber graph for this
bounded mode while keeping hardware probing and legacy speaker bridge/gate
services disabled. The old bridge adds 44x gain and drops a channel; its gate
assumes obsolete speaker routing. Generic sdm845 UCM uses SLIMBUS_0_RX, whereas
the working SPX playback route uses SLIMBUS_2_RX and needs late initialization
after the PCM reaches RUNNING. Merely enabling that UCM profile is insufficient.

For normal shutdown, test draining silence and closing PCM while amplifiers
remain attached, then checking stream teardown/FIFO and parking GPIOs. Preserve
immediate amplifier powerdown on abort or untrusted audio. BN's deliberate
amps-off control powers down before close, causing FIFO/DAPM errors; it proves
the acoustic control but cannot also prove orderly teardown. Do not reload the
WCD clock provider as a shortcut around parked stream ownership.

The next functional test should be a microphone-monitored desktop session of
at most 45 seconds: capped two-second left/right/both signals through the public
sink, five seconds idle, then another application playback. Require sustained
tone detection, no XRUN or excessive noise, unchanged ALSA owner/geometry, and
orderly close with no new SoundWire FIFO errors followed by verified amps off.
A subsequent same-geometry reopen/reinitialization test can check lifecycle.
These are proposed tests, not passes; broader volume, balance, physical mapping,
other microphones and reboot/resume still need coverage.
