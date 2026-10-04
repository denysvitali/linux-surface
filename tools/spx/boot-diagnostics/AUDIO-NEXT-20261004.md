# Audio: completion-paced startup queued for BS

BS (`20261005bs`) changes only startup pacing from BR:
`q6asm_dai.spx_force_timer_pacing=0`. The same mainline kernel, DTB, fixed
release and module tree are retained. Its consumed-once request is
`serve --serve-seconds 0 --desktop-peak 4000`; PA remains minimum and scoring
thresholds/temporary test levels stay unchanged. Persistent default is
`spx-known-good`; automatic return remains independently armed at uptime900.

BR's fresh startup had no ALSA underrun, but its 440 Hz stimulus arrived near
435.9 Hz. The nominal-frequency scorer failed before the higher-volume public
route. Both amplifiers initialized correctly. Two live reopen tests remained
silent, including completion pacing with211 submitted/211 completed buffers
and zero fallback. Do not infer that ALSA RUNNING or WRITE_DONE proves sound.
See [BR](RESULT-20261005br.md). All captures stopped and amplifiers parked.

The known 6.18 findings already functionally validated completion pacing
(PROGRESS.md section24, V17). Current q6asm filters immediate write ACKs;
WRITE_DONE counters are real completion events. BR's forced timer mode ignored
those events and rescheduled relative delayed work, allowing timing drift.
BS will test completion pacing from the working first-open path; no new
kernel build or provider reload is needed.

After reboot inspect `/var/lib/spx-boot-diagnostics/functional/20261005bs/audio/`:
`serve-ready.json` must match the current boot/live PCM and establish temporary
and actual-public acoustic passes plus `recording_closed`. Keep the retained
PCM for ordinary playback; no continuous microphone recording is intended.
Collect failure evidence before another action; never re-arm consumed requests.
Retire BR boot/staging/instance links once its result is collected and BS is
current. BQ has already been retired; its evidence remains.

A01a/A03a are reopened after the regression; A02a's known-stimulus microphone
capture remains established. FullA01/A02/A03, hardware reopen, WCD RX overflow,
ADM capture-close timeout, useful volume and persistent integration remain
open. This is the third boot after BP without a usable desktop handoff: if
BS fails, park this approach and record the blocker per AGENTS.md.
