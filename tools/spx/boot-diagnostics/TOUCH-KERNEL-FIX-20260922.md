# Bounded SPI-HID startup recovery, 2026-09-22

The proposed K kernel fixes a software recovery gap demonstrated by J: one
invalid response consumed the only startup fallback, leaving no HID device
and therefore no touch service to restart. The patch is built and checked
offline; hardware recovery and physical touch input remain unverified.

## Evidence and scope

J boot `6a9377c7-dcd8-463c-823e-c29710eb5e96` runs the unchanged G driver.
Its monotonic kernel journal records probe D3 to D0 at 27.124260 seconds,
the fallback at 27.627035, a `00 00 00 00` header, and error attempt 0 at
27.633859. No further SPI-HID recovery message followed. This is an earlier
enumeration failure than [I's failed HID open](TOUCH-STARTUP-20260922.md).
The I userspace retry policy cannot recover a device that was never created.

Changes are confined to `drivers/hid/spi-hid/spi-hid-core.c` and its header.
No live probe, rebind, reset, service restart, config change, or boot artifact
deployment was performed for this implementation task. The underlying cause
of the zero header is still unknown.

## Recovery policy

The existing 500 ms fallback now repeats within a fixed 2,000 ms startup
window. Normal scheduling permits reads at 500, 1,000 and 1,500 ms; the
deadline check prevents a fourth read. Workqueue delays can reduce that
number. If a SPI transfer is already pending, the worker observes it without
incrementing the pending count or submitting another read. This applies to
both initial probe and a fresh HID open.

`startup_active` and `startup_deadline` are protected by `input_lock`.
Startup protection begins before IRQ-driven startup can run. Arming after
reset release checks the flag again, so an already received device descriptor
does not start polling. Receiving `DEVICE_DESC` clears the flag and cancels
the delayed worker under the same lock; descriptor parsing then proceeds via
the existing create/refresh workers.

An invalid startup input retires its failed transfer under `input_lock`,
without queuing the generic error worker. The bounded polling window owns
these retries. Synchronous startup errors likewise leave recovery to this
window. The maximum generic reset-attempt count remains **3**; the dormant
shared EC/SAM reset branch is not enabled and no counter is raised.

When the polling deadline expires, polling stops and logs
`startup response polling timed out`. Startup protection intentionally stays
active until descriptor success or explicit power-down. A late valid IRQ can
still enumerate the device; a late invalid startup IRQ cannot invoke generic
destructive recovery. There is no further software polling or automatic power
cycle. A HID open still times out after its existing two-second wait and
quiesces the transport. A failed initial probe can remain unenumerated and
powered, accepting only real IRQs. This is a finite recovery attempt, not a
guarantee that the device will become ready.

## Lifetime and locking

Repeating asynchronous reads needs an explicit shutdown boundary:

- `input_idle` is reinitialized before submitting input. A successful
  header-to-body or body-to-next-header chain leaves it unsignaled. Only a
  terminal callback or failed submission signals it. This tracks actual SPI
  activity; the queued report count alone cannot do that.
- Power-down clears `powered` and `startup_active` under `input_lock`, then
  synchronously cancels the delayed worker and waits for `input_idle`.
  Reacquiring `input_lock` after the wait ensures the terminal callback has
  left its critical section before hardware power-off or subsequent reuse.
  IRQs and callbacks check the power gate before submitting or processing.
- A permanent `stopping` flag closes input and open paths during removal and
  post-IRQ probe failure. It remains effective if regulator disable fails.
  Shutdown drains input, cancels workers, destroys the HID device, then frees
  the IRQ. Keeping IRQ registration until pending HID opens have finished
  avoids freeing it before a late open reaches IRQ bookkeeping.
- Close and failed-open cleanup do not synchronously cancel the error/reset/
  create/refresh workers: those workers can themselves enter HID close.
  Neither startup work nor either SPI input callback calls power-down, so its
  delayed-work cancellation and input completion wait cannot wait on itself.
- Terminal errors now clear the pending count in the completion path. The
  generic handler no longer clears that count later, outside the lock, where
  it could overwrite a newer IRQ's transfer.

The wider generic recovery path still has inherited cancellation hazards,
including a reset worker calling a handler that synchronously cancels reset
work, and possible create/refresh/abort cancellation cycles. Its cancellation
policy was deliberately left unchanged. This patch prevents startup input
errors from reaching that path; it does not claim to repair all running-stream
recovery behavior. An independent agent reviewed the final startup, shutdown,
callback-chain, regulator-failure and late-IRQ paths and found no new blocker.

## Offline verification

The final source compiled with the active G configuration using
`make -j4 drivers/hid/spi-hid/spi-hid.o`. Compilation and linkage succeeded.
`git diff --check` passed. `scripts/checkpatch.pl --no-tree` reported zero
errors and zero warnings for the driver patch.

A userspace C harness extracts the **actual edited driver functions** and
runs them with mocked SPI submission, deterministic delayed-work scheduling,
and pthread mutex/completion primitives. It compiled with undefined-behavior
sanitization and passed eight scenarios:

1. Ordinary IRQ descriptor startup cancels polling before its first read.
2. A zero header with no subsequent IRQ recovers through reset and descriptor
   responses on later polls.
3. Repeated invalid input stops after exactly three polls; a late valid IRQ
   can still enumerate.
4. A busy SPI operation never receives an overlapping request, and polling
   stops at the deadline.
5. Submission failure retires the transfer and a later poll can succeed.
6. A separate shutdown thread waits for the actual body callback before
   regulator power-off and prevents rearming.
7. A fresh startup receives a fresh bounded polling window.
8. The permanent shutdown gate blocks reads even if regulator-disable fails.

This harness exercises real recovery/control functions, but mocks kernel
workqueue semantics, SPI hardware and HID parsing. It does not prove hardware
timing, every workqueue interleaving, or physical touch/pen operation. Multiple
fresh hardware boots are required because the observed failure is intermittent.

The reproducible harness, generated C, binaries, original and edited sources,
tested configuration/object, compile/style logs, and filtered J kernel evidence
are preserved in `/var/tmp/spx-touch-kernel-fix-20260922/`, with `SHA256SUMS`.
The K attempt archive should copy this whole directory before reboot.

Final source hashes:

| File | SHA-256 |
| --- | --- |
| `spi-hid-core.c` | `0803e404fa587baa04e813955acb831ef7b9b00a3d1f0aec16389baa622ed9ee` |
| `spi-hid-core.h` | `58a91320a1a071821540291b9edf5d1831a8c06c1bc51876629511cd7b44e5c1` |
| Tested G `.config` | `bce9cd54b597a55c58e2264a94d25a877bf358dcc26f357d4673753471264bc2` |

The original C source hash was
`05db7de922111727df1699f18e3c37476f69a1ca91a2b6c228a4932d2ba2478b`.
