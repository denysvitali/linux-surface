# Audio: BU default desktop playback works

BU (`20261005bu`) has microphone-verified playback through the ordinary default
`spx_speakers` sink. Both channels, simultaneous output, a second application
after idle and the louder public path pass. The microphone closes before
handoff. Two minutes of normal desktop forwarding complete without interrupting
the retained PCM. See [BU result](RESULT-20261005bu.md).

The working combination is completion pacing (`spx_force_timer_pacing=0`),
local silence during scoring, and waiting for actual frames while forwarding.
The digital cap is 4000 rather than 1433 (+8.9 dB), with PA gain still minimum.
Do not reintroduce active gap insertion: it stretches the waveform and shifts
tone timing even when PCM reports no underrun. All 28 audio tests pass,
including exact waveform preservation with independently clocked consumers.

Keep the running PCM owner open; hardware reopen repeatedly produced silence.
Do not reload WCD/ADSP providers. No continuous microphone capture is needed.
Candidate-specific startup is installed and enabled for BU through the existing
check service (`566006b1593a`, 15 focused tests pass). It validates the live
verified stream when enabled, attempts once per boot, and disables future
attempts after failure. Startup uses bounded acoustic feedback, then closes
the microphone. Enabling preserved the current owner and changed no boot
policy; its next hardware startup remains untested. Reboot/resume
persistence, clean current shutdown, WCD RX overflow/ADM close faults and full
listening-volume/mapping/balance acceptance remain open.

Known-good remains the persistent boot default. The current automatic return
is uptime 1800 while integration completes. The user's decision about canceling
this working boot's return is pending; untimed audio does not cancel it.
