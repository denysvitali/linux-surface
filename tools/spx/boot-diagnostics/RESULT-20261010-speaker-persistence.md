boxes closed: 3 of 47; newly closed: none.

# Saved +3 dB and enabled native playback on baseline boots

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Request:** record the user-confirmed clear +3 dB setup and make it permanent.
The exact earlier glitch mechanism remains unproven; preserve the successful
same-stream gain change instead of treating +1.5 dB as a hardware ceiling.

**Installed:** permanent `spx-desktop-playback.service`, enabled through the
`multi-user.target.wants` symlink. Installed launcher/audio code under
`/usr/local/lib/spx`, independent of the worktree. Root-owned
`/etc/spx/speaker-gain-step` saves2 (+3 dB). Start native playback at +1.5 dB,
then apply the saved gain after5 seconds without restarting PCM/PipeWire.
Ordinary startup/shutdown now preserve the user's slider, balance and mute.
The helper waits for the card/user bus and holds the device lock only through
initialization. Startup failure does not trigger automatic retries.

System-wide PipeWire/WirePlumber parked-audio guards prevent early user/GDM
probing; the native owner enables its own user's graph after initialization.
The boot unit requires `spx_baseline` and `spx_audio=parked`, both verified in
the saved baseline GRUB entry. Trials/recovery do not start this service.

**Verification:** 119 offline audio checks pass; focused checks also verify
saved gain survives startup and applies on the same PCM after settling, and
sink volume/balance/mute are neither reset nor restored over user changes.
Installed Python parses; systemd-analyze verify accepts the installed unit.
Enablement symlink and saved2 read back correctly. The current transient
service remains active: owner19340, PCM19468 and trigger1779.108494770 retained,
+3 dB/unity gain unchanged. No sound test, capture, restart, kernel change or
reboot; camera-front's device/build locks were left intact.

**Limit:** persistence is installed/enabled, but automatic startup has not yet
been exercised on a real reboot. Validate it on the next normal baseline boot;
full A01/A03, latency and factory maximum remain open. Do not label the prior
glitch's exact cause as established.
