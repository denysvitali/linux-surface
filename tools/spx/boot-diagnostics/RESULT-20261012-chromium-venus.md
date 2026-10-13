boxes closed: 3 of 47; newly closed: none.

# Chromium Venus: gate found, playback not fixed; live work stopped

Chromium152.0.7977.64 ArchARM, kernel7.3.0-rc2-spx-mainline-20261004bg+.
Boot6272005e: coherent tested Venus core+decoder plus
`--enable-features=AcceleratedVideoDecoder` enables video_decode and H264/VP8/
VP9 profile discovery. ArchARM builds native V4L2, not VAAPI; the runtime gate
was off and prior successful FFmpeg tests had unloaded their modules. No new
persistent browser flag, baseline install or encoder test.

Actual muted local H264High1080p stalls time0, readyState1, zero frames,
OUTPUT16/16 CAPTURE0/0. Chromium waits SOURCE_CHANGE before CAPTURE; FFmpeg
starts CAPTURE eagerly. Teardown proves lock deadlock: IRQ13160 waits
inst->lock in vdec_event_change; decoder14771 holds it in STREAMOFF/FLUSH and
waits disable_irq in the added session poller. Close also waits synchronize_irq.
Candidatee294913022d2 deletes session polling/private lock and restores bounded
completion waits, retaining core startup polling. Canonical modules build;
no live native-IRQ init/playback pass. Initial stall is not proved by teardown.

Recoveryboot4f9a4987: installed old core first fails reset/probe-110. At21:28:15
manual candidate core insertion logs PAS9 auth-resetret0, then sudo session
closes. Next source step is protected-video VIDEO_VAR SCM; post-return log is
missing. No decoder insertion/new Chromium trial log survives. Later hang/reset
reported by user; journal tail cannot identify its cause or blocking instruction.
Pstore empty; same protection tuple and failed-old-core->candidate transition
passed before, so no protection/range/timeout patch justified. Firmware/core/PM
startup code is unchanged by e294913. Currentboot93f93c82 unchanged7.x.

User forbids reboots. Live browser/module/hardware tests stopped; offline
continuation only. Source inspection also finds synchronous event callbacks
can delay later completion packets while an ioctl holds inst->lock, but normal
wait is bounded; no evidence this causes initial stall or reset. No speculative
async rewrite. Need fault/ordered packet evidence for any further fix; unavailable
without a separately authorized trial. No numeric hardware constants changed.
Reset left temporary /etc/modprobe.d/spx-venus-coherent.conf empty; not edited,
not a functioning barrier. Running modules/config untouched in continuation.

Evidence /var/tmp/spx-chromium-venus-deadlock-stacks-20261012.txt,
spx-chromium-diagnostic-v4l2-20261012.log, spx-venus-reset-retained-20261012.txt,
spx-venus-post-auth-offline-20261012.md, spx-venus-event-order-offline-20261012.md.
