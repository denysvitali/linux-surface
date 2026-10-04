# AW full current candidate and bounded GPU trial

Candidate: `7.3.0-rc2-spx-mainline-20261003au+`, immutable full build at
`/var/lib/spx-boot-diagnostics/attempts/20261003aw/build`.
AW reuses the byte-identical full AU build after actual AV baseline pass and
terminal GPU collector failure, followed by verified known-good return UUID
`50077400-0ef4-4712-932d-0fe1a231e2ad`. AV's first short GL validator passed
15 pixels but production five-second polling missed its render FD; zero sustained
rows/GLES occurred. AV failure remains failed. The new collector samples20ms
through validation and until first render FD; sustained sampling remains5s.
Synthetic short-lived-FD tests reproduce the old miss and verify12 new cases.
Known-good reference uses identical production validation sampling and passes
60 pixels/30 short rows with renderD128 witnesses in all10 runs. This is setup
validation only. The original missing-witness assertion remains required.

Read `LOCAL-PROGRESS.md`, `PORT-CHECKLIST.md`, `archive-review.json` and
`gpu-workload-20261003/README.md` (original workload source) before interpreting results.

The unchanged full AU image and 193 modules include the rear standby/reset cleanup and
synchronous V4L2 privacy LED ordering changes. Config differs from AR only in
LOCALVERSION. Deployed DTB is byte-identical to AT's rear-only/LED DTB; CAMSS
receiver stays disabled. No new camera streams or sound playback are requested.

Known-good outgoing UUID is `50077400-0ef4-4712-932d-0fe1a231e2ad`,
release `6.18.3-1-surface+`, preexisting taint4096. Candidate requires taint0.
Persistent GRUB default remains `spx-known-good`. User's explicit
2026-09-22 reboot authorization applies, including possible manual power-cycle
recovery. Recovery across EFI/early kernel remains unvalidated.

Six attempt-specific timers preserve the existing strict baseline and bound
the new experiment. Camera provider60s, read-only rear/LED control120s,
baseline620s, GPU workload660s, GPU result review2800s, fallback3300s.
Generic short/long return timers cannot run for this attempt. Each service
requires AW's command-line selector; all stay inactive on known-good.
The baseline always leaves the fallback armed. GPU launch requires the
independently recomputed baseline and camera idle pass on the actual new UUID.

The unchanged root-owned public AU fixture exposes only the two render-node GBM binaries
and data. Benchmark subprocesses run as dvitali using renderD128 without
modesetting. Output starts under `/var/tmp/spx-gpu-result-20261003aw` so this
user can traverse ancestors; the collector seals results root-private after
completion. Final review copies only inactive/failed service results, verifies
all hashes and recomputes60 image checks,30 timed scene rows,1800 seconds of
rendering and six30-second idle windows. It records GPU PM/thermal/desktop
state, verifies unchanged GNOME process identity and fresh touch/Wi-Fi/taint,
and checks complete kernel logs for GPU faults. It leaves fallback armed even
on a scoped pass. No live display unbind/rebind or power/role forcing occurs.

Default-precision GLES conditional pixel differed from its oracle in the
known-good reference; the retained plan explicitly uses high precision.
That discrepancy remains unresolved. Process continuity and offscreen pixel
checks do not establish heavy compositing, broad graphics conformance,
Vulkan/video acceleration or physical display correctness. Idle windows record
GPU PM counters; they do not establish power consumption or suspend acceptance.
All47 hardware acceptance boxes remain open, including D02 and final-candidate
regression. Full functionality is not inferred from build, startup or this run.

`installed-review.json`, `service-context-review.json`, a fresh read-only
native Happy continuation check and atomic `prequeue-records/` must pass before
selection. `queue-au-once.py` creates an exclusive request marker and selects
AW once, then schedules the immediate guard. The guard rehashes candidate,
source/config, fixtures/runtime and all5183 known-good module files/links,
checks the actual outgoing UUID and pending selection again, then requests
reboot. A failed immediate guard unqueues only its own selection; the exclusive
marker remains. Never blindly re-arm any failed attempt.

On continuation, read actual `/proc` identity and GRUB state first. Preserve
startup/kernel/initramfs evidence, wait for baseline/GPU outputs without
mutating active collection, and retain the fallback result and actual return
UUID. Archive/recompute the actual result before selecting another experiment.
