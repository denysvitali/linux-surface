# PIO stage 7 step 6: enable, receive, and reactive capability response

**Proceed with this coherent fresh-boot diagnostic bundle only on a new build
containing the reviewed capability-retry fix. Do not reuse unmodified L for
PIO.** The review found a concrete error in the reachable response worker,
not a need to isolate every register into a separate boot. After correcting
that error, stage 7 step 6 is a justified next diagnostic under the user's
accepted experimental-boot risk. It covers controller enablement, continuing
RX FIFO consumption, and possible reactive REPORT_SATELLITE transmission.
It does not establish safe transport, a working soundcard, or a completed port.

O completed the [stage-5 step-2 access sequence](AUDIO-STAGE5-STEP2-20260922.md)
and a 611.87-second baseline. Its result file was checked with SHA-256
`14e612628f5d590ed590a108e78357d9cfa744f6599a89aecce11e66d01952e8`.
Root independently verified and archived O before applying the candidate.
O's observed zero status does not identify the separate, unlogged INT_CLR
write operand or prove acknowledgment of a pending interrupt.

## Baseline and the necessary correction

The offline checker verified current source before root applied the patch,
L/O archived source metadata and both archived NGD copies, the module
manifests, and the installed module. Baseline identities are:

| Item | Identity |
| --- | --- |
| Build commit | `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b` |
| L/O release | `7.3.0-rc2-spx-mainline-20260922l+` |
| Baseline NGD Git blob | `f7ca305ba9221bb43d08b39cf266bb2f4ba57e28` |
| Baseline source SHA-256 | `ac5977296b408d6096b67675f4e1ff1b1267a796bb3d57e55abf33cddb1a392b` |
| Baseline NGD module SHA-256 | `31df6e27e5f8058dd9ff33bf2320cd38dc5e5a6ea4049771b72179210b380f1d` |
| Baseline module GNU build ID | `06213c39d0aab6e3e6ea12b63f8223c8e32a97ca` |
| Reviewed candidate source SHA-256 | `364357cf6f2097185b66808dc59497cf6e6ed349fbdd9e8e679530581d298b0b` |
| Candidate patch SHA-256 | `062b76f30c15e89858afd9dd1038d42f152eb41388d8620c011190b6817075f4` |

In `qcom_slim_ngd_master_worker()`, the original `txn.rl = 8` ran once,
before `capability_retry`. `qcom_slim_ngd_xfer_msg()` decrements `txn->rl`
when encoding the length field. A NACK returns `-EIO` and retries the same
transaction without restoring its length. Subsequent frames therefore shrink;
repeated retries can also wrap the eight-bit field and violate the fixed
transport-buffer bound. The limit of ten retries does not avoid this defect.
`spx_pio_cap_retries=0` does not affect this worker's NACK retry loop.

The functional patch moves `txn.rl = 8` immediately after the retry label,
before every transfer. It preserves ten retries after the initial attempt,
the 10-ms retry delay, payload, destination, completion and error policy.
REPORT_SATELLITE is a source-referred user message: the core-message rewrite,
TID and element-code branches are excluded. The uninitialized `txn.tid` and
`txn.comp` fields are not read on this path; no extra transaction-field
changes are needed for this correction. A second hunk corrects the misleading
step-6 log from “observe-only soak (no TX)” to
“RX/reactive capability soak (no proactive TX)”.

Eight tests execute the actual fixed worker with a stub modeling the verified
length-consuming transfer contract: initial success, repeated NACK then
success, all eleven attempts exhausted, timeout, invalid-message and gated
errors, and successful ASLEEP/AWAKE state handling. They pass ASan/UBSan with
warnings treated as errors. An independent reviewer checked the exact two
hunks, byte-identical worker extraction and all eight results. These tests
exercise retry correctness, not actual MMIO, FIFO transport or firmware.
Strict checkpatch reports zero errors/warnings with commit-description and
Signed-off-by checks excluded for this local candidate. Root owns target
compilation, the distinct P build, and new artifact/module build-ID proofs.
The baseline identities above must not be used as P's output identities.

## Exact proposed P selectors

Use the new P release and complete matching kernel/module/DTB/initramfs set.
Relative to O's ordered command line, change the attempt marker to
`spx_attempt=20260922p`, replace stage 5 with stage 7, reset the irrelevant
stage-5 selector from 2 to 0, and append each new selector once:

```text
slim_qcom_ngd_ctrl.spx_probe_stage=7
slim_qcom_ngd_ctrl.spx_stage5_step=0
slim_qcom_ngd_ctrl.spx_stage7_step=6
slim_qcom_ngd_ctrl.spx_pio_mode=1
slim_qcom_ngd_ctrl.spx_pio_cap_retries=0
```

Keep stage-6 step 0 and every other runtime policy unchanged. Effective
`spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full`, `spx_pdr_auto_enable`,
`spx_qmi_bypass_lookup`, `spx_dump_windows`, `spx_pio_debug_reads`,
`spx_pio_tx_nowait` and `spx_pio_verbose` must remain N. Pin-after-QMI stays Y
with module refcount 1; poll-RX stays Y. Selection instance remains -1,
selection mode 0, power-response type -1, base override -1, DMA-mask bits 0,
and bypass node/port -1. SPI-HID startup diagnostics remain N/0444; preserve
the input retry policy and all logging/fallback policy. The parameters are
boot selectors, never instructions for live writes.

For exact step 6, the code returns before `qcom_slim_ngd_pio_wait_capability()`;
its proactive retry setting is therefore unused. Setting it to zero states
the intended no-proactive-message policy and also suppresses those kicks if
a different path unexpectedly calls the helper. It does not suppress received
MASTER_CAPABILITY handling, the worker's NACK retries, or runtime power-up.
`spx_poll_rx` controls the separate DMA-message-queue polling branch, not the
PIO thread. `spx_allow_full=N` blocks full controller registration, not the
reactive worker.

## Reachable synchronous boundary

Child probe sets runtime suspension and takes a no-resume usage reference.
With PDR auto-enable disabled it waits for QMI service discovery, takes
`ssr_lock`, and calls `qcom_slim_ngd_enable(true)`. That performs
SELECT_INSTANCE, pins the module, and completes `qmi_comp`. At stage 7,
PIO Y satisfies the caller's admission check despite DMA N. It calls
`qcom_slim_ngd_spx_stage7_probe()` and returns before runtime resume and
`slim_register_controller()`; the stage-5 and stage-6 bodies are bypassed.
Stage-7 steps 0–5 add no PIO transport action, so they are not prerequisite
BAM operations for this experiment.

The stage helper sends QMI ACTIVE with the response-type TLV omitted. With
window dumps disabled, before starting the PIO thread it performs eight
32-bit reads and three 32-bit writes:

| Sequence | Access |
| --- | --- |
| Initial four reads | Top-level version at `0x171c0000`, then child STATUS `+0x4`, CFG `+0x0` and RX_MSGQ_CFG `+0x8`, child base `0x171c1000`. The latter pair are log arguments with unspecified relative evaluation order. |
| Clear status | Read child INT_STAT `+0x14`, then write that unlogged sample to INT_CLR `+0x18`. |
| Disable device interrupts | Write zero to INT_EN `+0x10`. This path does not read INT_EN back. |
| Enable PIO | Read CFG, clear RX/TX message-queue bits 1/2, set ENABLE bit 0, log and write the resulting value. Other CFG bits are preserved. |
| Readback marker | Read CFG and INT_STAT; the pair's relative evaluation order is unspecified. |

There is no RX_MSGQ_CFG timeout write, BAM request/allocation/descriptor
operation, nonzero INT_EN write, codec reset or controller registration in
this path. The “pending interrupts cleared, INT_EN held disabled” marker
means the writes returned; it does not log the actual clear mask or establish
an INT_EN readback. The common baseline suggests CFG 0 becomes 1, but record
actual values. MMIO accesses have no individual timeout.

## Continuing RX and reactive TX

`qcom_slim_ngd_pio_start()` creates `spx_slim_pio`. The thread checks
`mmio_alive`, polls INT_STAT, and drains at most eight messages per pass,
sleeping 500–1500 microseconds between passes. With MMIO gated it sleeps
50 ms. A latched RX_MSG_RCVD causes a read of the first RX FIFO word at
child `+0x70`, then up to seven further words according to the frame length.
These reads pop FIFO data. It writes bit 30 to INT_CLR, executes a barrier,
and dispatches the received message. Three consecutive zero-length frames
disable further RX draining, with an error marker. Heartbeats read
INT_STAT/STATUS/CFG about every two seconds for the first 30 seconds only;
the thread continues after the heartbeats stop.

A source-referred MASTER_CAPABILITY queues `m_work` on the single-threaded
`ngd_master` workqueue. Duplicate queuing can coalesce pending work, but it
does not limit the total number of future worker invocations. The worker
sends REPORT_SATELLITE to manager address `0xff`, payload `d9 c5 01 01`.
For this message, the fixed length is 8 before encoding and 7 afterwards;
PIO transmits two words. `tx_lock` serializes transmission. PIO bypasses the
unallocated DMA ring and writes TX FIFO words at child `+0x30/+0x34`, then
executes a barrier. The first FIFO write has an unconditional pre-log.

TX can first clear stale sent/NACK/invalid bits. With nowait N it polls
INT_STAT for roughly 50 ms per attempt, sleeping 100–200 microseconds.
TX_MSG_SENT is acknowledged by clearing bit 31; NACK clears bit 25 and
returns `-EIO`; invalid/device/contention errors clear their sampled bits
and return `-EINVAL`; timeout returns `-ETIMEDOUT`. The worker retries only
`-EIO`, at most ten times after the first attempt. It does not invoke the
two-second TID-response wait or its extra RX-drain path for this non-TID
message. No per-access timeout protects a stalled MMIO read or write.

On successful TX in initial DOWN state the worker completes `reconf` and
checks for already registered child devices. This stage has registered none,
so that notification does not create codecs or an ALSA card. Step 6 returns
without waiting on `reconf`; there is no stage-7 capability-DONE marker for
the selected step. Repeated unsolicited messages can trigger further TX.
This experiment has no fixed global MMIO/message count or kernel-side
600-second stop; the existing userspace fallback controls the observation
window if the machine remains responsive.

## Lifecycle limits and evidence requirements

The parent Linux IRQ is enabled independently of NGD_INT_EN. The suspended
child normally causes the ISR to return before register access. If runtime
state changes, PIO mode's ISR can read/log INT_STAT but returns without
clearing it. The PIO thread itself is intentionally not blocked by runtime
suspension; it gates on `mmio_alive`. Expect child `runtime_status=suspended`,
active time 0 and control auto throughout the staged experiment.

The runtime-resume callback bypasses stage selection and can execute full
power-up, so never force it. Module pinning prevents ordinary unload; it
does not make cleanup safe. QMI exit gates `mmio_alive` before releasing its
power vote, but that boolean is not a synchronization barrier that drains
all in-flight MMIO. The staged controller also remains in software DOWN
state: the PDR/SSR DOWN handler's `state != DOWN` test can skip cleanup and
leave polling enabled after an unexpected remote-processor shutdown. PDR
auto-enable N suppresses UP reenable only. These are material existing
lifecycle limitations, not evidence of validated crash recovery.

Removal cancels the master worker before stopping the RX thread, leaving a
possible requeue interval; child removal frees its NGD data and cannot be
used as a live recovery procedure. Stage-7 QMI and thread-start errors can
also be logged while the probe ultimately reports success. A stop/enable-done
marker alone therefore does not pass this test. Do not unload/rebind,
restart ADSP, force suspend/resume, change parameters or power/control,
or unbind/rebind live MSM display components. Those paths need separate
hardening before broader deployment; they do not require adding unrelated
register-isolation boots to this deliberately retained diagnostic session.

Require exact new loaded module/build-ID proof, effective parameters, pinning
and QMI response success, followed by the following markers and actual values:

```text
SPX: stage 7 controlled power-up step=6
SPX: stage 7 QMI power-on acked by ADSP
SPX: stage 7 reads done ver=0x202 status=0x40c cfg=0x0 rx_msgq=0x0
SPX: stage 7 PIO: pending interrupts cleared, INT_EN held disabled
SPX: stage 7 PIO writing NGD_CFG=0x1 (enable, msgqs off)
SPX: stage 7 PIO NGD_CFG readback=0x<actual> int_stat=0x<actual>
SPX: stage 7 PIO RX/reactive capability soak (no proactive TX); heartbeat logs follow
SPX: stopping after controlled stage 7 before SLIM registration
SPX: child probe: enable done
SPX: PIO poll thread started
SPX: PIO heartbeat int_stat=0x<actual> status=0x<actual> cfg=0x<actual>
```

Thread, heartbeat and reactive-worker markers can interleave with the
caller's final lines. Preserve failures/deviations, not only expected strings.
Record the thread's continued presence, IRQ counts, runtime state and the
complete timestamped journal. With verbose N there is no log for every RX
frame or successful TX. `SLIM SAT: Rcvd master capability` establishes worker
entry; the first FIFO marker establishes reaching the write boundary, not
successful delivery. With the step-6 return no capability-DONE line is
expected. A later STATUS with LADDR bit 1 set supports enumeration, not
proof of every frame, codec communication or audio. Absence of RX/TX markers
may mean a quiet master; do not manufacture traffic or enable verbose/live
debug accesses to turn an inconclusive observation into a pass.

Collect faults, NACK/error/timeout messages, zero-length RX shutdown,
unexpected IRQs, PDR/SSR/remoteproc changes, DPU timeouts, input outcome,
graphics/EGL and networking over at least 600 seconds. No soundcard is
expected. Preserve known-good as the persistent default, verify source,
configuration, new artifacts, recovery files and runtime policies, recheck
boot ID and pending GRUB/EFI selection, and select P once. Arm/verify any
replacement fallback before stopping the original timer; hash the complete
result before stopping fallback or choosing the next experiment. Existing
authorization covers the boot; early-hang automatic recovery is unvalidated.

## Historical support and frozen offline evidence

The [6.18 findings](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L1176)
record a stage-7 **step-7** PIO trial with a different module hash, QMI bypass,
verbose RX output, unsolicited MASTER_CAPABILITY, a first-attempt successful
REPORT_SATELLITE, STATUS changing `0x40c -> 0x240e`, and a two-minute soak.
No proactive kick was needed. This supports the CFG/FIFO/reactive-exchange
direction but is not evidence for P's exact build or a 600-second mainline
result. The same history records delayed resets after nonzero INT_EN even
after disable readback, and a BAM-start freeze requiring manual recovery.
DMA and nonzero INT_EN remain excluded. Later codec/playback results use
broader hardware operations and do not justify enabling them in P.

The baseline stage-7 helper and master worker matched the current sibling
6.18 source byte-for-byte at review time; that does not prove the historical
successful module contained the later retry correction. Evidence is frozen
under `/var/tmp/spx-audio-pio-stage7-step6-review-20260922/`: 14 hashed files
include baseline/candidate sources, patch, harness/binary/results, checker,
module notes, historical excerpt and independent review. `sha256.json` SHA-256
is `f2590b122839a2e602bd232de962ac3c0b920cba6569348fac8976936d8f188a`.
The checker was run before root changed the working source and is a recorded
baseline check, not a command to replay against the patched tree. Archive
this directory with P; no live device or boot selection was changed by this
review.
