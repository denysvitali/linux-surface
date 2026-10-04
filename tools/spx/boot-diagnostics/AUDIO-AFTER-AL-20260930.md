# Next boundary after AL

AK pin2 and AL pin1, with identical artifacts and both detached control guards,
each pass native identity/attachment/initialization and selected no-error checks.
AL fails the whole scope because touch never enumerates. Preserve these separate
outcomes; do not loosen the final touch readiness requirement or claim acoustic
output, both-speaker operation or hardware acknowledgment.

The next justified work is the SPI-HID initial-probe/warm-handoff lifecycle audit.
AL repeats K/AC's no-delivered-IRQ/three-zero-header initial-probe failure. Existing
userspace retry handles ordinary HID opens, and cannot retry an unpublished HID.
AK's later ordinary open recovered; AL supplies no such open. More startup log
windows, an audio route change, or blind AL re-arm would not address this path.

Inspect the actual SPI bus shutdown dispatch and the driver's teardown, input
reservation, PM ownership and power sequencing before proposing a hardware change.
The current spi_hid_shutdown helper is used by remove/probe cleanup, while the
spi_driver table has no shutdown callback. Warm-retained firmware state remains
a hypothesis; the name of that helper does not establish reboot execution.
A future shutdown hook must quiesce IRQ/work/SPI before power-off, retain permanent
stopping even if regulator-disable fails and avoid HID close/worker cancellation
cycles. Existing full-reset escalation is disruptive to the shared EC. A future
descriptor bootstrap needs a complete transport reservation design so IRQ-driven
header/body reads cannot interleave its write; do not shortcut that requirement.

First freeze AL source/config/results, verify actual known-good return and hashes.
Continue offline lifecycle analysis; no next hardware experiment is selected here.
No live restart/reset/rebind, audio/PCM/capture/input-event operation or both-pin
trial. Keep source/boot payloads and strict620/900 scope unchanged during review.

Completed lifecycle review found a separate reset-worker self-wait. The isolated
nonblocking-self/synchronous-other cancellation correction compiled and passed
12960 actual-C differential cases, preserving queued reset cancellation. Read
TOUCH-AFTER-AL-20260930.md and the frozen AL touch-lifecycle-audit plus
reset-self-wait-candidate-v2. No startup fix, shutdown hook or new trial is deployed.
Further cancellation-graph review precedes any initial-probe recovery experiment.

2026-10-01 continuation completed the worker-wait audit and two isolated source
corrections: recovery deferral through a shutdown-locked publication helper, and
permanent stop/drain before HID pointer disconnection. Native compilation, actual-C
caller/abort/teardown scenarios, publication stress and combined checks passed.
Read TOUCH-WORKER-RECOVERY-20261001.md and AL/worker-recovery-review-20261001.
Boot payloads/modules remain unchanged; no initial-probe fix or trial was deployed.
