# Audio: exact-waveform fix queued for BU

BU (`20261005bu`) changes only active forwarding from BT. Commit
`804b067ef187` waits for actual source frames instead of inserting five-ms
silence blocks. Idle and scoring retain local silence. The independent-clock
regression preserves the full contiguous stereo waveform and has zero
underruns with 95/145 ms producer bursts and a 250 ms hardware ring. The old
implementation fails the same test by adding 1,920 frames; 28 tests pass.

BT's shifted 436.9 Hz tone was reproduced by those silence insertions despite
zero DSP timer fallback. Its live retry remained silent after hardware reopen;
see [BT](RESULT-20261005bt.md). No gain or scoring thresholds changed. The
previously verified completion pacing and public-scoring quiet fix remain.

BU uses the same mainline kernel/DTB/module tree and fixed release. Its single
queued request is `serve --serve-seconds 0 --desktop-peak 4000`. Known-good
remains persistent default; automatic return is independently armed at uptime
900. Audio duration zero does not cancel it.

After boot inspect `/var/lib/spx-boot-diagnostics/functional/20261005bu/audio/`.
Readiness requires all temporary and actual-public acoustic checks, a closed
microphone and matching live PCM/boot ID. Verify continuing playback before
calling ordinary desktop audio ready. No continuous recording is intended.
Never re-arm a consumed request; collect failures before selecting another
experiment. Retire BT payload/staging/instance links once BU becomes current.

A01a/A03a are open after regressions; BS had verified the louder public path
but did not reach a stable handoff. Hardware reopen, WCD RX overflow, ADM
capture-close timeout, persistence and listening-volume acceptance remain open.
Do not reload WCD/ADSP providers around parked ownership.
