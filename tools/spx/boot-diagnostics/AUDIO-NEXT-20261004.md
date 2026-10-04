# Audio: scoring fix queued for BT

BT (`20261005bt`) changes only the public quiet/scoring interval from BS.
Commit882a287e9c6a keeps local silence feeding during CPU-bound analysis and
microphone teardown, then resumes monitor forwarding before handoff. The
independent-clock regression reproduces22 underruns without this fix and zero
with it;29 audio tests pass. Kernel/DTB, completion pacing, geometry, levels
and thresholds remain unchanged. Request: `serve --serve-seconds 0
--desktop-peak 4000`. Persistent default is `spx-known-good`; fallback900 is
independently armed and is not canceled by audio duration0.

BS restored correct440/660 timing and all four temporary desktop phases.
The actual public spx_speakers route also passed at cap4000, approximately9dB
above the prior digital limit, with unchanged PA gain and no detected excess
noise/clipping. ALSA then underrran during public scoring, so no handoff
occurred. See [BS](RESULT-20261005bs.md). The live scoring-fix retry was silent
after hardware reopen; it never reached public scoring. First startup remains
the working path. Do not reload WCD/ADSP providers to bypass parked ownership.

After boot inspect `/var/lib/spx-boot-diagnostics/functional/20261005bt/audio/`.
A valid `serve-ready.json` must match the current boot/live PCM, both acoustic
passes and `recording_closed`. Confirm the PCM continues running before normal
desktop handoff. No continuous microphone recording is intended. On failure,
collect evidence before another action and never re-arm a consumed request.
Retire BS boot/staging/instance links after BT becomes current; BQ/BR are
already retired with evidence retained.

A01a is restored by BS; A02a remains established. A03a, hardware reopen,
WCD RX overflow, ADM capture-close timeout, persistent integration and useful
listening volume remain open. BS made functional gain in timing and public
output; it did not make ordinary desktop playback reliable yet.
