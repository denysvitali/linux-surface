# SPX intermittent SPI-HID startup failure, 2026-09-22

Attempt I's touch daemon failed to open the SPI HID device, then recovered
after one ordinary service restart. A source review finds an incomplete
startup recovery path and an inconsistent retry budget. It does **not**
establish the cause of the first invalid SPI header or a regression caused
by the audio stage. A bounded service retry is a reasonable availability
mitigation; the transport still needs a separate, measured correction.

This review changed no kernel source, live input state, service policy or
audio state. The running source is
`drivers/hid/spi-hid/spi-hid-core.c`, Git blob
`363198b41965def52ca99688ede65ae70f55969f`, SHA-256
`05db7de922111727df1699f18e3c37476f69a1ca91a2b6c228a4932d2ba2478b`.
Its only difference from the sibling 6.18 working file is the redundant
return-type `const` qualifier on `spi_hid_power_mode_string()`. The sibling
file includes substantial uncommitted startup changes; its branch HEAD alone
does not describe that file. Mainline imported it in `e9643f0ad6f9`.

## Observed sequence

Boot ID `90b986c6-2f3e-49be-9418-d212e37e9f9c`, attempt `20260922i`,
release `7.3.0-rc2-spx-mainline-20260922g+`. G, H and I use the same kernel
and input module. Times are journal monotonic seconds.

| Seconds | Observation |
| --- | --- |
| 28.099141 | SPI HID descriptor enumeration publishes `hidraw4`. |
| 28.100022 | Creation work powers the unclaimed transport down, D0 to D3. |
| 28.244575 | `iptsd@dev-hidraw4.service` starts. |
| 28.295407–28.297389 | Header is `00 00 00 00`, rejected with `-EINVAL`; error attempt 0. |
| 28.809301 | The one-shot startup worker prints its missed-reset-IRQ fallback message. |
| 28.812031–28.813552 | Another zero header; error attempt 1. |
| 30.304365 | `spi_hid_ll_open()` reaches its 2-second firmware-ready timeout, `-110`. |
| 30.305078 | Daemon exits 1; its error says opening `/dev/hidraw4` timed out. |
| 239.088593 | Root starts one ordinary service restart after archiving the failure. |
| 239.148259–239.153867 | Another zero header; the retained error counter logs attempt 2. |
| 239.297218 | `spi_hid_ll_open()` completes successfully, D3 to D0. |
| 239.321115–239.321448 | Daemon connects; virtual touchscreen and stylus are created. |

The failed state and intervention are preserved under
`/var/lib/spx-boot-diagnostics/attempts/20260922i/touch-recovery/`.
The initial service had `Restart=no`, `NRestarts=0`; the restored service is
active. A later read-only sample reports `ready`, three bus errors (`-22`),
zero logic errors and zero device-initiated resets. Physical gestures remain
untested. See [I result](RESULT-20260922i.md) for the final observation status.

An invalid first header is not unique to I: G logged `ff ff ff ff` and error
attempt 0 at 25.647662, then completed open at 25.786639. H had three separate
open/close cycles with the same single `0xff` error followed by successful
opens, then virtual devices at 28.008044/28.009154. I differs by not receiving
a successful startup response after its first error, and by the zero value.
These are observations, not proof of the electrical reason for either value.

## Source-backed findings

1. **Recovery can exhaust its only startup kick.**
   [`spi_hid_ll_open()`](../../../drivers/hid/spi-hid/spi-hid-core.c#L1180)
   resets the ready completion, asserts reset, sets ACTIVE, enables the IRQ,
   powers up and deasserts reset. It schedules one fallback after 500 ms and
   waits at most 2 seconds. The
   [fallback](../../../drivers/hid/spi-hid/spi-hid-core.c#L422) performs one
   ordinary queued read. Its message claims an IRQ was missed, but it does
   not measure that condition; it only checks that the device is not ready
   or OFF. A rejected asynchronous header schedules the
   [error worker](../../../drivers/hid/spi-hid/spi-hid-core.c#L976).
   The soft branch clears state, sleeps 1–2 ms and waits for another IRQ. It
   neither retries the read nor re-arms the fallback. Thus the observed
   two-header failure can leave no software recovery action before timeout.
   The DT interrupt is falling-edge triggered, so another edge cannot simply
   be assumed. Whether the hardware generated or lost an edge on I is unknown.

2. **The error budgets contradict the documented escalation.**
   [`SPI_HID_MAX_RESET_ATTEMPTS`](../../../drivers/hid/spi-hid/spi-hid-core.c#L55)
   is **3**, but `SPI_HID_SOFT_RETRY_ATTEMPTS` is **5**. The
   [handler](../../../drivers/hid/spi-hid/spi-hid-core.c#L307) first tests
   `attempts++ >= 3`, and on failure disconnects/destroys the HID and powers
   down. Only counters 0, 1 and 2 reach the soft branch; the full EC reset
   below it is unreachable through this counter sequence. Raising the
   maximum alone would newly expose a destructive EC reset and is not an
   appropriate unreviewed fix. Historical sibling commit `4d0b2d2e436f`
   introduced five soft attempts to avoid disrupting the shared Surface
   Aggregator session and type-cover key releases, without increasing the
   pre-existing maximum of three. The maximum and abort test date back to
   original driver commit `35e7032e74a9` (2022-05-18). The dormant reset branch
   selects the reset pinctrl state, sets OFF, sleeps 250 ms, sets ACTIVE and
   selects active pinctrl. It is a reset-line operation, not a software-only
   retry. **I never logged the abort or entered this hard-reset branch**;
   the inconsistent budget is a latent defect and a retry limitation, not
   the demonstrated cause of I's initial timeout.

3. **The failed-open error budget survives a daemon retry.**
   The [timeout cleanup](../../../drivers/hid/spi-hid/spi-hid-core.c#L1263)
   disables the IRQ, powers down and drops controller runtime-PM, but does
   not clear `attempts`. HID core decrements its unsuccessful open count
   without invoking low-level close
   ([`hid_hw_open()`](../../../drivers/hid/hid-core.c#L2476)); normal close
   would clear the counter. The later log's attempt 2 confirms this for I.
   A valid device descriptor resets the counter at
   [line 652](../../../drivers/hid/spi-hid/spi-hid-core.c#L648). Therefore the
   successful restart restored the transport before the next failure would
   have reached the abort branch. Three userspace starts do not imply three
   independent kernel recovery budgets.

There are also concurrency concerns to investigate, not established causes:
the error worker updates `input_transfer_pending`, `input_stage` and `ready`
outside `input_lock`, while IRQ/completion paths use that lock. A concurrent
valid completion or edge may race state clearing or cancellation of reset
work. Enabling the IRQ before power-up/reset release can also permit an early
read. The present journal lacks the ordering needed to choose between these
paths and a hardware startup issue. The earlier HID publication/open race is
already addressed by `ll_open_lock` in creation work; I's log shows creation
power-down before daemon start, not evidence that it powered down an open
client.

## Bounded userspace mitigation for a subsequent observation

After I's required baseline and failure/recovery archive are complete, a
reviewed SPX service drop-in can use:

```ini
[Unit]
StartLimitIntervalSec=120s
StartLimitBurst=3

[Service]
Restart=on-failure
RestartSec=10s
```

Keep the existing device binding, `StopWhenUnneeded=yes` and SPX executable
override. Scope deployment to this machine's iptsd service, without changing
the packaged unit. There is no reason to restart the healthy daemon to apply
this future failure policy. Record the exact file, merged unit properties
and hash as a userspace change before the next boot.

Installed `systemd.unit(5)` and `systemd.service(5)` document that start
limiting includes the initial and manual starts. With repeated 2-second
failures this permits three starts in 120 seconds, normally the initial
start plus two retries at 10-second intervals after each exit. Once the limit
is reached systemd does not automatically resume retries just because the
window expires. This is a rate limit, not an absolute per-boot lifetime limit:
a later manual/device activation or failures separated beyond the window
can start a new sequence. `BindsTo=` may stop the unit sooner if the kernel
abort removes the device. No special failure reboot/reset action is needed.

This policy addresses the observed absence of userspace recovery. It does
not fix the kernel budget, prove a 10-second delay sufficient, or guarantee
recovery from the next startup failure. Preserve the first failure and all
automatic restarts in the journal rather than treating a later active state
as clean startup. A device-free mock service may verify the restart limit;
do not induce input failures or reset/rebind the live transport for that test.

## Next kernel investigation

On a separate input-focused trial, first capture bounded startup state
events and IRQ timing around the naturally occurring open. Existing SPI-HID
tracepoints expose report-processing state, pending count, power state and
ready state. Select state/IRQ events; avoid blanket raw input payload tracing.
Capture the initial attempt through completion/timeout and any ordinary
service retry, then disable the extra tracing. Do not conflate the service
retry policy with a source fix in the result.

Use that ordering to design an explicit per-open startup recovery budget:
distinguish initialization from a running stream, synchronize error-state
changes with transfers, retain a bounded pending-response retry while not
ready, and cancel/drain startup work before final timeout cleanup. Decide
the escalation policy explicitly instead of merely making the dormant EC
reset branch reachable. Verify successful startup, one transient header
error, absent response until timeout, repeated failures across a fresh open,
and close during pending startup before deploying a new module/kernel.
Build/archive a distinct trial and compare multiple boots; never infer the
intermittent startup defect is fixed from a single successful boot.
