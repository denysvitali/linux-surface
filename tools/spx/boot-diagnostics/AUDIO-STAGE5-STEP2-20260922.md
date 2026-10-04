# Audio stage 5 step 2: isolated interrupt-status acknowledgment

**The recommended next audio experiment is a fresh stage-5 step-2 boot on
the unchanged L artifacts, after independent verification of N's completed
result.** It advances the interrupt-status clear used by the eventual PIO
path. It does not enable transport. N's result records 616.08 seconds and
the expected step-0 no-writes stop with INT_STAT=0 and INT_EN=0. Its result
file SHA-256 was checked as
`d56fc12297222aa12f182f292d03cdb9c0a3b7b722e615cfa062e8969018d092`;
the full archive review remains separate. This offline review establishes
no mainline step-2 hardware result.

The [earlier stage-5 plan](AUDIO-STAGE5-20260922.md) preferred step 1 as a
general isolated-write diagnostic, while explicitly permitting a separate
review to omit it for PIO. This review takes that narrower route: full
[PIO power-up skips the RX timeout write](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2216),
then clears pending interrupt status. The cases are noncumulative; step 2
does not execute step 1. Skipping the timeout test makes no claim that its
write is safe or unnecessary for a different, DMA-based transport.

The [historical 6.18 findings](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L350)
record step 2 completing cleanly, but step 3 causing a delayed reset after
`INT_EN=0xfe000000` and successful disable readback. That history supports
the chosen diagnostic direction, not a mainline result or a mechanism for
the reset. Step 3 and nonzero INT_EN writes remain excluded. The subsequent
[6.18 PIO exchange](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L1176)
does not justify skipping fresh mainline boundaries or the 600-second window.

## Exact source and artifact provenance

The checker reverified the current source against L's build commit, L/N
archived source metadata and module manifests, both archived NGD copies,
and the installed module. The stage helper remains byte-identical to the
current sibling 6.18 helper. These are offline file checks, not an additional
inspection of the loaded module or live registers.

| Item | Identity |
| --- | --- |
| Build commit | `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b` |
| Release | `7.3.0-rc2-spx-mainline-20260922l+` |
| NGD Git blob | `f7ca305ba9221bb43d08b39cf266bb2f4ba57e28` |
| NGD source SHA-256 | `ac5977296b408d6096b67675f4e1ff1b1267a796bb3d57e55abf33cddb1a392b` |
| NGD module SHA-256 | `31df6e27e5f8058dd9ff33bf2320cd38dc5e5a6ea4049771b72179210b380f1d` |
| Module GNU build ID | `06213c39d0aab6e3e6ea12b63f8223c8e32a97ca` |

Reuse the complete L kernel/module/DTB/initramfs set already used by N.
The ordered command-line delta is a new attempt marker and exactly one
replacement of `slim_qcom_ngd_ctrl.spx_stage5_step=0` with
`slim_qcom_ngd_ctrl.spx_stage5_step=2`. Keep stage 5, pin-after-QMI 1,
`spi_hid.startup_diag=0`, the 600-second window and every other token.
No source/configuration change or live module-parameter write is proposed.

## Exact synchronous access boundary

SELECT_INSTANCE and module pinning precede the stage helper's QMI ACTIVE
request (`pm_req=2`, optional response-type TLV omitted). QMI changes firmware
state. With window dumps disabled, the successful synchronous helper path
performs **nine 32-bit MMIO reads and one 32-bit MMIO write**:

| Sequence | Address | Operation and evidence |
| --- | --- | --- |
| Common read 1 | `0x171c0000` | Top-level version read; version marker. |
| Common read 2 | `0x171c1004` | Child STATUS read. |
| Common read 3 | `0x171c1000` | Child CFG read. |
| Common read 4 | `0x171c1008` | RX_MSGQ_CFG read; child marker. |
| Common reads 5/6 | `0x171c1014`, `0x171c1010` | INT_STAT and INT_EN reads used by the combined stage-5 marker. |
| Case-2 read A | `0x171c1014` | INT_STAT sampled for the pre-clear marker. |
| Case-2 read B | `0x171c1014` | INT_STAT sampled again as the write operand. This sample is not logged. |
| Case-2 write | `0x171c1018` | Write sample B to INT_CLR. |
| Case-2 read C | `0x171c1014` | Read INT_STAT for the final marker. |

The [common source reads](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2542)
execute in the order above through read 4. The last two common reads are
arguments of one `dev_info()` call, so C does not specify their relative
order. The [case-2 sequence](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2580)
then executes A, B, the write and C in that order and returns from stage 5.
No timeout, CFG, INT_EN, FIFO or BAM write is part of this synchronous path.
`spx_allow_dma=N`, `spx_allow_int_en=N` and `spx_allow_full=N` do not block
this case's write; the selected step itself authorizes it.

**The pre-clear marker is not a record of the actual write mask.** Firmware
can change status between reads A and B. The final “readback” is a read of
INT_STAT, not INT_CLR, and does not verify the data written or establish
which latched bits were acknowledged. Even zero in every printed status
cannot prove that unlogged sample B was zero. If the actual operand was
zero, completing that write would not exercise acknowledgment of a pending
bit. Describe a zero-observation result as completion of the isolated access
sequence with zero observed status, not proof of working interrupt handling.

A nonzero or changed final status must be preserved and reviewed; it can
reflect remaining or newly asserted status. Do not repeatedly clear it or
induce an interrupt to strengthen the test. If exact write-mask attribution
becomes necessary, a separately reviewed source change must sample once and
log/write the same value. The current unchanged module does not do that.
`readl_relaxed()` has no per-access timeout; readback completion does not
prove freedom from delayed resets.

## Required boot evidence and retained guards

Require the successful pin/QMI acknowledgment markers, then the following
sequence. The version and child values are the established L/N baseline;
preserve deviations. Each status placeholder means the actual sampled
value, not a requirement to manufacture zero:

```text
SPX: top-level NGD raw version register=0x2020000 ver=0x202
SPX: child NGD read status=0x40c cfg=0x0 rx_msgq_cfg=0x0
SPX: stage 5 controlled write step=2 int_stat=0x<common> int_en=0x0 rx_msgq_cfg=0x0
SPX: stage 5 step 2: clearing pending INT_STAT=0x<A>
SPX: stage 5 step 2: INT_STAT readback=0x<C>
SPX: stopping after staged hardware probe (spx_probe_stage=5)
SPX: child probe: enable done
```

All effective state requirements from the [exact-L review](AUDIO-STAGE5-L-REVIEW-20260922.md)
remain, except step 2 replaces step 0: stage 5, pin Y, refcount 1; DMA,
interrupt-enable, full-registration, PIO, PDR auto-enable, QMI bypass,
window-dump, PIO debug/nowait/verbose flags all N; stage-6/7 steps 0;
instance -1, mode 0, power-response type -1, NGD offset -1, DMA-mask bits 0.
Poll RX stays Y but this stage starts no poller. Child runtime state must
remain suspended, active time 0, control auto. Input diagnostics remain
N/0444 with no startup-diag records. No ALSA soundcard is expected.

The parent Linux IRQ is already enabled at
[probe line 3190](../../../drivers/slimbus/qcom-ngd-ctrl.c#L3190), independently
of NGD_INT_EN. After QMI makes MMIO live, the suspended-child
[ISR barrier](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1584) is expected to
prevent asynchronous register access. A changed runtime state could allow
the ISR to read/clear status. The [runtime-resume callback](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2500)
can invoke full power-up outside stage selection; the disabled PDR option
only blocks the [UP auto-enable branch](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2893),
not every DOWN/cleanup path. Counts above therefore describe the successful
synchronous stage path, not an unconditional upper bound on all activity.

Do not force runtime resume, change power/control, advance parameters live,
unload/rebind the pinned stack, restart ADSP, or rebind live MSM components.
Observe actual uptime of at least 600 seconds and independently record
input, graphics/EGL, Wi-Fi, remote processors, IRQs and fault/reset evidence.
An input failure remains a failed component result. Preserve known-good as
the persistent boot default, select the new attempt once, recheck boot ID
and pending GRUB/EFI selection, and rehash all artifacts and runtime policies.
If extending observation, arm and verify the replacement fallback before
stopping the original timer. Archive and hash the result before stopping
the fallback or choosing another experiment. Existing authorization covers
these boots; automatic recovery from an early MMIO hang remains unvalidated.

## Later PIO scope and the smallest isolated source candidate

This section is a future source-review outline, not a boot recommendation
or an implemented change. No later-stage result is established here.

No existing selector isolates a zero write to INT_EN. The smallest existing
bundle that advances past INT_CLR without CFG/FIFO or DMA operations is
[stage 6 step 0](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2618): five reads
and three writes, including the unnecessary RX_MSGQ_CFG timeout write,
INT_CLR and INT_EN=0. Its no-DMA return is at
[line 1475](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1475). It is not selected
by this plan and is not interchangeable with stage-5 step 0 or step 2.

If another isolated register boundary is desired, the smallest PIO-focused
source candidate is a new explicit stage-5 case
that writes **only zero** to INT_EN, reads the same register back, logs both
boundaries and stops with the module pinned. It must preserve the current
default and existing cases, retain the nonzero-mask exclusion, and undergo
source/build review before any new fresh-boot trial. Successful INT_CLR
access does not establish this next register's behavior. A later isolated
CFG-enable case would need to stop before starting RX dispatch or any
message worker; each added write and read requires its own reviewed scope.

In particular, existing [stage 7 PIO step 6](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2318)
is **not a strict no-TX soak**, despite its marker. Steps 0–5 only repeat
four reads and return; step 6 clears INT_STAT, writes INT_EN=0, enables CFG
with message-queue bits cleared, then starts the RX thread. That thread
[reads/pops FIFO and clears RX status](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1062)
and dispatches received messages. An unsolicited MASTER_CAPABILITY
[queues the master worker](../../../drivers/slimbus/qcom-ngd-ctrl.c#L897),
which [sends REPORT_SATELLITE](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2443)
through the [TX FIFO](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1012).
`spx_pio_cap_retries=0` suppresses only proactive kicks; `spx_allow_full=N`
does not block this reactive exchange. Thus the present stage-7 step-6
path cannot serve as an isolated CFG-only or no-message test. Any future
PIO plan must address that exact asynchronous path before using its label
to define the experiment. An explicitly scoped stage-7 step-6 bundle covering
CFG enablement, RX consumption and possible reactive TX could instead be
considered after a separate review and completed step-2 result. A new source
case is needed only if those operations must be isolated; this review does
not require such a change before every future PIO experiment.

Offline evidence is in `/var/tmp/spx-audio-stage5-step2-review-20260922/`:
five files cover the checker, source snapshot, module notes, historical
excerpt and result. All hashes were verified. `sha256.json` SHA-256 is
`33e8c11f81a4d0b20f14f1738dafa659e00257db46c7602aae82e204fdbda33c`.
An independent source-path review agreed on the access count and exposed
the stage-7 reactive-TX limitation. No live hardware, boot selection,
deployed artifact or kernel source was changed by this review.
