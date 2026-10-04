# SPX audio: proposed child-register-read stage 4

This is a fresh-boot experiment following the **completed and archived
trial I stage-3 result**: I passed its audio/graphical observation at 612.76
seconds, with 270 archive hashes independently verified. Touch startup failed
and was recovered by one daemon restart; see [I's result](RESULT-20260922i.md).
No stage-4 success is assumed here. The [stage-3 plan](AUDIO-STAGE3-20260922.md) describes
the preceding top-level version read. No live hardware access was performed
for this review.

Stage 4 would reuse G's unchanged kernel, 187 modules, DTB and initramfs,
release `7.3.0-rc2-spx-mainline-20260922g+`, and change only the effective audio
stage from 3 to 4 in a new attempt. Its synchronous probe adds three child
register reads, then stops. It does not establish SLIMbus messaging, codec
enumeration, a soundcard or playback.

## Completed prerequisite and pending dependency

[H's completed stage-2 result](RESULT-20260922h.md) records an ACTIVE power
response with `result=0x0 error=0x0` at 27.884195 seconds, the explicit stop at
27.890560 seconds, and continued operation through the finalized 865.10-second
result. Its 266 archived hashes were verified. The child remained suspended,
the module was pinned and the diagnostic guards remained intact.

That result establishes the bounded power handshake. Before stage 4, I must
also complete the top-level read, explicit stage-3 stop and at least 600
seconds of continued system/ADSP observation, with source/artifact provenance
and logs archived and verified. A matching historical value, an early log or
a running desktop alone does not satisfy this dependency.

## Parameters and artifact scope

Use a distinct attempt and one-shot entry, preserve `spx-known-good` as the
persistent default, and retain the existing loader, `spx_gpu_profile=skip`,
600-second observation policy, QRTR rollback, GPU corrections, CMAC and
in-tree UINPUT. No rebuild, DTB or kernel configuration change is part of this
comparison. After I's baseline was archived, the bounded IPTSD retry policy
was installed without restarting the healthy daemon. J must record and hash
that userspace difference; a recovered service is not a clean startup pass.
See [the touch review](TOUCH-STARTUP-20260922.md). Record reused hashes from
[G preparation](PREPARED-20260922g.md).

The only functional command-line change from I would be:

```
slim_qcom_ngd_ctrl.spx_probe_stage=4 slim_qcom_ngd_ctrl.spx_pin_after_qmi=1
```

Verify the effective parameters after boot:

| Parameter/state | Required value |
| --- | --- |
| `spx_probe_stage`, `spx_pin_after_qmi` | 4, Y |
| `spx_select_instance`, `spx_select_mode`, `spx_power_resp_type` | -1, 0, -1 |
| `spx_ngd_base_offset` | -1; no alternate-window experiment |
| `spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full` | N, N, N |
| `spx_pio_mode`, `spx_pdr_auto_enable`, `spx_qmi_bypass_lookup` | N, N, N |
| `spx_dump_windows`, `spx_pio_debug_reads`, `spx_pio_tx_nowait` | N, N, N |
| Stage 5/6/7 substeps | 0, 0, 0 |
| `spx_poll_rx` | Y, unchanged; stage 4 does not start polling |
| Child runtime status, module refcount | suspended, 1 |

Do not raise the stage live, force runtime resume, change `power/control`,
unload/rebind the audio stack or restart ADSP. The pin prevents ordinary
module unload; it does not prevent every error cleanup or firmware change.

## Exact synchronous access path

The reviewed [qcom-ngd-ctrl.c](../../../drivers/slimbus/qcom-ngd-ctrl.c) blob
is `f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`.

The enable path at lines 2653–2697 performs SELECT_INSTANCE and pins the
module, then calls `qcom_slim_ngd_spx_stage_probe()`. Its line 2532 sends the
ACTIVE QMI power request (`pm_req=2`, optional response-type TLV omitted).
This firmware request remains a mutation; “read-only” describes the explicit
MMIO portion, not the whole experiment.

After the power acknowledgment, line 2540 calls the window-dump helper. Its
[line-2090 guard](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2090) must return
with `spx_dump_windows=N`; enabling it would add unplanned reads. The helper
then performs these 32-bit `readl_relaxed()` accesses in source order:

| Order/source line | Register | Offset | Physical address | Historical value |
| --- | --- | --- | --- | --- |
| 1 / 2542 | Top-level version | parent + `0x0` | `0x171c0000` | `0x02020000`, decoded `0x202` |
| 2 / 2548 | Child `NGD_STATUS` | child + `0x4` | `0x171c1004` | `0x40c` |
| 3 / 2549 | Child `NGD_CFG` | child + `0x0` | `0x171c1000` | `0x0` |
| 4 / 2550 | Child `NGD_RX_MSGQ_CFG` | child + `0x8` | `0x171c1008` | `0x0` |

The parent DT resource is
[`0x171c0000`, size `0x2c000`](../../../arch/arm64/boot/dts/qcom/sc8180x.dtsi#L3788).
The child has [DT `reg=1`](../../../arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi#L33).
Driver lines 257–260 specify offset/size `0x1000`; lines 2977–2978 calculate
`base + id * offset + (id - 1) * size`, placing child 1 at `0x171c1000`.
The register offsets are defined at driver lines 28–35.

Lines 2551–2553 emit one combined child-values log **after all three child
reads**. Lines 2554–2555 then return, and lines 2695–2697 emit the explicit
stage-4 stop. This path performs no MMIO write. It returns before the stage-5
INT_STAT/INT_EN reads, controlled writes, DMA, PIO and controller registration.
It does not access the alternate `+0x2000` window.

## IRQ, runtime PM and historical limits

Child probe [lines 3014–3018](../../../drivers/slimbus/qcom-ngd-ctrl.c#L3014)
sets runtime-suspended state and takes a no-resume reference. The staged
helper does not mark the child active or invoke runtime resume. QMI power
acknowledgment sets `mmio_alive=true` at lines 792–794, but does not prove AP
register accessibility or every clock/power-domain state.

Parent probe requests the Linux IRQ with `IRQF_NO_AUTOEN` at lines 3131–3133
and enables it at line 3190. The ISR's
[runtime-suspended check](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1589)
remains the expected barrier after acknowledgment. If runtime state changes,
the ISR can read child INT_STAT (`0x171c1014`) at line 1606 and write INT_CLR
(`0x171c1018`) at line 1628. The
[runtime-resume callback](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2500)
can enter power-up, whose lines 2220–2232 include RX_MSGQ_CFG, INT_CLR and
INT_EN writes outside the stage-4 early return. Disabled diagnostic options
are not a universal write prohibition across these other callbacks.

The sibling 6.18 [June findings, lines 306–312](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L306)
record the four values above and a successful stage-4 child read. These are
historical observations, not a register specification or proof for this
mainline boot. Zero is historically expected for CFG and RX_MSGQ_CFG; do not
apply the stage-3 zero-version rejection indiscriminately to these registers.
A changed STATUS value must be preserved and investigated rather than
silently accepted or rewritten to match history.

That history also records delayed resets after briefly writing INT_EN,
including a completed disable readback, at lines 350–365. The
[post-reboot note](../../../../linux-surface-kernel/docs/spx-audio-post-reboot.md#L3)
documents correction of an inverted ACTIVE/INACTIVE enum and warns against
relying on older power-collapse interpretations. Its line 60 records a
lockup from the alternate `0x171c2000` window. These observations explain the
narrow boundary; they do not make the proposed reads universally safe.

`readl_relaxed()` has no timeout here. A register read can stall if its target
is inaccessible, and a userspace return timer does not guarantee recovery.
The existing user authorization covers experimental boots that may need a
power cycle; automatic recovery remains unvalidated. Suspend/resume remains
a separate experiment.

## Collection and bounded result criteria

After I's completed result is verified, prepare the new attempt using the
established one-shot workflow. Recheck current boot ID, pending selection,
recovery hashes and reused artifacts immediately before reboot. Preserve
early and periodic logging and the bounded-return procedure; explicitly
record whether the session returned or was retained after verification.

Require the SELECT_INSTANCE/pin markers, ACTIVE response with zero result
and error, `staged QMI power request acked`, the top-level version, the
combined child-values log, `stopping after staged hardware probe
(spx_probe_stage=4)` and child `enable done`. Record all values exactly.

Observe at least 600 seconds of system and ADSP progress. Verify guards,
module refcount, suspended child state, remoteprocs, desktop/EGL, input and
Wi-Fi. Preserve unexpected IRQ, later-stage, DMA/PIO, controller-registration,
ADSP, GPU, oops/panic or reset evidence; record modem faults separately.
No soundcard and the loader's soundcard-wait failure remain expected.

If the log stops after the version line without the combined child-values
line, the planned next operations were STATUS, CFG and RX_MSGQ_CFG reads.
Because no per-read marker exists, the log cannot identify which completed,
and buffered output can be lost. Archive all available journal, collector,
pstore and boot-outcome evidence before choosing another experiment. Do not
repeat a register read manually, enable dump windows or advance the stage in
the same boot. A stage-4 pass would establish only this bounded access and
observation, not safety of later writes or functional audio.
