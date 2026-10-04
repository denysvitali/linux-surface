# SPX audio: proposed QMI power-request stage 2

This is a plan for a **separate fresh-boot experiment**, not a live change or
an executed stage-2 result. [F's completed result](RESULT-20260922f.md) confirms
SELECT_INSTANCE success through 813.84 seconds, while preserving its initial
modem failure. [G's completed result](RESULT-20260922g.md) repeats the stage-1
success after the isolated QRTR rollback, with no modem announcement/fatal
error through 756.96 seconds. Its finalized baseline archive has 260 verified
hashes. The required observation is complete, satisfying the baseline
dependency for the separate H trial; one clean boot does not prove the
intermittent QRTR hypothesis resolved.

The narrow next audio change is `spx_probe_stage=2`, reusing G's exact
kernel/modules, DTB and initramfs from
[PREPARED-20260922g.md](PREPARED-20260922g.md), unchanged GPU policy and existing
audio loader sequencing. The reused kernel release remains
`7.3.0-rc2-spx-mainline-20260922g+`; H would identify a new attempt, not a new
kernel build. Keep its attempt marker, archive and one-shot entry distinct,
with persistent default `spx-known-good`.

Preserve G's already tested QRTR source state; add no further source/config
change, QRTR experiment or audio stage in the same comparison. H is being
prepared against that completed baseline. This document remains a plan and
does not record stage-2 execution or success.

## Parameters and preserved guards

Replace G's stage-1 option in the new attempt with:

```
slim_qcom_ngd_ctrl.spx_probe_stage=2 slim_qcom_ngd_ctrl.spx_pin_after_qmi=1
```

Retain the existing `spx_gpu_profile=skip` and 600-second diagnostic observation
policy. There must be only one effective `spx_probe_stage` option. The loader
must still wait for ADSP running and SLIMbus QMI service 769/version 1/instance
0, then explicitly load the installed NGD module. Verify the resulting sysfs
parameters rather than assuming the command line won any conflicting option.

| Parameter | Planned value |
| --- | --- |
| `spx_probe_stage` | **2** |
| `spx_pin_after_qmi` | Y |
| `spx_select_instance`, `spx_select_mode` | -1, 0 |
| `spx_power_resp_type` | -1, optional response-type TLV omitted |
| `spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full` | N, N, N |
| `spx_pio_mode`, `spx_pdr_auto_enable`, `spx_qmi_bypass_lookup` | N, N, N |
| `spx_stage5_step`, `spx_stage6_step`, `spx_stage7_step` | 0, 0, 0 |
| `spx_dump_windows`, `spx_pio_debug_reads`, `spx_pio_tx_nowait` | N, N, N |
| `spx_poll_rx` | Y, unchanged; stage 2 does not start its poller |

Do not raise the stage or restart/unload/rebind the audio stack in the current
G boot. A successful SELECT_INSTANCE has already pinned that module; the pin
prevents ordinary unload, not all forms of teardown or firmware-side change.

## Exact source boundary

References are to
[qcom-ngd-ctrl.c](../../../drivers/slimbus/qcom-ngd-ctrl.c), reviewed blob
`f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`:

- Lines 2653–2667 perform SELECT_INSTANCE, pin the module through line 724,
  and implement the stage-1 stop. With stage 2, lines 2670–2680 additionally
  call `qcom_slim_qmi_power_request(ctrl, true)`, then return immediately.
  The staged register-read path begins at line 2683 and is not entered.
- Lines 767–795 construct the ACTIVE power request: `pm_req=2`. The unchanged
  `spx_power_resp_type=-1` sets `resp_type_valid=0`; the logged response-type
  value is 1 but its optional TLV is absent. Success records the firmware
  power vote and sets `mmio_alive=true`.
- Lines 569–619 initialize/send QMI request `0x0021`, wait up to five seconds,
  log the decoded firmware result/error and reject a non-success result.
  Unlike SELECT_INSTANCE, this power request has no retry loop. The QMI core
  decodes into the transaction's response structure at
  [qmi_interface.c](../../../drivers/soc/qcom/qmi_interface.c), lines 502–508.
- Stage 2 does not execute the stage-3 register dump, stage-5 register writes,
  stage-6 DMA setup, stage-7 PIO/polling or full SLIMbus controller registration
  at line 2749. No soundcard, codec enumeration or playback is expected.

The IRQ boundary needs care. Parent probe requests the IRQ with
`IRQF_NO_AUTOEN` at lines 3131–3133, then enables the line at line 3190 even
for earlier stages. Stage 1 leaves `mmio_alive=false`, so the ISR exits before
register access at lines 1584–1586. A successful stage-2 power response sets
that flag true. The ISR also exits while the child is runtime-suspended at
lines 1589–1592; probe establishes that suspended state at lines 3014–3018
and the stage-2 branch does not runtime-resume it. If that state changes,
the existing ISR can read `NGD_INT_STAT` at line 1606 and clear status at line
1628. Therefore stage 2 adds no explicit register operation in its synchronous
probe branch, but must not be described as unconditionally preventing all
MMIO/interrupt activity after the power acknowledgment.

The error path also matters: a failed power request reaches `staged_err` at
lines 3100–3106 and calls `qcom_slim_ngd_enable(false)`, which releases the QMI
client. Module pinning does not bypass this probe-error cleanup. A timeout
leaves firmware-side effects uncertain even if the caller returns an error;
collect it as a failed/inconclusive attempt rather than retrying manually.

## Evidence and outcome criteria

1. Use G's completed source/config/artifact and runtime archive, verify
   unchanged known-good hashes, and prepare a new attempt with the exact
   reused artifact hashes and stage-2 command-line difference. Check current
   boot ID and pending selection immediately before the authorized one-shot
   reboot using the established workflow.
2. Collect early and periodic kernel/userspace journals, all NGD parameters
   and refcount, the audio-loader log, ADSP/CDSP/modem state, NGD child runtime
   status, IRQ-related log messages and desktop/input/network state. Retain
   the normal bounded-return machinery; record explicitly if a verified
   mainline session is later retained instead of returning.
3. Handshake success requires the direct-QMI connection and pin marker, a
   power send for `pm_req=2`, a completed power wait with `result=0x0 error=0x0`,
   and `stopping after QMI power request (spx_probe_stage=2)`. Also require
   continued ADSP and system progress throughout the observation window,
   with no unintended later-stage operations. The audio loader's eventual
   no-soundcard failure is expected and does not itself fail stage 2.
4. Preserve any QMI timeout/rejection, ADSP failure, unexpected IRQ/register
   activity, GPU fault or interrupted observation. Record modem faults
   separately against G's completed baseline and F's earlier modem
   announcement/fatal/restart sequence;
   a modem crash alone does not identify stage 2 as its cause. No result here
   establishes audio playback or complete hardware recovery.

Only after a completed stage-2 result should a separate stage-3 register-read
experiment be considered. Higher stages remain outside this plan.
