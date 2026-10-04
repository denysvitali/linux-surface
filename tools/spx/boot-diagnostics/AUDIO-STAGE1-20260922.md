# SPX audio: proposed QMI-only stage-1 trial

The next narrow audio experiment is a fresh boot with NGD stage 1, keeping
the module pinned after a successful QMI SELECT_INSTANCE. This tests the
ADSP service handshake before power requests, register access, DMA, PIO or
SLIMbus controller registration. It will not produce a soundcard or playback.
No audio source, live module parameter or device state was changed by this
review. The collector now records audio parameters/refcount, loader status and
journal, iptsd unit status and the input-device inventory. Trial F is planned;
the stage-1 experiment described here has not run.

## Current evidence and prerequisites

The running E kernel is `7.3.0-rc2-spx-mainline-20260922e+`, boot ID
`1caa8c4c-0fa9-4986-9e3b-32bf1919cea3`. Its journal records discovery of the
SLIMbus QMI service, completion of `qmi_up` at 28.235 seconds, and the explicit
stage-0 stop at 28.240 seconds. `/proc/asound/cards` reports no soundcards.

Read-only module parameter checks confirmed:

| Parameter | E value | Proposed trial value |
| --- | --- | --- |
| `spx_probe_stage` | 0 | **1** |
| `spx_pin_after_qmi` | Y | Y |
| `spx_select_instance` | -1 | -1 |
| `spx_select_mode` | 0 | 0 |
| `spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full` | N | N |
| `spx_pio_mode`, `spx_pdr_auto_enable`, `spx_qmi_bypass_lookup` | N | N |

E already includes the installed NGD, SLIMbus, QMI, PDR, WCD934x, WSA881x,
SoundWire and SDM845 machine modules. No additional config or kernel build is
required solely for stage 1. Planned F nevertheless uses a distinct build with
`CONFIG_INPUT_UINPUT=m`, retaining E's CMAC and A680 GBIF correction. The uinput
module addresses iptsd's missing input-device interface separately from audio.
F therefore changes both that configuration and the audio stage-1 boot
parameter; it is not an exact E-artifact comparison. In particular, the separate
`CONFIG_SLIM_QCOM_NGD_QMI_PROBE` module is unnecessary. Compiled BAM support
does not mean stage 1 starts DMA.

The existing `/usr/local/sbin/spx-audio-modules` waits for ADSP `running` and
QRTR service 769/version 1/instance 0 before explicitly loading NGD. Its
explicit modprobe bypasses the alias-autoload blacklist in
`/etc/modprobe.d/spx-slim-diag.conf`. Preserve this sequencing. The loader then
waits for a soundcard and will report failure after about ten seconds;
that outcome is expected while controller registration remains guarded.

Historical 6.18 evidence in the sibling tree's `PROGRESS.md:1224` records
successful instance-0 selection. Its September 8 clean-stereo report explicitly
describes a live repair, not a reboot-validated configuration. Neither proves
the stage-1 path on E. Its documented post-QMI module pin and failed recovery
after an ADSP crash also support using a fresh boot, without live unloads.

## Exact trial parameters and code boundaries

Append these two options to F's new one-shot trial entry, retaining E's DTB,
GPU policy, audio loader and other audio parameters:

```
slim_qcom_ngd_ctrl.spx_probe_stage=1 slim_qcom_ngd_ctrl.spx_pin_after_qmi=1
```

The installed `modprobe(8)` manual confirms that module options on the kernel
command line are read in `<module>.<option>` form. The loader currently adds
no conflicting NGD options. Verify the complete table above from sysfs after
the trial starts; retain all guards rather than enabling another stage in the
same boot. Do not combine this trial with the proposed QRTR source change.

Source references below are to
[qcom-ngd-ctrl.c](../../../drivers/slimbus/qcom-ngd-ctrl.c), reviewed blob
`f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`:

- Lines 2646–2667: stage 0 stops before `qcom_slim_qmi_init()`; stage 1
  returns immediately after that function succeeds. Stage 2's power request
  starts at line 2670 and is not reached.
- Lines 687–705: default instance is `ctrl->ngd->id >> 1`; the included
  `sc8180x-wcd9340.dtsi:33` child has `reg = <1>`, producing instance 0.
  `spx_select_mode=0` omits the optional mode TLV.
- Lines 516–552 and 710–724: SELECT_INSTANCE waits for a successful QMI
  response, retries at most three times with five-second transaction timeouts,
  and pins the module only after success. Keep the pin message in the logs.
- Lines 633–645: pinning takes a module reference to prevent ordinary unload.
  It does not prevent device unbinding or make arbitrary teardown safe.
- Lines 3131–3133 and 3190: the existing parent probe registers an IRQ with
  `IRQF_NO_AUTOEN`, then calls `enable_irq()`, including at stage 0. Therefore
  do not describe stage 1 as disabling every IRQ line. It adds no
  `NGD_INT_EN` write. `mmio_alive` stays false without the power request;
  the interrupt handler returns before register reads at lines 1584–1586.

Stage 1 still sends a state-changing QMI request. A timeout can leave the
firmware-side outcome uncertain; pinning happens only after success, and the
error path releases the QMI handle. A failed transaction is evidence to
collect, not a reason to retry manually or bypass the pin.

## Bounded verification

1. Finish and archive E's retained-boot evidence. Prepare a new attempt record
   with F's distinct kernel/modules/initramfs, complete source/config/artifact
   hashes, the uinput addition and the audio parameter difference. Keep
   `spx-known-good` as the persistent default and use the established
   one-shot/recovery checks.
2. Restore F's explicit 600-second return window for this new experiment. Capture
   early and periodic logs, including the audio-loader journal, module
   parameters, module refcount and ADSP remoteproc status, plus iptsd status and
   input-device inventory. Use the established logger and return machinery.
3. Success requires the direct-QMI connection, module-pinned message,
   `stopping after QMI select_instance (spx_probe_stage=1)`, and continued
   system/ADSP progress through the observation window. Record either orderly
   return or an explicitly verified decision to retain the live mainline
   session; a retained session does not prove the return path. No soundcard and
   the loader's card-registration timeout are expected. Assess uinput/iptsd
   separately; these do not establish audio success.
4. Record QMI transport errors, firmware result/error fields, ADSP crashes,
   pin failure, unexpected power/DMA/PIO/controller-registration logs or an
   interrupted return as a failed or inconclusive stage-1 trial. Do not raise
   the stage or unload/rebind the audio stack during that boot.

After a passed stage 1, stage 2 would be a separate power-request experiment;
it is not included here. Stage 7 step 6 must never be described as guaranteed
"no TX": its PIO path starts the RX poller before the observe-only log, and
receiving MASTER_CAPABILITY queues `m_work` at lines 897–899. The worker at
lines 2443 onward sends REPORT_SATELLITE through `qcom_slim_ngd_xfer_msg()`.
That distinction matters for any later PIO plan, even with proactive sends
disabled.
