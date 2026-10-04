# BK: fresh stereo playback candidate, startup with amplifiers parked

BK is installed for a one-shot mainline boot from recovery
`1940d138-1de0-4a84-8bf0-0cacc3e4edcb` (`6.18.3-1-surface+`). BJ's scheduled
return completed at18:59:07CEST; its both-amplifier initialization passed, but
audible playback remains untested. Do not select BJ again.

The release stays `7.3.0-rc2-spx-mainline-20261004bg+`, with the same Image,
board configuration and private Bluetooth address. Two modules were rebuilt
incrementally. `432b8793466f` maps native physical left/right speakers to
master DP1/DP4 independently of bus address. `94d48470830e` adds per-codec
late initialization after stream startup, with error propagation and minimum
gain checks. `7469b5f09155` exposes port banks and fresh WCD compander/volume
registers. PA/protection readouts remain driver shadows, not hardware evidence.

The reusable audio tool has a separately authorized `listen` action. It powers
and identifies both native amplifiers, routes stereo, opens one owned PCM on
digital silence, verifies the known runtime transport, and late-initializes
each codec. After one second of silence it plays two seconds left, right, then
both, with sample peak1433/32768 and minimum PA gain. It attempts powerdown
before closing PCM on every exit. No microphone capture. This fresh-start
sequence is WIP and has not run on hardware.

Startup uses parked GPIO direction/output `0x1e/0x18`, with desktop audio and
legacy bridges suppressed. **No audio request is armed.** The previous BJ power
authorization is consumed; ask for this specific listening run after BK starts.
Startup static can be loud independently of tone volume. Listen for correct
left/right location, clear tones and absence of crackle/static; report each.

Validation passed: two-module incremental build, four offline PCM/tone/permission
checks, dependency resolution, initramfs creation, GRUB syntax and installation.
Known-good remains the persistent default; the generic900s return/check timers
are enabled. State and future logs are in
`/var/lib/spx-boot-diagnostics/functional/20261004bk/`. Check live boot ID,
`selected.json` and pending boot selection after any interruption; never re-arm
blindly. On BK, collect startup checks and extend the existing return timer if
needed for the human session. A01 remains open; this preparation closes no box.
