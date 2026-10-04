# SPI-HID worker recovery after AL

AL's original405-file result and583-file automatic return were rehashed before
work. Current known-good boot remains5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5,
6.18.3-1-surface+. No boot selection or live device manipulation occurred.
The prior self-wait-v2 source/config/diff was frozen before these corrections.

The remaining recovery call sites were reset descriptor-write failure, unsupported
create/refresh device descriptor versions, and synchronous request timeout. The
last call happens after reacquiring shid->lock, including report-descriptor requests
from HID creation/parsing and refresh. Reset work flushes create/refresh work;
inline recovery from those workers can wait for reset or for the caller itself
at terminal abort. A request holding the mutex can also wait for work that needs
that caller to finish. Skipping only reset's self-cancel does not remove these cycles.

All four process paths now request the existing error_work. Only that worker
calls spi_hid_error_handler. A small helper holds input_lock while checking the
existing stopping/powered/startup/power-state gates and publishing work. Shutdown
sets stopping under the same lock before canceling work; a late request cannot
publish recovery after cancellation. Input completion's existing locked error
publication is unchanged. Recovery is deferred and multiple requests may coalesce;
attempt budgets still apply per executed error handler. Synchronous request return
values, wire requests and success paths are preserved. No retry/reset budget or
power timing change is included. The prior reset self-wait guard remains defensive.

Terminal stop previously disconnected shid->hid before waiting for create/refresh
publishers, and waited for neither when the pointer was null. A running successful
create can subsequently dereference shid->hid; a pending publisher can outlive the
stop. The corrected stop sets the permanent stopping gate, drains both publishers
regardless of current pointer value, then disconnects/destroys the resulting HID.
This gate remains set if later power-off fails. Stop has exactly two call paths:
the dedicated error worker's terminal abort and external shutdown/remove cleanup.
Neither publisher calls recovery inline after the first correction.

This fixes the reviewed synchronous work-wait cycles and publisher-pointer lifetime
hazard. It does not prove every output/HID/core interleaving safe. In-flight output
transactions and electrical power-off are not modeled exhaustively. The existing
teardown helper still has no registered SPI driver reboot shutdown callback. No
initial-probe retry, descriptor bootstrap, reset/power change or audio policy change
is implemented. AL's no-IRQ/three-zero-header initial-probe timeout is unresolved.

Verification extracted the actual old/new caller, error, stop and shutdown functions:

- Deferred candidate:1536 four-caller cases plus32 unchanged-path cases,44 old
  modeled wait cycles, ASAN/UBSAN. The actual publication helper passed a pthread
  stopping/publication race with20000 post-stop requests and no late queued work.
- Stop candidate:108 stop/terminal-abort/shutdown cases with idle/pending/running
  publishers, null/present HID and failed power-off. Controlled publishers exposed
  10 old stale-pointer and14 old surviving-publication cases. ASAN/UBSAN passed.
- Combined final source:1536+32 caller cases and publication stress passed again
  after integrating the stop change. Native SPI-HID object compilation produced
  no warnings; both isolated patches and combined patch pass strict checkpatch.
  Config50118c6b... and all other tracked diff chunks remain unchanged.

Mocks model workqueue waits, publisher behavior, HID and SPI. Counts are deterministic
software scenarios, not hardware boots or an exhaustive workqueue proof. Initial
harness formatting/stub compile failures are preserved in the candidate archives.

Final driver f29d249fbb55d336a2286beff7fd6bb66e11d90eb8d616f6712747656a4acee5,
full diff3e57067835c4c13ab730247277a3002fc40e34622e9bb931d061dd6d67fc0770.
Archives under AL:21 deferred files782ad2fe...,17 stop files3a79a28f...,
20 combined files7c590f4e.... All are source/object candidates, not installed boot
payloads or hardware-tested releases. AK modules, boot slots, private initramfs,
DTB and known-good recovery remain unchanged. The full module/kernel build must
use a distinct release before deployment; /boot currently has only about3MB free.

Next work is a separately reviewed reboot quiesce callback using these corrected
worker lifetimes, with evidence of actual outgoing execution and a controlled
subsequent incoming boot. Review remaining in-flight synchronous output ownership
before enabling that callback. A warm-retained firmware cause is still a hypothesis;
a successful single boot cannot establish touch reliability. A bootstrap alternative
requires transport reservation, IRQ deferral/draining and late-reset/two-reply design.
No new hardware trial is selected, and AL is not re-armed.
