# L SPI-HID startup review, 2026-09-22

L completed three ordinary IRQ-driven touch startup sequences: initial probe
and two subsequent real opens. Each received a reset response, device
descriptor and report descriptor, then became ready. No fallback polling or
invalid header was observed. This is a successful startup with diagnostics
enabled, not evidence that logging fixed the intermittent failure.

The smallest next control is a fresh attempt using the **exact L artifacts**
with `spi_hid.startup_diag=0`, retaining audio stage 4, the DTB and the current
userspace retry policy. Finish and archive L's actual 600-second baseline
before selecting that attempt. No timing, IRQ-retention or descriptor-bootstrap
change is justified by this successful trace alone.

## Evidence and scope

Reviewed live boot `90f1a5fc-5a70-4bd5-8d7d-99e45039b007`, release
`7.3.0-rc2-spx-mainline-20260922l+`, attempt `20260922l`. The live read-only
module parameter is `Y`. Collection at **415.58 seconds** is preserved in
`/var/tmp/spx-touch-l-review-20260922/`: filtered kernel metadata, IPTSD journal,
service state, driver state, identity/source hashes and parsed per-window
records. All six files are covered by a verified `SHA256SUMS`. This is an
interim touch review, not the final 600-second system result.

The source matches the frozen L source: core SHA-256
`fc0dd9640a3b99376f3ef2f73621df2ed742181b9a42751e03d8549b382d687a`, header
`31c5fcc5cfe847112101d06c7f7b77819a4173a1be20158e0d5daf63f65ccaa0`.
An independent source review checked IRQ bookkeeping and locking. This review
made no source or runtime changes and performed no input-event or raw HID
reads, reset, reload, rebind or service restart.

## The successful chronology

All timestamps below are monotonic journal seconds. The delay column measures
time between software log records, not electrical pin edges.

| Window | Purpose | Reset deassert record | First powered IRQ | Delay | Ready |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Initial probe | 25.698786 | 25.836665 | 137.879 ms | 25.894647 |
| 2 | Subsequent open | 26.191421 | 26.330729 | 139.308 ms | 26.358023 |
| 3 | Subsequent open | 26.419161 | 26.558382 | 139.221 ms | 26.607858 |

Each window reports the sequence `3 → 7 → 8`: reset response, device descriptor,
report descriptor. Each terminal summary has three headers, one reset response,
one device descriptor, zero polls and zero suppressed records. Window 1 has
three IRQ entries; windows 2 and 3 have four each because each also logged one
early gated IRQ. The 64 diagnostic records are below the 192-line lifetime
limit; no fourth window was observed at collection.

The first reset response is accepted at 25.858394, followed by the existing
descriptor request at 25.864154 and successful write return at 25.865638.
The device descriptor is accepted at 25.875601 and report descriptor at
25.893933. The first valid IRQ arrives while probe's existing settling wait
is still in progress. Fallback is armed at 25.868126, while descriptor input
is already underway, then canceled when the device descriptor arrives. The
150 ms wait therefore does not postpone IRQ processing until fallback begins.

Window 2 includes an IRQ at **26.184162** with `powered=0`; window 3 includes
one at **26.408569** with `powered=0`. Neither creates a pending read. Both
windows later receive a normal powered IRQ and complete enumeration. Existing
close/open transitions occur between the windows; these are three sequences
within one boot, not three independent fresh-boot reliability trials.

IPTSD connects to `045E:0C21` at **26.644851**. Virtual touchscreen and stylus
devices appear at **26.646534** and **26.646676**. At collection,
`iptsd@dev-hidraw4.service` is active/running with `NRestarts=0`; SPI-HID reports
ready and zero bus, regulator and logic errors, and zero device-initiated
resets. The daemon retry policy was not needed. No physical gesture or pen
function is established by this enumeration evidence.

## What the fields establish

`spi_hid_dev_irq()` takes `input_lock`, logs the IRQ, then calls the existing
input function (`spi-hid-core.c:1355`). The logged IRQ `ret=0` is a literal
argument supplied before that call, not its return status. IRQ entries count
handler invocations, including ones ignored by the power gate; they do not
independently identify a firmware reset response, a current physical edge,
or the cause of a pending/resend interrupt.

With `powered=0`, `spi_hid_bus_input_report()` returns before incrementing
`input_transfer_pending` or submitting SPI (`core.c:1241`). The lock covers
both the observation and the gate. Thus the two early IRQs were discarded in
software, with no queued read retained for later. This does not mean the rail
was electrically off: regulator enable is logged before a settling sleep,
and the software `powered` flag is set only afterward (`core.c:1302`). Power
down clears the same flag before physically disabling the supply.

In particular, window 3's early IRQ has **`irq-enabled=0` while its handler is
executing**. That is consistent with existing bookkeeping: open invokes
`enable_irq()` before setting `shid->irq_enabled = true` (`core.c:1445`). Probe
likewise calls `request_irq()`, logs `irq-request`, then sets the flag
(`core.c:1903`). IRQ registration can make the handler runnable before those
later statements. Disable paths clear the flag after `disable_irq()` returns.
The flag is not a measurement of IRQ-controller masking.

The diagnostic lock also does not serialize every writer of `irq_enabled`,
`power_state` or `ready`; these are software observations with weaker
synchronization than the protected power/read gate. A successful pinctrl or
regulator return reports software completion, not measured board voltage or
reset pulse width. The reset-deassert record precedes its 5–6 ms sleep.

Header/body `ret=0` and `value` describe the existing SPI message status and
actual transferred length; lengths include the read approval. A completed
header transaction by itself does not establish a valid header. Here it is
followed by accepted report types and ready, which supplies the stronger
evidence. Reset/descriptor counters increment at accepted report-type
dispatch, not after an independent firmware-health check.

The initial `deadline=0`, and old deadlines at the start of windows 2 and 3,
are expected because the current deadline is assigned only at the `arm`
event. No deadline interpretation should use a preceding `begin` or IRQ
record. Logging ends at ready, so a terminal startup summary is not a
whole-boot interrupt counter; later error checks also use the ordinary
journal, driver counters and daemon state.

## Comparison with K and the next control

[K](TOUCH-K-REVIEW-20260922.md) had no delivered touch IRQ and completed three
fallback header transactions, all returning zero headers, followed by the
bounded deadline. L instead has valid reset-triggered descriptor traffic in
every observed window. L does not exercise recovery from K's missing-response
condition, nor show that retaining one of L's harmless early IRQs would have
repaired K. K's initial-probe failure cannot be assigned the two early-open
IRQs observed only in successful L.

L changed bounded diagnostic code and the release identity, with no intended
reset/power/IRQ/SPI policy change. Enabled logging nevertheless adds work and
extends lock-held sections, which can alter timing and scheduling. One
successful boot can also reflect ordinary intermittency or retained device
state. The near-140 ms response timing in L does not prove a required new
delay, and successful warm startup does not rule out warm-state effects in
the previous failures.

After the complete L result is archived, assign a new attempt ID and reuse
the verified L Image, DTB, module tree and initramfs. Change only that ID and
`spi_hid.startup_diag=1` to `spi_hid.startup_diag=0` in the trial command line;
keep audio stage 4 and all other runtime policy unchanged. The booted release
should remain `7.3.0-rc2-spx-mainline-20260922l+`. Verify the live parameter is
`N`, collect normal startup/errors, HID publication, IPTSD restarts and the
full baseline. Preserve and hash each attempt, keep `spx-known-good` as the
persistent default, and select this control only once.

If the control succeeds, record clean startup without diagnostic logging,
then repeat a fresh boot before claiming reliable startup. If it fails,
collect its actual outcome before choosing a targeted diagnostic comparison;
the single on/off outcome still does not establish causality. Keep reset
timing and early-IRQ retention unchanged until evidence distinguishes a
discarded usable response from no response. The previously deferred descriptor
bootstrap still requires a transport-reservation/outstanding-response design;
L's success provides no reason to bypass that review.
