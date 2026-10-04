# SPX audio: proposed top-level version-read stage 3

Proposed trial I is a separate fresh boot using **G's unchanged kernel,
modules, DTB and initramfs**, with only H's audio stage changed from 2 to 3
and a distinct attempt marker. It adds one explicit top-level NGD register
read after the QMI power acknowledgment. It does not test child-register
access, SLIMbus enumeration or playback.

Do not select I until H has completed at least 600 seconds of observation
and its result/artifact provenance has been archived and verified. H's early
success alone does not satisfy that dependency. This document records a
source review and future plan, not an executed stage-3 result. No audio MMIO
or bound-register read was performed for this review.

## Baseline and artifact identity

H is boot `3af15a82-c6ed-4d5e-b165-b332e3869793`, running the reused release
`7.3.0-rc2-spx-mainline-20260922g+`. Its journal records:

| Monotonic seconds | Observation |
| --- | --- |
| 27.867382 | Module pinned after SELECT_INSTANCE. |
| 27.868160 | Power transaction uses `pm_req=2`, `resp_type_valid=0`. |
| 27.884195 | Power response completes with `result=0x0 error=0x0`. |
| 27.890560 | Explicit stop after QMI power request, stage 2. |

During this review, H's NGD child remained runtime-suspended, its recorded
runtime-active time was zero, its module refcount was 1, and DMA/INT_EN/full/
PIO/window-dump/PDR-auto-enable parameters were disabled. These are interim
observations, not a completed H baseline. See
[H preparation](PREPARED-20260922h.md) and the
[stage-2 plan](AUDIO-STAGE2-20260922.md).

I would keep that same release and the payload described in
[G preparation](PREPARED-20260922g.md), including the QRTR rollback, A680 GBIF
correction, CMAC and UINPUT. No build, source, config, IPv6 MARK correction,
DTB, loader or userspace-service change belongs in this comparison. Preserve
the reused artifact hashes in I's own archive and select its entry only once,
with `spx-known-good` remaining the persistent default.

## Parameters

Replace the one effective stage option with:

```
slim_qcom_ngd_ctrl.spx_probe_stage=3 slim_qcom_ngd_ctrl.spx_pin_after_qmi=1
```

Keep `spx_gpu_profile=skip`, the 600-second observation policy, and the
existing loader's ADSP/QMI-service wait. Verify the effective module parameters
after boot; do not rely solely on the command-line text.

| Parameter | Required value |
| --- | --- |
| `spx_probe_stage` | **3** |
| `spx_pin_after_qmi` | Y |
| `spx_select_instance`, `spx_select_mode` | -1, 0 |
| `spx_power_resp_type` | -1; optional response-type TLV omitted |
| `spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full` | N, N, N |
| `spx_pio_mode`, `spx_pdr_auto_enable`, `spx_qmi_bypass_lookup` | N, N, N |
| `spx_dump_windows`, `spx_pio_debug_reads`, `spx_pio_tx_nowait` | N, N, N |
| `spx_stage5_step`, `spx_stage6_step`, `spx_stage7_step` | 0, 0, 0 |
| `spx_poll_rx` | Y, unchanged; stage 3 does not start polling |

Keep the child runtime-PM policy unchanged. Do not write `power/control`,
force runtime resume, raise parameters live, unload/rebind audio or restart
ADSP. The pin prevents ordinary module unload, not every teardown path.

## Exact access boundary

The reviewed [qcom-ngd-ctrl.c](../../../drivers/slimbus/qcom-ngd-ctrl.c) blob is
`f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`.

1. [Enable path, line 2653](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2653)
   performs SELECT_INSTANCE and pins the module. Stage 3 bypasses the
   stage-1/2 stops and calls the staged helper at line 2691.
2. [Staged helper, line 2532](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2532)
   sends one ACTIVE power request. It uses the same `pm_req=2` and omitted
   optional response-type TLV as H. A successful response sets
   `qmi.powered=true` and `mmio_alive=true` at lines 792–794.
3. Line 2540 calls the optional window-dump helper, whose
   [line-2090 guard](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2090) returns
   before any register read when `spx_dump_windows=0`. This guard is necessary:
   enabling the dump would add top-level and child-register reads before the
   stage-3 stop.
4. [Line 2542](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2542) executes a single
   32-bit `readl_relaxed(ctrl->base)`. The DT resource is
   [base `0x171c0000`, size `0x2c000`](../../../arch/arm64/boot/dts/qcom/sc8180x.dtsi#L3788),
   so the access is to **physical address `0x171c0000`**, offset zero.
   The code logs the raw value and `value >> 16`, then returns at line 2546.
5. The caller logs `stopping after staged hardware probe
   (spx_probe_stage=3)` at lines 2695–2697 and returns. There is no staged-path
   register write, DMA setup, PIO poller or controller registration.

For clarity, the child has [DT `reg=1`](../../../arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi#L33).
The matching offset data at driver lines 257–260 and calculation at line
2977 put its window at `0x171c1000`. Stage 3 returns before the stage-4 reads
of child STATUS (`0x171c1004`), CFG (`0x171c1000`) and RX_MSGQ_CFG
(`0x171c1008`). It does not read `0x171c2000`, the historically problematic
alternate window. These addresses are source-derived; they were not probed.

## Runtime PM, IRQ and historical limits

[Child probe, lines 3014–3018](../../../drivers/slimbus/qcom-ngd-ctrl.c#L3014)
sets runtime-suspended state, enables runtime PM and takes a reference with
`pm_runtime_get_noresume()`. Stage 3 performs its QMI request and explicit
version read without calling runtime resume or marking the child active.
A successful QMI response is firmware protocol evidence, not proof that every
AP register window, power domain or clock is accessible.

Do not force a runtime resume to prepare this experiment. The
[runtime-resume callback](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2500)
can enter `qcom_slim_ngd_power_up()` based on controller state; it is not
bounded by the stage-3 early return. That path reads child registers and can
write RX_MSGQ_CFG, INT_CLR and zero to INT_EN at
[lines 2220–2232](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2220) before later
setup checks. Disabled DMA/INT_EN/full parameters are not a universal ban on
all register writes from other callbacks.

The parent requests the interrupt with `IRQF_NO_AUTOEN` at lines 3131–3133,
then enables the Linux IRQ at line 3190 after registering the child and
notifiers. It remains enabled for the resulting diagnostic session. The
[ISR](../../../drivers/slimbus/qcom-ngd-ctrl.c#L1584) first checks `mmio_alive`,
then the child's runtime-suspended state. Power acknowledgment makes the
first check pass; the suspended-state check remains the expected barrier.
If that state changes, the ISR can read child INT_STAT at `0x171c1014` and
write INT_CLR at `0x171c1018`. Do not describe stage 3 as disabling every IRQ
or making all possible MMIO read-only.

The sibling 6.18
[June findings](../../../../linux-surface-kernel/docs/spx-audio-2026-06-11-findings.md#L306)
recorded stage 3 returning raw `0x02020000`, decoded version `0x202`, and a
separate stage-4 child-read success. Its
[post-reboot note](../../../../linux-surface-kernel/docs/spx-audio-post-reboot.md#L3)
records correction of an earlier inverted ACTIVE/INACTIVE enum and cautions
that pre-fix power-collapse interpretations were unreliable. Treat those
observations as historical evidence, not a guarantee for this kernel/boot.
The staged helper is unchanged between the current sibling and mainline
sources; parent/child registration, IRQ timing and teardown code differ.

The same history records a lockup from the `+0x2000` window and later failures
around child writes/DMA. A MMIO read can stall if its target is inaccessible;
`readl_relaxed()` has no timeout here, and a userspace return timer cannot
guarantee recovery from such a stall. The existing user authorization covers
experimental boots that may require a power cycle; this plan does not claim
automatic recovery is validated. Preserve the existing suspend behavior;
system suspend is a separate test.

## Result criteria and collection

After completing and archiving H, prepare I with a fresh attempt identity,
the exact reused artifact hashes and only the stage-2-to-3 functional change.
Recheck current boot ID, pending selection and recovery hashes immediately
before the authorized one-shot reboot. Keep early/periodic logging and the
bounded-return procedure; record explicitly if I is retained after a verified
baseline instead of returning.

Require the pin marker, successful ACTIVE response with zero result/error,
`staged QMI power request acked`, the raw/version log, the explicit stage-3
stop and child `enable done`. The historical expected value is
`raw=0x02020000`, `ver=0x202`; zero, all ones or a differing value must be
preserved and investigated, not automatically accepted or retried live.

Verify at least 600 seconds of continued ADSP/system progress, guarded
parameters/refcount, suspended child runtime status, graphics, input and
network behavior. Record modem failures separately from audio faults. Look
for unexpected IRQ, child-window, DMA, PIO, controller-registration, ADSP
fatal, DPU/GPU, oops or panic messages. A missing soundcard and the loader's
soundcard-wait failure remain expected at this stage.

If logs stop after the power-ack marker, the next planned access was the
version read, but missing buffered logs do not prove that read caused the
failure. Archive the complete available journal, collector, pstore and boot
outcome before choosing another experiment. Do not manually repeat the read
or advance to stage 4 in the same boot. A stage-3 pass establishes only this
bounded top-level access and observation window, not child-register safety,
audio transport, codec enumeration or playback.
