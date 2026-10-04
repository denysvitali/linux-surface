# SPX audio: prospective stage-5 reads and isolated writes

The smallest next audio experiment is **stage 5, step 0**, on a fresh boot
after K's touch change and unchanged stage-4 audio baseline are validated
and archived. It adds two explicit MMIO reads, then stops. This document
does not stage an entry, change parameters, perform live audio access or
claim that any stage-5 mainline experiment has passed.

[J's final result](RESULT-20260922j.md) establishes stage 4 through 644.15
seconds, with 274 evidence hashes independently verified. Its version and
child STATUS/CFG/RX_MSGQ_CFG values were `0x02020000`, `0x40c`, `0`, `0`.
J failed touch publication before IPTSD startup. K addresses that separate
failure while retaining stage 4; complete its own observation and result
before considering the audio progression here. Do not mix an unvalidated
touch kernel with a new audio stage.

## Reviewed source and historical scope

The current [NGD driver](../../../drivers/slimbus/qcom-ngd-ctrl.c) blob is
`f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`. Its complete
`qcom_slim_ngd_spx_stage_probe()` and IRQ-handler functions are byte-for-byte
identical to the current sibling 6.18 source, whose whole-file blob is
`d9ad4a452dd37e9def5cc5de8de9891dfcd4f9f7`. This source comparison supports
the access description; it does not transfer a hardware result between
kernels, firmware state or boots.

The [6.18 controlled-step findings](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L350)
record step 0 clean, step 1 writing/readback `RX_MSGQ_CFG=0x10000` clean,
and step 2 clearing interrupt status clean. Step 3 wrote `INT_EN=0xfe000000`,
read it back, immediately wrote zero and read zero back, **then reset**.
The journal preserved the disable-readback marker; no pstore or normal
Linux crash signature was recorded. That is strong evidence against
repeating INT_EN enablement. The proposed interrupt/firmware mechanism
remains an interpretation, not a proved explanation of the reset.

The later [PIO result](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L1176)
established capability exchange without BAM or NGD interrupt enablement.
Its two-minute observation notes that the preceding delayed resets occurred
within about 60 seconds. This does not reduce the current minimum 600-second
observation requirement or justify a direct jump to PIO/full bring-up.
The [later speaker handoff](../../../../linux-surface-kernel/PROGRESS.md#L3)
still describes amplifier de-enumeration during streams; transport success
must not be presented as complete speaker support.

Earlier suggestions to enable interrupts or run DMA in
[the June 10 note](../../../../linux-surface-kernel/docs/spx-audio-post-reboot.md)
precede those later findings and do not govern this plan. Its warning about
the inverted historical QMI ACTIVE/INACTIVE encoding also limits older
power-state interpretations. Keep the current ACTIVE request (`pm_req=2`,
optional response-type TLV omitted), and never access the historically
wedging alternate child window at `0x171c2000`.

## Parameters and guards for the first prospective boot

Reuse the validated K artifacts without further kernel/config/DTB changes.
Give the experiment a new attempt ID; the functional audio delta from K is
stage 4 to 5, with step 0 explicitly selected:

```
slim_qcom_ngd_ctrl.spx_probe_stage=5
slim_qcom_ngd_ctrl.spx_stage5_step=0
slim_qcom_ngd_ctrl.spx_pin_after_qmi=1
```

These are prospective boot parameters, not commands to change a live module.
Verify all effective values after boot:

| Parameter/state | Required value |
| --- | --- |
| `spx_probe_stage`, `spx_stage5_step` | 5, 0 |
| `spx_pin_after_qmi`, module refcount | Y, 1 |
| `spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full` | N, N, N |
| `spx_pio_mode`, `spx_pdr_auto_enable`, `spx_qmi_bypass_lookup` | N, N, N |
| `spx_dump_windows`, `spx_pio_debug_reads`, `spx_pio_tx_nowait`, `spx_pio_verbose` | N, N, N, N |
| `spx_stage6_step`, `spx_stage7_step` | 0, 0 |
| `spx_select_instance`, `spx_select_mode`, `spx_power_resp_type` | -1, 0, -1 |
| `spx_ngd_base_offset`, `spx_dma_mask_bits` | -1, 0 |
| `spx_poll_rx` | Y; stage 5 does not start a poller |
| Child runtime status / active time / control | suspended / 0 / auto |

Preserve the existing display, QRTR, network, input and logging settings;
hash all runtime differences. Keep `spx-known-good` persistent, select each
new trial once and preserve/hash source/config, payloads, modules, recovery
artifacts and logs. Recheck boot ID and pending selection immediately before
reboot. Do not repeat a failed image without first collecting its result.

## Exact stage-5 access boundary

As in J, SELECT_INSTANCE pins the module, and the ACTIVE QMI transaction
precedes the staged probe. That firmware request is a mutation even when
the explicit MMIO portion only reads. The window-dump helper must stay
disabled. All listed MMIO accesses are 32-bit.

| Access | Physical address | Source line(s) | Stage-5 step 0 behavior |
| --- | --- | --- | --- |
| Top-level version | `0x171c0000` | 2542 | Read, then version log. |
| Child STATUS | `0x171c1004` | 2548 | Read. |
| Child CFG | `0x171c1000` | 2549 | Read. |
| Child RX_MSGQ_CFG | `0x171c1008` | 2550 | Read, then combined child log. |
| Child INT_STAT | `0x171c1014` | 2562 | New read used by the combined stage-5 log. |
| Child INT_EN | `0x171c1010` | 2563 | New read used by the combined stage-5 log. |

The first four reads execute in the displayed order. **The source does not
specify the relative order of the last two reads:** both are arguments of
the same `dev_info()` invocation. The combined stage-5 log appears only
after both return. An interrupted boot cannot identify which of those reads
stalled from that marker alone; do not infer a sequence from argument order.
The logged `rx_msgq_cfg` at this point is the earlier saved value, not a
third new read.

[Lines 2557–2569](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2557) also reset
the software completion and print `stage 5 step 0: no writes`. The helper
returns at line 2615; the caller emits the explicit stage-5 stop at lines
2695–2697, and child probe reaches `enable done`. Thus step 0 performs six
explicit register reads and **no explicit MMIO writes** on this synchronous
path. It neither enables the child nor registers the SLIM controller.
No soundcard is expected, and the delayed loader's soundcard-wait failure
remains an expected limitation of the stage.

Record INT_STAT exactly without assuming it must be zero. Expect INT_EN to
be zero for the intended disabled baseline, but neither the N parameter nor
the prior CFG value proves that register value. Preserve a nonzero INT_EN
as an unexpected result; do not write zero live to make the test pass.

## Isolated write steps, after the read-only boundary is validated

The stage-5 switch is **not cumulative**. Each fresh boot executes the six
common reads above and exactly one selected case. Step 2 does not perform
step 1 first. `spx_allow_dma=N`, `spx_allow_int_en=N`, `spx_allow_full=N` and
`spx_pio_mode=N` must remain set for both cases; these flags do not prevent
the case-1 or case-2 write.

| Selected case | Additional accesses after the common log | Persisted effect and evidence limit |
| --- | --- | --- |
| Step 1, lines 2570–2579 | Log saved `rx_msgq \| 0x10000`; write it to RX_MSGQ_CFG `0x171c1008`; read RX_MSGQ_CFG and log readback. | One write and one new read. With initial zero, expected readback is `0x10000`. The value is not restored before stopping; no transport operation follows. |
| Step 2, lines 2580–2589 | Read INT_STAT `0x171c1014` for the pre-write log; read INT_STAT again as the value for a write to INT_CLR `0x171c1018`; read INT_STAT a third time for the final log. | One write and three new reads. INT_CLR is not read back; the final read observes status after acknowledgment. The value printed before the write can differ from the value actually written. |

Step 1 is the strongest justified **first isolated-write diagnostic** after
step 0: it targets a register already read successfully in J, ORs only the
named timeout bit into its saved value, provides a same-register readback,
and has a clean historical 6.18 observation. Require the expected initial
state, planned value, matching readback, explicit stop and at least 600
seconds of continued operation. A readback alone does not establish safety
from delayed faults, transport correctness or a hardware timeout duration.
Do not infer timeout units from the constant name. Do not restore the
original value live; any follow-up uses a fresh boot.

This is optional diagnostic evidence, **not a prerequisite of eventual PIO
transport**: the current [PIO power-up branch](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2216)
expressly skips the RX_MSGQ_CFG timeout write. Testing that write is justified
only as a deliberate isolated-write boundary, not as a reason to proceed
into BAM. Any later decision to omit it in favor of the PIO-relevant
INT_CLR test must state that scope explicitly and retain a separate step-0
result and a separately reviewed fresh-boot write experiment.

Step 2 changes latched interrupt state. It writes whichever status bits are
present at its second case-specific read; its pre-log cannot prove that
exact write mask. A zero status before/after a zero write proves only that
the access completed, not that acknowledgment of a pending interrupt works.
A changed or nonzero final status must be preserved and interpreted, not
repeatedly cleared. If exact write-mask attribution becomes necessary,
prepare and review a source change that samples once and logs/writes that
same value; do not describe the current code as doing so.

**Step 3 remains excluded.** Its allow flag must stay N. The historical
delayed reset after a successful disable readback defeats any assumption
that a short enable/disable pulse is harmless. Stage 6 is also outside this
plan: even step 0 executes timeout, INT_CLR and zero-to-INT_EN writes before
its DMA helper, so it is not interchangeable with stage-5 step 0. Stages
7/8, PIO, DMA, codec enumeration and playback require separate source and
evidence review; no unsupported jump is proposed here.

## Asynchronous paths, observation and limits

The parent Linux IRQ is enabled at line 3190, after registration with
`IRQF_NO_AUTOEN`. Child probe sets runtime-suspended state and takes a
no-resume reference at lines 3014–3018. The stage-5 path does not change that
state. After the QMI acknowledgment sets `mmio_alive`, the
[runtime-suspended ISR check](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1589)
remains the expected barrier. If the state changes, the handler can read
INT_STAT and write INT_CLR regardless of the diagnostic step. The
[runtime-resume callback](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2500)
can call power-up, whose writes precede later setup guards.

Never force runtime resume, change `power/control`, escalate parameters live,
unload/rebind the pinned audio stack or restart ADSP. Never unbind/rebind
live MSM display components. Pinning and disabled parameters are not proof
that every asynchronous or cleanup path is unable to access hardware.

For each prospective step, require the QMI/pin/version/child markers, the
exact step-specific markers, explicit stage-5 stop and child `enable done`.
Observe actual uptime of at least 600 seconds with intact guards, suspended
child, pinned module, running remoteprocs, desktop/EGL, Wi-Fi and the input
outcome recorded independently. Preserve all IRQ, ADSP, modem, GPU, oops,
panic, reset and unexpected later-stage evidence. Input failure must remain
a failed component result even if the audio observation succeeds.

Keep periodic logging and the established bounded fallback. If extending
observation, first arm a replacement at least 20 minutes away, verify it
active, then stop the original timer. Archive and hash the result before
stopping the replacement or choosing the next experiment. A userspace timer
does not guarantee recovery from a stalled MMIO access; `readl_relaxed()`
has no per-access timeout here. Existing user authorization covers boots
that may need a manual power cycle. No automatic early-hang recovery has
been established by this review or J's retained mainline session.
