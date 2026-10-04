# K SPI-HID startup investigation, 2026-09-22

K exercised all three bounded startup polls but did not enumerate the touch
device. The polling correction behaved as intended; it did not repair the
underlying absence of a valid firmware response. The next trial should add
bounded startup metadata without changing power, reset, IRQ or SPI policy.

This investigation performed only source/history review and read-only live
collection. It did not reset, rebind, reload or otherwise manipulate input.

## Observed K evidence

Boot `58d2ebe1-1b3d-4b75-aa1e-d0ff2d8b9562` runs
`7.3.0-rc2-spx-mainline-20260922k+`, attempt `20260922k`, audio stage 4.
The loaded SPI-HID module matches the archived K module. Monotonic times:

| Seconds | Observation |
| --- | --- |
| 21.915048 | Probe reports D3 to D0. |
| 22.416564 | First startup poll. |
| 22.418892 | Rejected header is four zero bytes. |
| 22.920073 | Second startup poll. |
| 22.924312 | Rejected header is four zero bytes. |
| 23.424674 | Third startup poll. |
| 23.427161 | Rejected header is four zero bytes. |
| 23.929021 | Bounded polling deadline expires. |

The live SPI statistics report exactly three asynchronous messages, six
transfers, 15 transmitted bytes and 12 received bytes, with zero controller
errors/timeouts. There were no synchronous writes. The device IRQ (214,
TLMM122) has count zero; controller IRQ 154 has count six. Driver state is
`not ready`, three protocol errors (`-22`), zero regulator/logic errors and
zero device-initiated-reset count. That last counter only counts a reset
received after `ready`; it is not a universal count of reset responses.

No SPI HID or IPTSD instance was created. The userspace retry policy therefore
had no service to restart. The initial observation is preserved in
`/var/tmp/spx-touch-k-review-20260922/` with four files and `SHA256SUMS`;
the parent task also retains the full K baseline archive.

These facts establish successful software completion of three nine-byte SPI
transactions and no delivered touch IRQ. They do not establish that the
device was electrically ready, that returned zero bytes originated in valid
firmware, or that reset/rail transitions happened on the board. SPI can clock
bytes successfully when a peripheral is not responding.

## Source and history comparison

The wire-format helpers, descriptor request and board touch DT match the
sibling 6.18 working source. K adds startup/lifetime handling; it does not
change SPI speed, chip select, mode, reset timing or regulator selection.
Mainline GENI SPI has broader upstream changes relative to 6.18, including
automatic chip-select handling, but those same changes were present during
successful G/H/I startup. A deterministic format mismatch is not supported
by the reviewed evidence; an intermittent transport problem remains possible.

The board DTS assigns reset to **TLMM GPIO54**, interrupt to **TLMM GPIO122**
(falling edge), the SPI pins to GPIO114–117, and the 5 V enable to
**PMC8180E GPIO10**. GPIO35 is not the touch reset. The live DT retains
12.5 MHz and descriptor address 1. Parent read-only inspection found the
IRQ line high and the touch regulator enabled; these are later snapshots,
not observations of the reset sequence.

Probe selects sleep/reset-low, waits 100 ms, registers/enables the IRQ,
selects reset, waits 10–11 ms, enables the supply, waits 5–6 ms, marks the
transport powered, selects active/reset-high, waits 5–6 ms, then waits
150 ms before arming fallback polling. IRQ input can run before that final
150 ms wait finishes. The journal does not currently timestamp the individual
steps. The driver has no reboot `.shutdown` callback, so retained peripheral
state across warm boots is plausible, but neither the source nor the logs
prove it caused K's failure. G/H and I's initial probe worked after reboots.

The strongest verified recovery remains I: HID publication at 28.099141 s,
normal creation power-down at 28.100022 s, zero headers on reopen and timeout
at 30.304365 s, then an ordinary daemon restart at 239.088593 s and successful
open at 239.297218 s. A further zero header preceded that successful open.
All 11 hashes in I's `touch-recovery/sha256.json` were independently verified.
This recovery included the normal open reset/power sequence, but no generic
full-reset escalation. See [the I review](TOUCH-STARTUP-20260922.md).

Historical audio notes describe a separate destructive GPIO54 codec-IRQ
collision causing reset storms and zero/FF SPI data. That explains why audio
must never claim GPIO54; it is not evidence that K's quiet, zero-IRQ failure
has the same cause. Increasing the dormant generic reset budget remains an
unjustified way to expose disruptive reset escalation.

## Descriptor bootstrap alternative

The current driver sends its known ten-byte descriptor request only after
processing `RESET_RESP`. A device already running without a queued reset
response could therefore wait indefinitely for a request the host never
sends. K's zero writes are compatible with that hypothesis, but do not prove
the firmware is in such a state. A descriptor request is not itself a reset
or power cycle.

Microsoft's published enumeration sequence reads the reset response before
requesting the descriptor. The public protocol 1.0 specification also uses
wire version 3, descriptor version `0x0300` and a 24-byte descriptor, while
this working SPX driver uses wire version 2, descriptor version `0x0100`
and a 30-byte descriptor. The published document therefore supplies useful
ordering context, not authority to replace this device's existing wire
format. No reviewed source documents SPX firmware accepting a descriptor
request before a reset response. Sources: [Microsoft enumeration guidance](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/plug-and-play-for-spi)
and [official protocol PDF, sections 6.1.1–6.1.2](https://download.microsoft.com/download/c/a/0/ca07aef3-3e10-4022-b1e9-c98cea99465d/HidSpiProtocolSpec.pdf).
The PDF and its hash are preserved in
`/var/tmp/spx-touch-protocol-review-20260922/`.

A future explicit experiment could send one extra known-format descriptor
request, initial probe only, after a failed poll and before any observed
startup progress. It would need a read-only, default-off boot option and a
private DMA-safe buffer. A normal reset-triggered request must remain allowed
if a genuine reset arrives later; suppressing it could discard the required
handshake. The extra request budget would not bound normal protocol traffic.

There is a scheduling issue to resolve before that experiment: a mutex around
descriptor writes does not stop a new IRQ from inserting a header read before
the bootstrap write and its body read afterward. A final state check only
narrows this race. Preventing it requires reserving the transport under
`input_lock`, deferring a racing IRQ read and draining it after the write,
with corresponding teardown and late-reset handling. Two serialized writes
can also leave two replies outstanding. Independent review reached the same
conclusion. This exceeds a metadata-only change and is not included in L.

## Smallest useful next trial

L should enable default-off, read-only `spi_hid.startup_diag=1` and retain
K's power/reset/IRQ/SPI behavior and audio stage 4. Log only a bounded set of
startup metadata: pinctrl/regulator operation results, IRQ arrival and gating,
pending/input-stage state, message status and actual length, report type,
reset/descriptor transitions, polling count and deadline summary. Do not dump
report bodies or enable blanket transfer tracing. Existing SPI-HID tracepoints
cannot be selected in K because `CONFIG_FTRACE` is disabled; some also expose
raw input data, so enabling the whole event family would be inappropriate.

The useful distinction is whether reset completes in software without any
IRQ, whether an early IRQ is discarded before power readiness, whether a
complete nine-byte transaction reaches the header validator, and whether
normal reset/descriptor work ever begins. If no IRQ or valid response follows
successful reset/power calls again, the next experiment can target that
sequence or the guarded descriptor bootstrap with explicit evidence. A single
successful L startup would not establish the intermittent issue is fixed.

## L implementation and offline checks

The diagnostic-only patch is implemented in `spi-hid-core.c` and its header.
`startup_diag` defaults to false and has module-parameter permissions 0444;
enable it for the fresh L boot with `spi_hid.startup_diag=1`. It cannot be
enabled later through the sysfs parameter. No descriptor bootstrap is included.
The existing workqueue choice is unchanged.

Every added record begins `startup-diag:`. A maximum of four startup windows
is observed: initial probe and up to three genuine open attempts. Early-return
opens of an already ready/creating device do not consume a window. Each window
allows 47 ordinary records and reserves its 48th record for an existing ready,
power-down or polling-timeout event. After that terminal event, logging stops
for the window. Total added output is at most 192 lines per device lifetime;
excess ordinary events increment a suppression count. A terminal record is
not guaranteed if another enumeration failure bypasses all three terminal
sites, for example after descriptor receipt cancels startup polling.

`begin value=1` identifies initial probe and `value=0` identifies an open.
`irq-request value` is the existing IRQ trigger flags; `irq value` is the
Linux IRQ number. `header` and `body` record existing message status in `ret`
and actual transferred byte count in `value` (the read approval is included).
`report value` is the report type after body-length validation, before dispatch.
The reset/descriptor counters count these accepted report-type observations,
not independent firmware health assertions. `descriptor-request value` is the
existing descriptor register address; `descriptor-sent ret` is the existing
write result. Other result events record existing function return codes.

Each record includes software power/startup/ready/stopping/IRQ-enabled state,
pending count and input stage, counters, suppressed count, current jiffies and
the stored deadline. A begin event can precede deadline initialization; the
arm event establishes the current window's deadline. No new device reads,
raw report-body dumps, commands, sleeps or IRQ configuration calls are added.
Logging can itself perturb timing, and software operation success is not a
measurement of electrical transitions.

The input lock is initialized earlier during probe so every new diagnostic
site can safely use it. IRQ/completion/poll/report sites call the already-locked
helper; process-context sites use its locking wrapper. With the parameter off,
helpers return before taking additional locks or changing diagnostic state.
An independent agent reviewed both the initial patch and final delta, including
the three ready sites outside `input_lock`, and found no blocking issue.

The target object compiled with the unchanged K configuration. `git diff
--check` passed; checkpatch reported zero errors and warnings on the final
properly formatted patch. A C harness extracts the actual diagnostic helpers
and runs with lock/assertion/logging mocks under undefined-behavior sanitization.
Five test groups passed: default-off inactivity; K's three-poll/zero-IRQ sequence
and actual-length reporting; early IRQ state and ready closure; flooding all
four windows while preserving terminal summaries and the 192-line limit; and
failed power-down closing diagnostics without altering power state. These
tests check the diagnostic code, not hardware recovery or kernel workqueue
interleavings. Evidence and a reproducible extractor are in
`/var/tmp/spx-touch-startup-diag-20260922/` with `SHA256SUMS`.

Frozen source SHA-256:

| File | SHA-256 |
| --- | --- |
| `spi-hid-core.c` | `fc0dd9640a3b99376f3ef2f73621df2ed742181b9a42751e03d8549b382d687a` |
| `spi-hid-core.h` | `31c5fcc5cfe847112101d06c7f7b77819a4173a1be20158e0d5daf63f65ccaa0` |
| Tested K `.config` | `e4b274603711c18713957d1b374b47ca05a9e583c60ff7dad6d2d6e6703ddf10` |
