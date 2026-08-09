# SPX audio bring-up — 2026-06-11 findings

This doc captures the state after the clock-fix build (kernel image
`5ccc9915d4…`, "preset_channels=23") first froze the system on
`sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=6`, and what we did
next. The two prior docs — `spx-audio-post-reboot.md` and the
inline `docs/spx-camera-recon.md` — are unchanged.

## What was confirmed on the fresh boot (without loading the module)

All checks were done from a clean shell after the user rebooted; nothing
in `modprobe` was run.

| Check | How | State |
| --- | --- | --- |
| ADSP remoteproc | `cat /sys/class/remoteproc/remoteproc2/state` | `running` |
| APR audio services | `sudo journalctl -k \| grep apr` | 3/4/7/8 registered on `apr_audio_svc` |
| IPCRTR (apps↔ADSP) edge | `ls /sys/bus/rpmsg/devices/ \| grep IPCRTR` | bound, driver attached |
| SLIMbus QMI service 0x301 | `sudo qrtr-lookup` | **published on node 5, port 11, version 1, instance 0** |
| BAM probe state | `sudo dmesg \| grep 'SPX: BAM'` | `has_clk=1 preset_channels=23 preset_ees=4`, init done, DMA registered |
| Iommu group for SLIMbus + BAM | `ls /sys/kernel/iommu_groups/4/devices/` | `171c0000.slim-ngd` + `17184000.dma-controller` both bound |
| `slim_qcom_ngd_ctrl` module | `lsmod \| grep slim` | not loaded — device is safe to debug from userspace |

The SLIMbus QMI service is exactly what `qcom-ngd-ctrl.c` expects
(`SLIMBUS_QMI_SVC_ID=0x301`, `SLIMBUS_QMI_SVC_V1=1`,
`SLIMBUS_QMI_INS_ID=0`). When the module's `qmi_add_lookup` runs, the
`new_server` callback should fire immediately because the service is
already known to the local QRTR cache. **There is no QRTR-side reason
for the freeze.**

## What we could not see

- `/sys/fs/pstore/` is empty in the current boot, and the journal was
  rotated by a 229-second clock jump after the crash, so the
  pre-freeze dmesg tail is lost.
- `CONFIG_HARDLOCKUP_DETECTOR is not set` in this kernel
  (`zcat /proc/config.gz \| grep HARDLOCKUP_DETECTOR`). Only
  `hung_task` (timeout 120s, `hung_task_panic=0`) is enabled. So the
  "rebooted by itself" reset was not a hardlockup panic and not a
  hung_task panic — it was either a BUG() in non-fatal context, a
  firmware-level PSCI watchdog, or a manual power event. Pstore should
  have caught a real panic, so the most likely explanations are (a) the
  kernel never reached a panic path and (b) ramoops was not actually
  persisting to RAM (see next section).
- Without the stack, the only signal we have is the single line
  `SPX: NGD child id=1 base_offset=0x1000` from the **parent**
  driver's `of_qcom_slim_ngd_register` (drivers/slimbus/qcom-ngd-ctrl.c:1917).
  After that, `platform_device_add(ngd->pdev)` triggers the child
  probe synchronously, and the child probe's first blocking call is
  `wait_for_completion_interruptible_timeout(&ctrl->qmi_up, 1s)`. So
  the hang is between the parent's `dev_info` at line 1917 and that
  wait — i.e. inside the child probe's first ~6 lines.

## Bug found: ramoops is double-initialised

Every boot, the kernel ring says:

    ramoops: using module parameters
    pstore: Registered ramoops as persistent store backend
    ramoops: using 0x100000@0x9a480000, ecc: 0
    ramoops: already initialized
    ramoops ramoops: probe with driver ramoops failed with error -22

The kernel command line already configures ramoops with the correct
sizes (`ramoops.mem_address=0x9a480000 ramoops.mem_size=0x100000
ramoops.record_size=0x4000 ramoops.console_size=0x20000
ramoops.pmsg_size=0x10000`). But the DT node also has
`compatible = "ramoops"` on the same memory region, so the
built-in platform driver tries to register a second instance and the
kernel rejects it with `-EINVAL` ("already initialised"). The cmdline
instance survives but the platform driver never binds, so the
persistent pstore dump region is not actually wired to a backend.

Fix: drop `compatible = "ramoops";` from the `ramoops_mem` node in
`arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts`. The cmdline
params are enough.

## The freeze, restated

The clock-fix build changed three things, in order from lowest to
highest risk:

1. `drivers/dma/qcom/bam_dma.c` — `bam_clk` is now required when the
   DT supplies a `clocks` property; returns `-ENOENT` for a NULL handle.
2. `drivers/clk/qcom/common.c` — `qcom_cc_clk_hw_get` returns
   `ERR_PTR(-ENOENT)` for sparse holes so the OF clock core can
   continue to the earlier provider on the same node.
3. `drivers/dma/qcom/bam_dma.c` — `num-channels` and `qcom,num-ees`
   are always seeded from DT (was previously conditional on
   `!bdev->bamclk`).

Of these, only (1) and (2) change runtime behaviour on this hardware.
(1) is the new BAM error path; (2) is the new clock fallback. Together
they make the LPASS AHB clock findable for the first time
(`lpass_q6ss_ahbs_aon_clk enable_count=1` after BAM probe, was 0
before). Nothing in the SLIMbus child probe references a clock, so the
clock change should not affect the child probe directly.

The most consistent explanation with the symptoms is that the new
LPASS AHB clock vote changes the LPASS fabric / Q6 power state enough
that the QRTR/SMD edge between apps and the ADSP behaves differently
when the SLIMbus module asks it for a fresh QMI handle. The next
freeze — if we cannot avoid triggering it — must leave evidence, or we
are back to guessing.

## Operational rule

**Do not run stage 6 again until ramoops is actually working.** The
freeze left no stack trace because ramoops never wrote anything to
pstore, and the journal rotated away the dmesg tail. Without
evidence, every subsequent hypothesis is another round of
`rebuild → reboot → modprobe → freeze → reboot`. Fix ramoops first,
trigger a controlled panic to confirm it works, then proceed.

## Fixes landed in source today

1. Removed `compatible = "ramoops";` from `ramoops_mem` in the board
   DTS. The kernel-cmdline ramoops instance is now the only one. DTB
   only, rebuild + install + reboot.

2. `qcom_slim_ngd_qmi_svc_event_init` failure in the child probe now
   returns `-EPROBE_DEFER` instead of the raw error. Previously a
   transient QMI hiccup left SLIMbus silently dead; now the kernel
   re-probes.

3. The child probe's `qmi_up` wait is now 5s (was 1s) and on timeout
   it calls `WARN(1, …)` printing the `new_server` callback pointer,
   so the next hang leaves a marker even if pstore fails.

4. New diagnostic module `slimbus_qmi_probe` (see below).

## New diagnostic module: `slimbus_qmi_probe`

Single-TU kernel module at `drivers/slimbus/slimbus-qmi-probe.c`,
gated by `CONFIG_SLIM_QCOM_NGD_QMI_PROBE` (tristate, default `n`).
It exercises the **same** QMI / QRTR plumbing as the SLIMbus child
probe but never touches `0x171c0000` and never starts a DMA. The goal
is to bisect whether future freezes are in the QRTR/QMI/PDR
subsystem or in the SLIMbus driver itself.

### Build

`CONFIG_SLIM_QCOM_NGD_QMI_PROBE=m` in `.config` and a normal
`make M=drivers/slimbus modules` will produce
`drivers/slimbus/slimbus-qmi-probe.ko`. It is independent of
`CONFIG_SLIM_QCOM_NGD_CTRL`, so it can be built/loaded without the
real driver in the tree.

### Install

    sudo install -m 0644 -o root -g root \
        drivers/slimbus/slimbus-qmi-probe.ko \
        /lib/modules/$(uname -r)/extra/
    sudo depmod -a
    sudo modprobe slimbus_qmi_probe

Module parameters:

- `probe_stage` (int, default 0) — same idiom as the real driver.
- `allow_qmi_mutation` (bool, default false) — required for stages 1
  and 2. These stages are no longer considered safe defaults on SPX.
- `pin_after_qmi_mutation` (bool, default true) — after a successful
  `SELECT_INSTANCE`, increment the module refcount so `modprobe -r`
  cannot release the QMI handle. Reboot is then required before
  unloading.
- `select_instance` (int, default 0) — passed to the SELECT_INSTANCE
  TLV instance field.
- `log_echo` (bool, default true) — log every QRTR packet seen.

### Stages

- **Stage 0** — `qmi_handle_init` + `qmi_add_lookup` for service
  0x301. The `new_server` callback logs node/port and completes a
  local completion. Module waits up to 3s for the completion, then
  stays loaded.
- **Stage 1** — also `kernel_connect` to the discovered service and
  send `SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01` (0x0020) with the same
  TLV layout as `qcom_slim_qmi_init`. Requires
  `allow_qmi_mutation=1`.
- **Stage 2** — also send `SLIMBUS_QMI_POWER_REQ_V01` (0x0021) with
  `pm_req = SLIMBUS_PM_ACTIVE_V01`, wait for ack, then immediately
  send `pm_req = SLIMBUS_PM_INACTIVE_V01` and wait for ack, so the
  ADSP is left in the same state it was in before the probe. Requires
  `allow_qmi_mutation=1`.

### Expected log shape

    SPX: QMI-probe stage 0: handle init begin
    SPX: QMI-probe stage 0: handle init done
    SPX: QMI-probe stage 0: add_lookup svc=0x301 v=1 inst=0
    SPX: QMI-probe stage 0: waiting for new_server (3s)
    SPX: QMI-probe new_server: node=5 port=11 service=0x301 instance=0
    SPX: QMI-probe stage 0: done
    SPX: QMI-probe stage 1: select_instance req begin
    SPX: QMI-probe stage 1: select_instance ack result=0x0
    SPX: QMI-probe stage 1: done
    SPX: QMI-probe stage 2: power=active req begin
    SPX: QMI-probe stage 2: power=active ack result=0x0
    SPX: QMI-probe stage 2: power=inactive req begin
    SPX: QMI-probe stage 2: power=inactive ack result=0x0
    SPX: QMI-probe stage 2: done

### How to interpret a hang

- If the freeze happens **before** `new_server` fires, the cause is in
  QRTR packet processing or in the new LPASS AHB clock vote that
  exposes an existing race. Disable the new clock vote by removing
  `clk_ignore_unused` from the kernel cmdline (or by
  `echo 0 > /sys/module/clk_qcom/parameters/skip_disable`) and re-run
  stage 0; if it now succeeds, the LPASS AHB clock vote was the
  trigger.
- If the freeze happens **after** `new_server` fires but before
  `select_instance` acks, the cause is in
  `kernel_connect` / `qmi_send_request` for the second socket. That
  points at the QMI helpers or the SMD/GLINK edge.
- If the freeze happens **after** `select_instance` acks, the cause
  is in the ADSP-side SLIMbus QMI service handling a POWER request,
  i.e. firmware-side. The fix there is in the ADSP firmware image,
  not in the kernel.
- If the probe module runs cleanly through stage 2, the SLIMbus-side
  freeze is in code that runs after `qcom_slim_ngd_enable` returns,
  i.e. in the MMIO path. Re-run the real driver with
  `spx_probe_stage=2` or `spx_probe_stage=3` to find the
  first-MMIO-write hang.

## Hard-won operational rules (additions)

- The new LPASS AHB clock vote is a runtime behaviour change. Until it
  is exercised end-to-end without a hang, treat any `modprobe
  slim_qcom_ngd_ctrl` as a controlled experiment, not a routine
  command. Have a SysRq sequence ready (`Alt-SysRq-s` to sync, then
  `Alt-SysRq-b` to reboot) and a way to read pstore after.
- The kernel cmdline ramoops and a DT `compatible = "ramoops"` node
  are **mutually exclusive** on this kernel. Use one or the other.
- `samples/qmi/qmi_sample_client.c` includes `<linux/qrtr.h>`, which
  does not exist on this tree. The new probe module uses
  `<uapi/linux/qrtr.h>` instead and avoids the sample's local
  QMI-encoding helpers in favour of the kernel's
  `qmi_encode_*` API.

## Follow-up after reboot: QMI probe stage 0/1

After rebooting with the DT ramoops fix, ramoops did not auto-load
because it is built as a module. Loading it manually registered the
cmdline backend cleanly:

    pstore: Registered ramoops as persistent store backend
    ramoops: using 0x100000@0x9a480000, ecc: 0

`/etc/modules-load.d/ramoops.conf` now contains `ramoops`, so future
boots load the backend automatically.

`slimbus_qmi_probe probe_stage=0` succeeded immediately:

    SPX: QMI-probe new_server: node=5 port=11 service=0x301 instance=0 version=1
    SPX: QMI-probe stage 0: done node=5 port=11

The first `probe_stage=1` attempt failed with `-EOPNOTSUPP` (`-107`)
because the diagnostic module reused the lookup QMI handle but did
not connect its QRTR socket before calling `qmi_send_request(...,
sq=NULL, ...)`. The real driver explicitly calls `kernel_connect()`
in `qcom_slim_qmi_init()`, so the probe was fixed to mirror that.

The next `probe_stage=1` attempt reached the ADSP response path but
then Oopsed locally in `qmi_helpers`:

    pc : qmi_decode+0x6c/0x564 [qmi_helpers]
    Workqueue: qmi_msg_handler qmi_data_ready_work [qmi_helpers]

This was a bug in the diagnostic module, not evidence against the
ADSP. `slimbus_qmi_probe` declared response TLV `0x02` as a
`QMI_STRUCT` with `ei_array = NULL`; the QMI decoder then recursed
into a NULL nested element table. The probe now mirrors
`qcom-ngd-ctrl.c` and decodes response TLV `0x02` as nested
`struct qmi_response_type_v01` with `qmi_response_type_v01_ei`.

The Oops also proved the original ramoops sizing was too small:

    pstore: backend (ramoops) writing error (-28)

The boot cmdline has been changed from 16 KiB records plus unused
console/pmsg reservations to four 256 KiB dmesg records:

    ramoops.record_size=0x40000 ramoops.console_size=0 ramoops.pmsg_size=0

Because the Oops left the old probe module pinned and a `modprobe`
process in uninterruptible sleep, do not retest stage 1 in the same
boot. Reboot first, confirm ramoops auto-loaded with the larger record
geometry, then retry:

    sudo modprobe slimbus_qmi_probe probe_stage=1 select_instance=0
    sudo dmesg -T | grep 'SPX: QMI-probe'

## Follow-up: real driver stages 2-5

After rebooting again, the fixed `slimbus_qmi_probe` ran cleanly
through all QMI-only stages:

- stage 0: QRTR lookup/new_server succeeded.
- stage 1: `SELECT_INSTANCE` acked with `result=0x0 error=0x0`.
- stage 2: `POWER_ACTIVE` and `POWER_INACTIVE` both acked with
  `result=0x0 error=0x0`.

That rules out QRTR/QMI/PDR as the direct cause of the later reset.

The real `slim_qcom_ngd_ctrl` staged probe then reached:

- `spx_probe_stage=2`: real driver QMI select + power acked.
- `spx_probe_stage=3`: top-level NGD version read succeeded:
  `raw version register=0x2020000 ver=0x202`.
- `spx_probe_stage=4`: child NGD reads succeeded:
  `status=0x40c cfg=0x0 rx_msgq_cfg=0x0`.

The next test, the old `spx_probe_stage=5`, reset the machine. There
is no `dmesg-ramoops-*` file in `/sys/fs/pstore/` after reboot, and
the previous boot's persistent journal ends at the successful stage 4
lines. No Linux `Oops`, `panic`, `Internal error`, watchdog splat, or
`pstore` write error was recorded.

Interpretation: this was not a normal Linux crash path. It is most
consistent with a firmware/SoC-level reset or hard lock triggered by
stage 5's child NGD write sequence. Since stage 4 proved all reads are
safe and the standalone QMI probe proved ADSP QMI power is safe, the
first dangerous operation is in the stage 5 write area:

    writel_relaxed(DEF_NGD_INT_MASK, ngd->base + NGD_INT_EN);
    writel_relaxed(rx_msgq | SLIM_RX_MSGQ_TIMEOUT_VAL,
                   ngd->base + NGD_RX_MSGQ_CFG);

The live output from the test reached the "writes done" marker before
the reset, so the current best hypothesis is that arming child NGD
interrupts leaves a line asserted or enables an interrupt source the
APPS-side handler cannot safely service yet. The reset is delayed
enough to print live output, but not enough for journald to persist it.

The real driver has now been rebuilt and installed with a safer stage 5:

- `spx_probe_stage=5 spx_stage5_step=0`: read/log only, no writes.
- `spx_probe_stage=5 spx_stage5_step=1`: write/read back
  `NGD_RX_MSGQ_CFG` only.
- `spx_probe_stage=5 spx_stage5_step=2`: write `NGD_INT_CLR` only.
- `spx_probe_stage=5 spx_stage5_step=3`: write `NGD_INT_EN`, read it
  back, then immediately write `0` to disable it again.

Do not run old stage 5 semantics again. The next diagnostic run should
use these sub-steps one at a time, with manual confirmation after each
one, and should not proceed to stage 6 until the interrupt-enable
sub-step is understood.

## Follow-up: INT_EN reset confirmed, staged DMA/full gated

The controlled stage 5 sub-steps showed:

- `spx_stage5_step=0`: no writes, clean.
- `spx_stage5_step=1`: `NGD_RX_MSGQ_CFG=0x10000` write/readback,
  clean.
- `spx_stage5_step=2`: `NGD_INT_CLR` write/readback, clean.
- `spx_stage5_step=3`: `NGD_INT_EN=0xfe000000` write/readback,
  immediate disable/readback to `0x0`, then delayed reset.

After the reset there was still no pstore record and no Linux crash
signature. The previous boot's journal did persist the full step 3 log
through `INT_EN disabled readback=0x0`, so the write itself completes,
but even briefly arming those child NGD interrupt sources is enough to
trigger a later firmware/SoC reset.

A subsequent reset had no persisted `SPX:` lines at all, which means it
happened before journald flushed any diagnostic output from that run.
Treat this as the same class of platform-level reset: do not keep
advancing hardware stages without an explicit guard.

The installed `slim-qcom-ngd-ctrl.ko` is now guarded:

- `spx_probe_stage=5 spx_stage5_step=3` refuses unless
  `spx_allow_int_en=1`.
- `spx_probe_stage=6` refuses unless `spx_allow_dma=1`.
- Full SLIMbus controller registration refuses unless
  `spx_allow_full=1`.

Installed guarded module hash:

    f3c3fb3d67fe38359c0232747dea0d8b307b365d759d168f0bc1c01b9c432bf7

The source full-power path has also been changed to keep
`NGD_INT_EN=0` unless `spx_allow_int_en=1`; the next viable direction
is a polling or alternate-completion path for capability exchange,
rather than enabling the NGD interrupt mask.

## Follow-up: polling path and staged DMA sub-steps

The installed module now contains a non-interrupt capability-exchange
experiment. When `spx_poll_rx=1` (default) and `spx_allow_int_en=0`,
`qcom_slim_ngd_power_up()` keeps `NGD_INT_EN=0` and, while waiting for
the initial `reconf` completion, polls the coherent RX message buffers.
If a buffer contains a SLIMbus message, it is fed through the existing
`qcom_slim_ngd_rx()` handler so the normal master-capability path can
queue `qcom_slim_ngd_master_worker()` and complete `reconf`.

This is deliberately narrow: it only replaces the unsafe NGD interrupt
dependency during the initial capability exchange. It does not claim
full playback readiness yet.

Stage 6 is now split into explicit DMA sub-steps:

- `spx_probe_stage=6 spx_stage6_step=0`: no DMA operations.
- `spx_probe_stage=6 spx_stage6_step=1`: request/release RX DMA
  channel only.
- `spx_probe_stage=6 spx_stage6_step=2`: request RX DMA channel,
  allocate/free coherent RX buffer.
- `spx_probe_stage=6 spx_stage6_step=3`: initialize RX queue and post
  RX descriptors.
- `spx_probe_stage=6 spx_stage6_step=4`: full RX+TX DMA init, then
  cleanup.

Stage 6 step 0 performs no DMA and is allowed without extra opt-in.
Stage 6 steps 1-4 still refuse unless `spx_allow_dma=1`, and full
controller registration still refuses unless `spx_allow_full=1`. This
prevents accidental reset-inducing commands while leaving a controlled
path for the next manual diagnostic run.

The high-level post-DMA stages are:

- `spx_probe_stage=7 spx_allow_dma=1`: run QMI, power request, full DMA
  init, NGD setup, and capability polling, then stop before
  `slim_register_controller()`.
- `spx_probe_stage=8 spx_allow_dma=1 spx_allow_full=1`: continue from
  the same full power-up path into SLIM controller registration.

This keeps the next broad test to one reboot-sized step while still
separating firmware/MMIO/DMA bring-up from Linux SLIMbus/ALSA
enumeration.

After `spx_probe_stage=7 spx_allow_dma=1` also reset with no pstore and
no persisted `SPX:` lines, stage 7 was split internally:

- `spx_stage7_step=0`: QMI power-on plus safe version/status/config
  reads.
- `spx_stage7_step=1`: step 0 plus full RX+TX DMA init.
- `spx_stage7_step=2`: step 1 plus RX timeout/INT clear/INT disable
  and `NGD_CFG` enable for RX/TX queues and NGD.
- `spx_stage7_step=3`: step 2 plus capability exchange polling.

For stage 7 diagnostics, failures after `SELECT_INSTANCE` are logged
but the probe returns success so the module remains pinned and does not
run the QMI release path. Reboot is the cleanup path.

Installed module hash with polling + stage 6 sub-steps:

    28d911129adf44338cf5e51bcf4cdcaca92c3d4fd23bd2e69611150cfca863ae

Current userspace audio state after reboot is still:

    /proc/asound/cards: --- no soundcards ---

So the objective is not complete; the next milestone is proving the
polling path can reach SLIMbus controller registration without arming
`NGD_INT_EN`.

## Follow-up: stage 6 step 1 and teardown Oops

`spx_probe_stage=6 spx_stage6_step=0` completed cleanly. It reached
the DMA stage with `NGD_INT_EN` held disabled and performed no DMA
operation.

`spx_probe_stage=6 spx_stage6_step=1 spx_allow_dma=1` also completed
cleanly. It requested and released the RX DMA channel only. The BAM
driver allocated pipe 3, allocated/free'd the FIFO, reset the pipe, and
disabled pipe IRQ state without hanging.

The next attempted run (`spx_stage6_step=2`) did not reach the DMA
allocation step. It failed earlier in `SELECT_INSTANCE` with a QMI
transaction timeout:

    QMI TXN wait fail: -110
    failed to select h/w instance
    qmi init fail, ret:-110

Then module removal Oopsed:

    pc : qmi_handle_release+0x24/0x160 [qmi_helpers]
    lr : qcom_slim_ngd_ctrl_remove+0xa4/0x110 [slim_qcom_ngd_ctrl]

Root cause: the child probe failure path already deinitialized the
service-event QMI handle via `qcom_slim_ngd_qmi_svc_event_deinit()`.
The parent `qcom_slim_ngd_ctrl_remove()` then unconditionally called
the same deinit path again. `qmi_handle_release()` is not NULL-safe and
dereferences `qmi->sock`, so the second release crashed.

The source and installed module now track `qmi_svc_event_active` and
release the service-event QMI handle only once. Installed fixed module:

    7b0f3c8ebf7e840b2802b313992359db0fee27c990891cd0bb1d782223f3de9d

The current boot cannot be used for further module testing because the
old module is wedged in the live kernel with refcount `-1` after the
Oops. Reboot before the next test so the fixed teardown code is loaded.

## Follow-up: QMI timeout, ADSP restart, and no-pstore reset

`spx_probe_stage=6 spx_stage6_step=2 spx_allow_dma=1` later completed
cleanly: it requested RX DMA, allocated a coherent RX buffer, released
the resources, and never armed `NGD_INT_EN`.

The following attempt to continue testing did not reach the next DMA
step. The SLIMbus QMI service was advertised, but both the real driver
and `slimbus_qmi_probe probe_stage=1` timed out waiting for
`SELECT_INSTANCE`:

    QMI TXN wait fail: -110
    PDR: msm/adsp/audio_pd register listener txn wait failed: -110
    SPX: QMI-probe select_instance qmi_txn_wait failed:-110

Restarting `remoteproc2` recovered the ADSP service enough for
`slimbus_qmi_probe probe_stage=1` to receive a successful
`SELECT_INSTANCE` ack on the new service port. Immediately after the
probe handle was released, the machine reset again. The next boot had
no `/sys/fs/pstore/dmesg-ramoops-*` files and the previous journal ends
at:

    SPX: QMI-probe stage 1: select_instance ack result=0x0 error=0x0
    SPX: QMI-probe exit: releasing handle
    SPX: QMI-probe exit done

So this was not a Linux panic/Oops path. The current best diagnosis is
a firmware/platform reset after SLIMbus QMI state mutation, likely
related to the previously observed ADSP/PDR QMI timeout state. Because
of that, the installed defaults have been made more conservative:

- `slim_qcom_ngd_ctrl` now defaults to `spx_probe_stage=0`, which
  stops before sending `SELECT_INSTANCE`.
- `slimbus_qmi_probe` now refuses stages 1 and 2 unless
  `allow_qmi_mutation=1` is explicitly provided.
- Both the real driver and probe module now pin themselves after a
  successful `SELECT_INSTANCE` by default, so accidental `modprobe -r`
  cannot trigger the QMI handle release path that preceded the latest
  no-pstore reset.
- The real driver's QMI power-request path now checks
  `qmi_txn_init()` before sending the request.

Installed safer module hashes:

    slim-qcom-ngd-ctrl.ko  80029f1741611786d19338b03768d889842ad2a879c5d9257bde63fd382adac5
    slimbus-qmi-probe.ko   24b36efa44fefc9fbf0152462c81fa48338359d52fffd000e6e0ad18178e18d9

The safe diagnostic boundary is now only service lookup:

    sudo modprobe slimbus_qmi_probe probe_stage=0

Anything that sends `SELECT_INSTANCE` or `POWER_REQ` should be treated
as reset-capable and run only when a reset is acceptable.

## Follow-up: broad test reset with no persisted SLIMbus lines

After a reset following the broad/full test, the next boot again had no
`/sys/fs/pstore/dmesg-ramoops-*` file. The previous boot's journal
contains normal boot, ADSP/APR services, modem, Wi-Fi, and then no
persisted `SPX:`/SLIMbus test lines at all. That means the reset
happened before the SLIMbus diagnostic output reached persistent
journal, so the broad test did not identify the exact failing point.

To reduce further reboot churn while preserving a useful boundary, the
high-level stages were split:

- `spx_probe_stage=7 spx_allow_dma=1`: full NGD/BAM/MMIO power-up and
  capability polling, but stop before `slim_register_controller()`.
- `spx_probe_stage=8 spx_allow_dma=1 spx_allow_full=1`: continue into
  full SLIM controller registration and ALSA-facing enumeration.

Installed `slim-qcom-ngd-ctrl.ko` with that split:

    38d89ca4cfd4150c3f09d51fec85f0ca7c07ea214993e645f54f06e97333e2da

`spx_stage7_step=0` passed: QMI power-on acked and safe reads returned
`ver=0x202 status=0x40c cfg=0x0 rx_msgq=0x0`.

`spx_stage7_step=1` reset before the previously existing
`stage 7 QMI power-on acked by ADSP` line. The QMI power helper now
logs transaction init, send begin/done, wait begin, and wait done so
the next run can distinguish reset during QMI send/wait from reset
after the QMI ack but before DMA init.

With the extra QMI logging, `spx_stage7_step=1` reached full RX+TX DMA
init and returned before SLIM registration. The visible tail showed RX
descriptors issued, TX channel/buffer allocation, TX ring reset, and
`SPX: stage 7 full RX+TX DMA init done`, followed by DPU frame-done
timeouts. The likely issue is leaving RX DMA descriptors active while
stopping before NGD/SLIM registration. Stage 7 step 1 now releases DMA
resources before returning.

Installed `slim-qcom-ngd-ctrl.ko` with step-1 DMA cleanup:

    96a74b7818650d1ef13ac12ebbfbe5f5c7ae6d99eb238d1dd4f3307c1528afac

## Follow-up: reset during POWER_ACTIVE wait

After another clean reboot, a stage-7 step-1 run reset before any DMA
or NGD register access. The visible tail was:

    SPX: stage 7 controlled power-up step=1
    SPX: QMI power txn init done pm_req=2 txn_id=1
    SPX: QMI power send begin pm_req=2
    SPX: QMI power send done pm_req=2 ret=0
    SPX: QMI power wait begin pm_req=2 timeout=3000 ms

There was no `QMI power wait done` line and no pstore record after the
reset, so this is still a firmware/platform reset rather than a Linux
panic. This narrows the reset-capable boundary to the ADSP SLIMbus QMI
`POWER_ACTIVE` transaction after the request packet has been accepted
by QRTR.

The in-kernel driver and diagnostic QMI probe previously omitted the
optional `resp_type` TLV from `SLIMBUS_QMI_POWER_REQ_V01`, while the
userspace QRTR probe already had a known variant that sends
`resp_type=1` (`SLIMBUS_RESP_SYNCHRONOUS_V01`). Both kernel modules now
have a parameter to select that request shape:

- `slim_qcom_ngd_ctrl.spx_power_resp_type=-1` keeps the old behavior
  and omits the optional TLV.
- `slim_qcom_ngd_ctrl.spx_power_resp_type=1` emits
  `resp_type_valid=1, resp_type=1`.
- `slimbus_qmi_probe.power_resp_type` provides the same control for the
  QMI-only probe.

Installed module hashes with the `resp_type` knob:

    slim-qcom-ngd-ctrl.ko  74d9a32c0e1b02220d72f9e8e23db57a4ac5ced47f3331ef4defd1d2b2a7f329
    slimbus-qmi-probe.ko   87261a79e3cf600f157fe797c6b231e8454ecea194bddbfb6c7e0e58eb5c45fb

Recommended next test after a clean reboot is to try the synchronous
POWER request shape at the already-known safe stage-7 step 0:

    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=0 spx_power_resp_type=1

If that reaches `QMI power wait done` and `stage 7 reads done`, reboot
before the next mutation and then try `spx_stage7_step=1` with the same
`spx_power_resp_type=1`. If step 0 resets with `resp_type=1`, the
optional TLV is worse on this firmware and should not be used.

Follow-up: a clean stage-7 step-0 run completed with the old POWER
request shape:

    SPX: QMI power txn init done pm_req=2 resp_type_valid=0 resp_type=1 txn_id=1
    SPX: QMI power send done pm_req=2 ret=0
    SPX: QMI power wait done pm_req=2 result=0x0 error=0x0
    SPX: stage 7 QMI power-on acked by ADSP
    SPX: stage 7 reads done ver=0x202 status=0x40c cfg=0x0 rx_msgq=0x0

Because `resp_type_valid=0`, this confirms only the baseline stage-0
boundary, not the new optional `resp_type` TLV. The next useful test is
stage-7 step 1 after a reboot, preferably with
`spx_power_resp_type=1`, so the POWER request shape differs from the
previous reset-prone step-1 runs and the DMA cleanup path can be tested
if QMI completes.

Follow-up: stage-7 step 1 with the previous numbering reached full
RX+TX DMA initialization and the added cleanup, then the display
controller immediately started timing out and the machine reset:

    SPX: TX DMA channel released
    SPX: freeing RX DMA buffer phys=0x00000000ffff7000 size=1280
    SPX: freeing TX DMA buffer phys=0x00000000fffe7000 size=1320
    SPX: stage 7 step 1 cleanup done
    SPX: stopping after controlled stage 7 before SLIM registration
    [drm:dpu_encoder_frame_done_timeout] [dpu error]enc33 frame done timeout

This moved the boundary past QMI and past DMA cleanup. The failure is
now associated with the side effects of actually starting/releasing the
BAM/NGD DMA state, not with the POWER_ACTIVE wait itself.

To avoid another large jump, stage 7 now reuses the existing controlled
DMA steps after QMI power-up:

- `spx_stage7_step=0`: QMI POWER_ACTIVE plus safe NGD reads.
- `spx_stage7_step=1`: request/release RX DMA channel only.
- `spx_stage7_step=2`: request RX channel, allocate/free RX coherent
  buffer.
- `spx_stage7_step=3`: initialize RX queue and post RX descriptors,
  then cleanup.
- `spx_stage7_step=4`: full RX+TX DMA init, then cleanup. This is the
  equivalent of the reset-prone old step 1.
- `spx_stage7_step=5`: full DMA init plus NGD_CFG enable.
- `spx_stage7_step=6`: capability exchange polling.

Installed module hash with the finer stage-7 DMA split:

    slim-qcom-ngd-ctrl.ko  8171a871ad691c03ef2ab64fc5332312c0eae561f8961717b3c570455008f53a

The next low-risk test is:

    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=1 spx_power_resp_type=1

If that passes, reboot before trying step 2. Do not jump to step 4
again until steps 1-3 identify whether the reset starts at channel
request, coherent allocation, or RX descriptor issue.

Additional runtime clue: during the reset-prone full RX+TX DMA test,
the Surface keyboard/trackpad stopped responding almost immediately,
while kernel logging continued long enough to print BAM cleanup and DPU
frame-done timeouts. That argues against a CPU lockup or Linux panic.
It points instead at a shared fabric/power/clock side effect: the
display controller and SPI HID path both become unhealthy while the
kernel can still run and log.

The audio BAM is `qcom,controlled-remotely` and the logs show
`controlled=1 powered=0`, so the generic BAM driver is not taking the
`powered_remotely` full BAM software-reset path on channel release.
The suspect operations are now narrower:

- requesting/releasing a pipe on a remotely controlled BAM, including
  per-pipe reset and IRQ-mask writes during free;
- allocating/freeing coherent memory for that DMA path;
- issuing RX descriptors to the remote-controlled BAM;
- adding TX channel allocation on top of active RX descriptors.

The finer stage-7 steps should be interpreted with the keyboard/display
clue in mind. If keyboard/trackpad dies at step 1, the problem is
already in DMA pipe request/release cleanup. If it survives steps 1-2
but dies at step 3, the trigger is RX descriptor issue. If it only dies
at step 4, the trigger is full RX+TX state.

Follow-up: `spx_stage7_step=1` completed cleanly. It powered the NGD
through QMI, read the safe status registers, requested RX DMA pipe 3,
allocated the BAM FIFO, released the channel, reset the pipe, updated
the IRQ mask/P_IRQ_EN, and stopped before SLIM registration:

    SPX: stage 7 controlled DMA step=1
    SPX: stage 7 step 1: requesting RX DMA channel
    SPX: BAM alloc[1] pipe=3 active_before=0 controlled=1 powered=0
    SPX: stage 7 step 1: RX channel=... chan_id=3
    SPX: BAM free pipe=3 reset begin
    SPX: BAM free pipe=3 reset done
    SPX: BAM free pipe=3 IRQ mask write done
    SPX: BAM free pipe=3 P_IRQ_EN disabled
    SPX: stage 7 step 1: RX channel released

This rules out basic RX pipe request/release and the pipe-3 cleanup
writes as the immediate reset/display-input trigger. The next boundary
is RX coherent buffer allocation/free at `spx_stage7_step=2`.

Follow-up: `spx_stage7_step=2` completed cleanly. It added coherent RX
buffer allocation/free on top of the step-1 RX pipe lifecycle:

    SPX: stage 7 controlled DMA step=2
    SPX: stage 7 step 2: RX channel + coherent buffer
    SPX: BAM alloc[1] pipe=3 active_before=0 controlled=1 powered=0
    SPX: stage 7 step 2: RX buffer phys=0x00000000ffff7000 size=1280
    SPX: BAM free pipe=3 reset done
    SPX: BAM free pipe=3 P_IRQ_EN disabled
    SPX: stage 7 step 2: RX resources released

This rules out coherent RX buffer allocation/free as the immediate
trigger. The next boundary is `spx_stage7_step=3`, which posts and
issues RX DMA descriptors before cleanup. If keyboard/display fails at
step 3, the unsafe operation is likely `dma_async_issue_pending()` /
`BAM_P_EVNT_REG` on RX pipe 3 rather than channel allocation or buffer
allocation.

Reboot is required between these tests even though the driver is a
module because successful `SELECT_INSTANCE`/`POWER_ACTIVE` mutates
ADSP-owned SLIMbus state. Earlier unload attempts released the QMI
client/power vote and triggered crashes/resets, so the diagnostic
module pins itself after QMI mutation. Reboot is the controlled way to
reset both Linux module state and ADSP firmware state.

Follow-up: the old `spx_stage7_step=3` failed. The visible tail showed
that RX pipe 3 had become initialized, cleanup completed, and then the
display controller started timing out while keyboard/trackpad were
already unusable:

    SPX: BAM terminate pipe=3 reinit done head=0 tail=0
    SPX: BAM free pipe=3 begin active=1 initialized=1 head=0 tail=0
    SPX: BAM free pipe=3 P_IRQ_EN disabled
    SPX: RX DMA channel released
    SPX: freeing RX DMA buffer phys=0x00000000ffff7000 size=1280
    SPX: stage 7 step 3: RX DMA cleanup done
    SPX: stopping after controlled stage 7 before SLIM registration
    [drm:dpu_encoder_frame_done_timeout] [dpu error]enc33 frame done timeout

Since step 2 was safe and the failed step had `initialized=1`, the
suspect operation is now specifically the hardware kick of RX
descriptors, not channel allocation or coherent buffer allocation.
The code was split again so descriptor preparation/submission can be
tested separately from `dma_async_issue_pending()` / `BAM_P_EVNT_REG`:

- `spx_stage7_step=3`: prepare and submit RX descriptors, but skip
  `dma_async_issue_pending()`.
- `spx_stage7_step=4`: issue pending RX descriptors, then cleanup.
  This is equivalent to the reset-prone old step 3.
- `spx_stage7_step=5`: full RX+TX DMA init, then cleanup.
- `spx_stage7_step=6`: full DMA init plus NGD_CFG enable.
- `spx_stage7_step=7`: capability exchange polling.

Installed module hash with RX descriptor submit/issue split:

    slim-qcom-ngd-ctrl.ko  36e2970934ecb95113dd339a028f65dc945a6d4a5da29352c71c913743abc008

The next test is the new, safer step 3:

    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=3

If this passes, the failing operation is almost certainly the
`dma_async_issue_pending()` path that initializes pipe 3 and writes
`BAM_P_EVNT_REG`.

Follow-up: the new `spx_stage7_step=3` passed. It prepared and
submitted all 32 RX DMA descriptors, skipped `issue_pending`, then
cleaned up with `initialized=0`:

    SPX: RX desc[31] submitted cookie=33
    SPX: RX DMA descriptors submitted; issue_pending skipped
    SPX: stage 7 step 3: RX descriptors submitted without hardware issue
    SPX: BAM terminate pipe=3 begin initialized=0 head=0 tail=0
    SPX: BAM free pipe=3 begin active=1 initialized=0 head=0 tail=0
    SPX: stage 7 step 3: RX DMA cleanup done

This rules out QMI, RX channel allocation, coherent RX buffer
allocation, descriptor preparation, descriptor submission, and cleanup
when the pipe has not been started. The reset/display/input failure is
now isolated to the RX hardware issue path: `dma_async_issue_pending()`
causes BAM pipe 3 initialization and eventually the `BAM_P_EVNT_REG`
write. The next diagnostic should not repeat a broad step 4; it should
split BAM start into "initialize pipe registers" and "write EVNT_REG"
inside `drivers/dma/qcom/bam_dma.c`.

The BAM DMA driver is built into the kernel (`CONFIG_QCOM_BAM_DMA=y`),
so the BAM start split required a kernel image rebuild rather than a
module swap. Two built-in parameters were added:

- `bam_dma.spx_bam_start_pipe=3` selects RX pipe 3 by default
  (`-1` means all pipes).
- `bam_dma.spx_bam_start_stop=0` is normal behavior.
- `bam_dma.spx_bam_start_stop=1` enters `bam_start_dma()`, initializes
  pipe hardware, then returns before descriptor dequeue/FIFO queueing
  and before `BAM_P_EVNT_REG`.
- `bam_dma.spx_bam_start_stop=2` queues descriptors into the BAM FIFO,
  then returns before `BAM_P_EVNT_REG`.

Installed kernel image with the BAM start split:

    /boot/vmlinuz-linux-surface  5a27039060b28823cbff8965b9562a27fcbd92aab113466bffffd1de02437e8b
    backup: /boot/vmlinuz-linux-surface.20260611-151023

After reboot, first confirm the params exist:

    ls /sys/module/bam_dma/parameters/

Then test pipe initialization only:

    echo 1 | sudo tee /sys/module/bam_dma/parameters/spx_bam_start_stop
    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=4

If that passes, reboot and test FIFO queueing without EVNT_REG:

    echo 2 | sudo tee /sys/module/bam_dma/parameters/spx_bam_start_stop
    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=4

If stop=1 and stop=2 both pass but normal stop=0 fails at step 4, the
bad operation is the `BAM_P_EVNT_REG` write itself.

Follow-up: `bam_dma.spx_bam_start_stop=1` with stage-7 step 4 passed.
This allowed `dma_async_issue_pending()` to enter `bam_start_dma()` and
initialize RX pipe 3, but stopped before descriptor dequeue/FIFO
queueing and before `BAM_P_EVNT_REG`:

    SPX: BAM start diagnostic stop=1 pipe=3: init only, skip descriptor dequeue/EVNT_REG
    SPX: BAM pipe=3 writing P_RST assert/deassert
    SPX: BAM pipe=3 writing DESC_FIFO_ADDR=0x00000000ffff8000 FIFO_SIZE=32760
    SPX: BAM pipe=3 writing P_IRQ_EN=0x31
    SPX: BAM pipe=3 writing IRQ mask=0x8
    SPX: BAM pipe=3 writing P_CTRL=0x2a
    SPX: BAM pipe=3 init_hw done head=0 tail=0
    SPX: stage 7 step 4: RX DMA cleanup done

This rules out RX pipe initialization itself, including P_RST,
descriptor FIFO address/size, P_IRQ_EN, IRQ mask unmask, and P_CTRL.
The next boundary is FIFO descriptor queueing without `BAM_P_EVNT_REG`:

    echo 2 | sudo tee /sys/module/bam_dma/parameters/spx_bam_start_stop
    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=4

Follow-up: `bam_dma.spx_bam_start_stop=2` with stage-7 step 4 also
passed. This initialized RX pipe 3, copied all 32 descriptors into the
BAM FIFO, and stopped immediately before `BAM_P_EVNT_REG`:

    SPX: BAM start[1] pipe=3 queued cookie=33 new_tail=32 desc_list_empty=0
    SPX: BAM start diagnostic stop=2 pipe=3: queued FIFO tail=32, skip EVNT_REG
    SPX: stage 7 step 4: RX DMA cleanup done

This rules out descriptor FIFO queueing. The only remaining operation
from the failing path is the final `BAM_P_EVNT_REG` write that starts
RX pipe 3 consuming the queued descriptors.

The queued descriptor addresses are suspiciously close to the top of
the 32-bit IOVA aperture:

    RX buffer:        0x00000000ffff7000
    BAM descriptor FIFO: 0x00000000ffff8000

Both `slim-ngd` and `slimbam` use the same apps SMMU stream ID
(`0x1806`), so these are IOVAs, not necessarily physical RAM
addresses. To test whether starting RX DMA at the top of the 32-bit
IOVA space is what poisons display/SPI HID, the next build adds mask
knobs applied immediately before allocation:

- `bam_dma.spx_bam_dma_mask_bits`: applied before BAM descriptor FIFO
  allocation.
- `slim_qcom_ngd_ctrl.spx_dma_mask_bits`: applied before SLIM RX/TX
  coherent buffer allocation.

Installed build with DMA-mask knobs:

    /boot/vmlinuz-linux-surface  d4e1778a1468d52ec63ba784c9897136049a002cd1dc97482a97e4bcf4ac87d1
    slim-qcom-ngd-ctrl.ko        9b61c343b48ec5a0b63ac08faa3666c2a71db52bbb13e66beb1a496d30744c45
    valid kernel backup: /boot/vmlinuz-linux-surface.20260611-151023

Note: `/boot` was full, so an attempted new backup at
`/boot/vmlinuz-linux-surface.20260611-152539` was truncated and then
removed. The older valid backup remains.

After reboot, first confirm the new params exist, then force lower
IOVAs and retest the normal EVNT_REG path:

    ls /sys/module/bam_dma/parameters/
    echo 31 | sudo tee /sys/module/bam_dma/parameters/spx_bam_dma_mask_bits
    sudo modprobe slim_qcom_ngd_ctrl spx_dma_mask_bits=31 spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=4

If the logged RX/FIFO DMA addresses move away from `0xffff....` and
normal step 4 no longer breaks display/input, the practical fix is to
constrain the SLIM/BAM IOVA aperture for this hardware.

Follow-up: first boot with the DMA-mask build did not exercise the DMA
path because the module was loaded with `spx_stage7_step=0`:

    spx_dma_mask_bits=31
    bam_dma.spx_bam_dma_mask_bits=31
    spx_probe_stage=7
    spx_stage7_step=0

The QMI/read boundary still passed, but no RX/BAM allocation happened,
so the IOVA-mask hypothesis remains untested. The next run must include
`spx_stage7_step=4` in the initial `modprobe` command; changing the
parameter after probe does not rerun the staged path.

Follow-up: the same missed-step condition happened again. Live params
showed:

    spx_dma_mask_bits=31
    bam_dma.spx_bam_dma_mask_bits=31
    spx_probe_stage=7
    spx_allow_dma=Y
    spx_stage7_step=0

There was no config file overriding `spx_stage7_step`, so the load
command simply did not apply `spx_stage7_step=4`. A helper script was
added to avoid another mistyped command:

    scripts/spx-stage7-step4-mask-test.sh

Run it after a clean reboot. It refuses to run if
`slim_qcom_ngd_ctrl` is already loaded, writes
`bam_dma.spx_bam_dma_mask_bits=31`, and invokes:

    modprobe -v slim_qcom_ngd_ctrl spx_dma_mask_bits=31 spx_probe_stage=7 spx_allow_dma=1 spx_stage7_step=4

Follow-up: the first real mask run still reset the device and the tail
still showed the same top-of-32-bit IOVAs:

    RX buffer:        0x00000000ffff7000
    BAM descriptor FIFO: 0x00000000ffff8000

That means the run did not prove the mask hypothesis; either the DMA
mask was not constraining the IOMMU allocator, or another device limit
was still allowing allocation at the top of the 32-bit aperture. The
diagnostic build was updated to set and log both the DMA/coherent mask
and `dev->bus_dma_limit` before the SLIM RX/TX coherent allocations and
the BAM descriptor FIFO allocation.

Installed build with stronger DMA-limit logging:

    /boot/vmlinuz-linux-surface  d6124bba649b2e9546664d8aca44c1d70f2f930f10517523cfa3735fa51ee5b8
    slim-qcom-ngd-ctrl.ko        d52f9a7f062c1ef0d86ba4c74e958e93e2655e56f29e4e6c81acacbdaa8aa4ca
    module backup: /lib/modules/6.18.3-1-surface+/kernel/drivers/slimbus/slim-qcom-ngd-ctrl.ko.20260611-170312
    valid kernel backup: /boot/vmlinuz-linux-surface.20260611-151023

The helper script now also writes:

    echo 2 | sudo tee /sys/module/bam_dma/parameters/spx_bam_start_stop

So the next run is a safe observation run: pipe init and descriptor FIFO
queueing happen, but the final `BAM_P_EVNT_REG` write is skipped. The
important result is whether the log shows the new `SLIM DMA limits` and
`BAM ... DMA limits` lines and whether the RX/FIFO IOVAs move below the
old `0xffff....` range. Only if they move should the final EVNT_REG
path be retried with `spx_bam_start_stop=0`.

Follow-up: the safe stop=2 run with 31-bit masks completed and moved
the allocations below bit 31:

    RX buffer:           0x000000007fff7000
    BAM descriptor FIFO: 0x000000007fff8000

The SLIM module showed the new full limit log:

    SLIM DMA limits bits=31 mask 0xffffffff->0x7fffffff coherent 0xffffffff->0x7fffffff bus 0xfffffffff->0x7fffffff

The BAM path still printed the older `using DMA mask bits=31` message in
that boot, but the FIFO allocation moved to `0x7fff8000`, so the BAM
mask was effective for this test. The helper now accepts environment
overrides:

    SPX_DMA_BITS=31 SPX_BAM_START_STOP=0 ./scripts/spx-stage7-step4-mask-test.sh

That is the next risky test: same below-bit31 IOVAs, but allow the final
`BAM_P_EVNT_REG` write that previously reset display/input when the
descriptors lived at `0xffff....`.

Follow-up: the `SPX_BAM_START_STOP=0` run froze/reset before any stage-7
or QMI breadcrumbs appeared. The only observed line was:

    SPX: NGD child id=1 base_offset=0x1000

This means the last visible point was parent-side child creation, before
the existing logs in the child probe path. A module-only breadcrumb build
was installed to bracket the next boundary:

    slim-qcom-ngd-ctrl.ko        ca9ca07b88732adfe6c53f5106696fa78bffbc57361ada805d94d5132a13c4bc
    module backup: /lib/modules/6.18.3-1-surface+/kernel/drivers/slimbus/slim-qcom-ngd-ctrl.ko.20260611-173219

New breadcrumbs include:

    SPX: platform_device_add begin/done for NGD child
    SPX: driver_set_override begin/done for NGD child
    SPX: child probe entry
    SPX: child probe: runtime PM setup begin/done
    SPX: qmi_svc_event_init: qmi_handle_init begin/done
    SPX: qmi_svc_event_init: qmi_add_lookup begin/done
    SPX: child probe: waiting for qmi_up completion
    SPX: child probe: enable begin/done

Because this is a module-only update and the module is not loaded after
the reset, no reboot is needed before the next run.

Follow-up: that breadcrumb run reset with the final visible line:

    SPX: qmi_svc_event_init: qmi_handle_init begin

So the reset occurred before service lookup, select_instance, power, or
DMA. The real service-event handle was using `qmi_handle_init(..., 0,
ops, NULL)`, while the standalone `slimbus_qmi_probe` used a nonzero
receive length. The next module build changes the service-event handle
to use `SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN` and adds a bypass path that
skips service lookup entirely and uses the previously observed SLIMbus
QMI endpoint:

    node=5 port=11

Installed module:

    slim-qcom-ngd-ctrl.ko        ec73de354b9937497c66ea6370b7db3f7f8821446772ea744812f4371eeeb800
    module backup: /lib/modules/6.18.3-1-surface+/kernel/drivers/slimbus/slim-qcom-ngd-ctrl.ko.20260611-174301

New module params:

    spx_qmi_bypass_lookup=1
    spx_qmi_node=5
    spx_qmi_port=11

First run only the no-DMA bypass probe:

    scripts/spx-stage7-bypass-step0.sh

It loads stage 7 step 0, so it performs direct QMI select/power and
safe NGD reads, then stops before DMA allocation.

Follow-up: bypass step 0 succeeded. The direct QMI handle initialized,
connected to node 5 port 11, selected the instance, powered the SLIMbus
core active, and read safe NGD registers:

    ver=0x202 status=0x40c cfg=0x0 rx_msgq=0x0

This proves the reset at `qmi_svc_event_init: qmi_handle_init begin` is
specific to the service-discovery handle path. Direct QMI request handle
init/connect/power is still viable when the endpoint is supplied
manually.

A bypass step-4 helper was added:

    scripts/spx-stage7-bypass-step4.sh

It defaults to:

    spx_qmi_bypass_lookup=1
    spx_qmi_node=5
    spx_qmi_port=11
    spx_dma_mask_bits=31
    bam_dma.spx_bam_dma_mask_bits=31
    bam_dma.spx_bam_start_stop=2
    spx_probe_stage=7
    spx_stage7_step=4

So the next run tests the safe descriptor queueing path with lookup
bypassed and with below-bit31 IOVAs. If that passes, set
`SPX_BAM_START_STOP=0` on the same helper to retry the final EVNT_REG
write with the lookup bypass and the 31-bit DMA aperture.

Follow-up: bypass step 4 with `SPX_BAM_START_STOP=2` succeeded. The
service lookup was bypassed, direct QMI power succeeded, RX/BAM coherent
allocations were constrained below bit 31, all 32 RX descriptors were
queued into the BAM descriptor FIFO, and cleanup completed:

    RX buffer:           0x000000007fff7000
    BAM descriptor FIFO: 0x000000007fff8000
    BAM start diagnostic stop=2 pipe=3: queued FIFO tail=32, skip EVNT_REG
    stage 7 step 4: RX DMA cleanup done

The remaining risky boundary is now only the final `BAM_P_EVNT_REG`
write with lookup bypassed and below-bit31 IOVAs:

    SPX_BAM_START_STOP=0 ./scripts/spx-stage7-bypass-step4.sh

Follow-up: the `SPX_BAM_START_STOP=0` run froze the device but did not
autonomously reset. The device remained frozen for about one minute
until a manual hard reset was performed.

This is a distinct failure mode from the earlier automatic resets:

- QMI service lookup was bypassed.
- Direct QMI select/power had already been proven working.
- RX/BAM IOVAs were constrained below bit 31.
- Descriptor FIFO queueing had already been proven working with
  `SPX_BAM_START_STOP=2`.
- The only newly enabled operation was the final `BAM_P_EVNT_REG` write
  that starts RX pipe 3 consuming the queued descriptors.

Current conclusion: the remaining platform wedge is caused by starting
the RX BAM pipe/SLIMbus RX transaction itself, not by QMI lookup, QMI
power, descriptor allocation/submission, descriptor FIFO queueing, or the
old `0xffff....` IOVA placement.

## New direction: PIO/FIFO messaging mode (no BAM, no INT_EN)

Plan: /home/dvitali/.claude/plans/read-docs-spx-audio-2026-06-11-findings-generic-flute.md

Since both fatal operations (NGD_INT_EN arm, BAM pipe start) are only
needed for the *message transport*, and audio data itself is mastered by
the ADSP on the bus, `spx_pio_mode=1` was added to qcom-ngd-ctrl.c:

- TX: message words written to NGD child FIFO at +0x30, completion by
  polling INT_STAT TX_MSG_SENT (W1C by TX path only).
- RX: kthread `spx_slim_pio` polls INT_STAT; on RX_MSG_RCVD reads the
  RX FIFO at +0x70 (pops on read), clears BIT(30), dispatches into
  qcom_slim_ngd_rx(). Heartbeat-logs INT_STAT/STATUS/CFG for 30s.
- NGD_CFG written as ENABLE only (msgq bits masked). No dma_request_chan
  at all. INT_EN stays 0. IRQ handler is observe-only in PIO mode.
- Capability wait sends proactive REPORT_SATELLITE via m_work after
  300ms, then 1/s (spx_pio_cap_retries, default 3).
- Fallbacks: spx_pio_tx_nowait=1 (blind 2ms TX delay) if TX_MSG_SENT
  never latches; spx_pio_debug_reads=1 for one-shot IE/VE_STAT reads.

Installed module with PIO mode:

    slim-qcom-ngd-ctrl.ko  592f8d00e006a9276372ce9ca7013f2c320f343cf8ea543023da8abc608db780

Run 1 (about to execute; service 0x301 confirmed at node=5 port=11):

    sudo modprobe slim-qcom-ngd-ctrl spx_probe_stage=7 spx_stage7_step=7 \
        spx_pio_mode=1 spx_qmi_bypass_lookup=1 spx_qmi_node=5 spx_qmi_port=11 \
        spx_power_resp_type=-1 spx_pio_cap_retries=3

If this boot ends in a wedge with no further notes here: the last line
in the journal attributes it (CFG-enable write vs first TX FIFO write vs
RX FIFO read — each has a distinct pre-log). Decision tree is in the plan
file. Module pins itself on success or QMI-mutation; reboot before Run 2
(stage 8 + spx_allow_full=1 + spx_pio_mode=1).

### Run 1 RESULT: SUCCESS — capability exchange completed over PIO

Log tail (2026-06-11 19:12):

    SPX: stage 7 PIO writing NGD_CFG=0x1 (enable, msgqs off)
    SPX: stage 7 PIO NGD_CFG readback=0x1 int_stat=0x0
    SPX: PIO poll thread started
    SPX: PIO RX stat=0x40000000 rl=7 words=2 data=c7 00 ff d9 c5 01 01 00
    SPX: rx msg mt=0x6 mc=0x0 len=7
    SPX: PIO TX first-ever FIFO write: words=2 w0=0xd9ff01c7 to child+0x30
    SPX: PIO capability exchange done status=0x240e int_stat=0x0
    SPX: stage 7 PIO capability exchange DONE

Established facts:

- `NGD_CFG = ENABLE` with msgq bits off is safe (no reset).
- The ADSP master broadcasts MASTER_CAPABILITY immediately and
  unsolicited on NGD enable; RX FIFO at child+0x70 works; INT_STAT
  latches RX_MSG_RCVD/TX_MSG_SENT with INT_EN=0 (fully pollable).
- TX FIFO at child+0x30 works; REPORT_SATELLITE was acked by hardware
  (TX_MSG_SENT) on the first try; no NACK.
- NGD_STATUS went 0x40c -> 0x240e: NGD_LADDR (BIT 1) set, the NGD is
  enumerated on the bus.
- No proactive capability kick was needed (spx_pio_cap_retries unused).

The BAM and NGD_INT_EN are simply not needed for control messaging on
this firmware. Next: reboot (module is pinned), then Run 2:

    sudo modprobe slim-qcom-ngd-ctrl spx_probe_stage=8 spx_pio_mode=1 \
        spx_allow_full=1 spx_qmi_bypass_lookup=1 spx_qmi_node=5 \
        spx_qmi_port=11 spx_power_resp_type=-1

or simply (discovers node/port dynamically, refuses a dirty boot):

    ./scripts/spx-run2-pio-full.sh

then:

    ls /sys/bus/slimbus/devices            # expect 0:1 ... 217:250
    cat /proc/asound/cards                 # expect "Surface Pro X"
    aplay -l

Run-1 soak: stable through +2 min (historic delayed resets all hit
within ~60 s), zero DPU errors, heartbeat ended on schedule at +30 s.

### Run 2 RESULT: SLIM controller registered; codec absent from bus

After reboot, `scripts/spx-run2-pio-full.sh` (stage 8, PIO) completed:
capability exchange again instant, `SLIM controller Registered`,
`/sys/bus/slimbus/devices` = `217:250:0:0` (ifd) + `217:250:1:0` (codec).
`modprobe wcd934x` bound (all supplies dummy), but the post-probe
ADDR_QUERY got a valid ADDR_REPLY whose payload was ALL ZEROS:

    SPX: PIO RX stat=0x40000000 rl=11 words=3 data=cb 0e ff 01 00 00 00 ...
    wcd934x-slim 217:250:1:0: Failed to get logical address

Meaning: PIO transport is fully functional (request out, reply in); the
bus MASTER does not know the codec's enumeration address — the WCD9340
never announced (REPORT_PRESENT) on the physical bus.

### Root cause found in ACPI: codec reset GPIO = TLMM 143

From /tmp/acpidumps/surface_pro_x_sq2/dsdt.dsl (linux-surface/acpidumps),
`\_SB.ADSP.SLM1.ADCM.AUDD` (SLM1 = slim@171c0000) carries in _CRS:

- GpioIo on \_SB.GIO0 pin 0x8F (143), PullNone — codec SYS_RST_N
- GpioInt Edge ActiveHigh pin 0x100 — MBHC/jack class interrupt
- SpiSerialBusV2 on \_SB.SPI4 — the WDSP/SPI side channel (origin of the
  old "SPI Aqstic" confusion)

Also: TLMM gpios 149-151 are already muxed func1 = `lpass_slimbus` by
boot firmware (152 left as gpio/pull-down, likely unused DATA2), so the
external bus pads were never the blocker.

Fix landed: `reset-gpios = <&tlmm 143 GPIO_ACTIVE_HIGH>` added to the
wcd9340 node in sc8180x-wcd9340.dtsi (the wcd934x driver then does the
proper 20ms low / 20ms high sequence in probe). New DTB installed:

    /boot/dtb/qcom/sc8180x-surface-pro-x.dtb
        37615b47d8a4cec10d5c76ff338778eb0d57ca711addf981a9df15a3cedfe5cc
    backup: /boot/dtb/qcom/sc8180x-surface-pro-x.dtb.20260611-194600

### HAZARD: do not read pinctrl debugfs pin listings on this kernel

`sudo grep ... /sys/kernel/debug/pinctrl/3100000.pinctrl/pinmux-pins`
OOPSed in `msm_get_group_name` (pinmux_pins_show) and the dead reader
left the pinctrl mutex held. Every subsequent pinctrl/GPIO operation —
including driver binds that apply pinctrl-0 and all gpioset/gpioget —
then hangs in uninterruptible D state. The boot is unrecoverable except
by reboot. Do NOT read `pinmux-pins`/`pins`/`pinconf-pins` there again
(`pinmux-select` writes use a different path). Upstream bug worth fixing
separately; userspace GPIO reset pulses also became moot once
reset-gpios moved into the DT.

### Next boot procedure (one command)

    ./scripts/spx-run2-pio-full.sh

now does: stage-8 PIO bring-up -> wcd934x modprobe (driver pulses TLMM
143 reset) -> prints slimbus devices, dmesg tail, /proc/asound/cards,
aplay -l. Expected: ADDR_REPLY with non-zero payload, wcd934x full mfd
probe, sdm845-sndcard machine driver binds, card "Surface Pro X".

After the card appears, first-sound mixer sequence (C630/sdm845 UCM as
reference):

    amixer -c 0 cset name='SLIMBUS_0_RX Audio Mixer MultiMedia1' 1
    amixer -c 0 cset name='SLIM RX0 MUX' AIF1_PB
    amixer -c 0 cset name='SLIM RX1 MUX' AIF1_PB
    amixer -c 0 cset name='RX INT1_1 MIX1 INP0' RX0
    amixer -c 0 cset name='RX INT2_1 MIX1 INP0' RX1
    amixer -c 0 cset name='RX INT1 DEM MUX' CLSH_DSM_OUT
    amixer -c 0 cset name='RX INT2 DEM MUX' CLSH_DSM_OUT
    speaker-test -c 2 -t wav -l 2

(exact control names via `amixer -c 0 scontrols` once the card exists;
HPH first, LINEOUT variants if silent — speakers hang off the codec's
analog outputs per the no-WSA topology.)

### Run 3 RESULT: codec ALIVE, card registered — then GPIO 54 storm reset

With reset-gpios on TLMM 143 the codec enumerated and identified:

    wcd934x-slim 217:250:1:0: WCD934x chip id major 0x108, minor 0x1

Regmap I/O over PIO worked (ADDR_REPLY/REPLY_VALUE traffic clean). After
`modprobe snd_soc_wcd934x snd_soc_sdm845`:

    0 [X]: sdm845 - Surface Pro X

Then, with PipeWire probing the card and mixer enumeration running, the
machine slowed, keyboard/trackpad (SPI-HID) died, subsystems restarted
(modem SSR, ath10k re-init, GMU reload, spi_hid reading all-00/all-ff),
and the platform reset.

**Root cause: the codec node's `interrupts-extended = <&tlmm 54>` +
`bias-pull-down` pinctrl — copied from sdm845 — landed on the SPX's
SPI-HID RESET line** (`spi1_hid0_reset_assert/deassert` in the board dts
both use gpio54). The wcd934x MFD requests a LEVEL_HIGH IRQ on it; any
high level (e.g. spi_hid's own error recovery asserting reset) becomes
an IRQ storm feeding a HID-reset loop until the platform dies. The DSDT
says the real codec INTR is GpioInt pin 0x100 (unresolved — NOT a valid
TLMM pin number; possibly PMIC-side). NEVER point audio at GPIO 54.

Fixes landed (all installed):

- sc8180x-wcd9340.dtsi: codec IRQ + wcd_intr_default pinctrl REMOVED;
  codec runs IRQ-less (no MBHC — the SPX has no jack anyway).
- drivers/mfd/wcd934x.c: IRQ now optional (skips regmap-irq chip).
- sound/soc/codecs/wcd934x.c: guards for NULL irq_data (skips MBHC and
  the SLIM port irq); wcd_mbhc_event_notify already NULL-safe.
- qcom-ngd-ctrl.c: per-message PIO RX logging now behind
  spx_pio_verbose (default off) — regmap traffic was flooding printk.
- scripts/spx-run2-pio-full.sh now goes all the way: stage-8 PIO ->
  wcd934x -> snd_soc_wcd934x + snd_soc_sdm845 -> mixer path
  (MultiMedia1->SLIMBUS_0_RX, SLIM RX0/1->AIF1_PB, RX INT1/2->HPH dem,
  RX INT3/4->LINEOUT) -> speaker-test.

Installed hashes:

    /boot/dtb/qcom/sc8180x-surface-pro-x.dtb
        45c1496f9093e735f3ef762627da6ecbfff93936902551cff218f32774dffced
    slim-qcom-ngd-ctrl.ko
        25afd26f21131ec91bdc9e6386c6db7f695ad217607dec4a8a0909d2f843ab2f
    wcd934x.ko (mfd)
        a054aa676a38896d9c1f40a51be07a00f8118f06e6173067bae6059a328b0a05
    snd-soc-wcd934x.ko
        0053420dd7876d4a41a3b74babf33393305a7c8223244ad6634384265f42406e

Next boot: `./scripts/spx-run2-pio-full.sh` (expect dev_warn lines about
"No IRQ / no MBHC" — correct), listen for the speaker-test tone. If the
tone path is silent on both HPH and LINEOUT despite a running stream
(check `cat /proc/asound/card0/pcm0p/sub0/status`), next suspects are a
speaker-amp enable (PMIC GPIO?) and DAPM endpoint routing in the sound
node (add "Speaker"/"Line Out" audio-routing entries).

### Run 4 RESULT: full path ran, ADSP died at audio-data start

The IRQ-less bring-up worked (no gpio54 involvement, keyboard stayed
alive). speaker-test started and the platform collapsed seconds later.
User-captured dmesg (journal tail lost again to "Time jumped backwards"
rotation — the new script runs a journalctl --sync loop during playback
to fix this):

    SPX: PIO heartbeat int_stat=0x1000000 status=0x4240e cfg=0x1
    [drm:dpu_encoder_frame_done_timeout] ... (repeating)
    TX timed out:MC:0x2e,mt:0x2 / Tx:MT:0x2, MC:0x2e, LA:0xcf failed:-110
    qcom-q6afe aprsvc:service:4:4: AFE close failed -110
    SPX: PIO heartbeat int_stat=0x1000000 status=0x5c40e cfg=0x1

Decode:

- int_stat bit 24 = RECFG_DONE latched: the whole control sequence —
  CONNECT_SINK, DEFINE/ACTIVATE channel, RECONFIGURE_NOW — completed
  over PIO and the master reconfigured the bus. NGD_STATUS 0x240e ->
  0x4240e -> 0x5c40e shows the data channel/ports going active.
- LA 0xcf = the master's logical address (seen in all replies).
- The MC:0x2e (DISCONNECT_PORT) timeouts are TEARDOWN failing after the
  ADSP already stopped answering; AFE close -110 = APR timeouts = the
  ADSP audio service was dead/hung. aplay saw an I/O error.
- DPU frame-done timeouts = the usual fabric-distress canary; the PIO
  heartbeat kept running throughout (SLIMbus MMIO stayed alive).

Conclusion: the wedge fires when ADSP-driven AUDIO DATA starts flowing
(AFE port + active bus channel), not in the control plane. Same class
as the old BAM EVNT_REG wedge — the common denominator across both is
LPASS-side DMA/data activity, ADSP firmware hangs/crashes and takes
fabric/RPMh handshakes with it.

Candidate causes (untested): missing calibration/topology data the MSFT
AFE expects before port start; q6afe slim config mismatch (mainline
never sets slimbus_dev_id — stays 0 = AFE_SLIMBUS_DEVICE_1; q6afe.c:1331
q6afe_slim_port_prepare); an LPASS resource Windows' PEP0 votes that
Linux doesn't; clock-gear/bandwidth of the 48k stereo channel.

### Next test ladder (scripts/spx-run2-pio-full.sh, one step per boot
### unless a step survives)

1. `SPX_TEST=mute ./scripts/spx-run2-pio-full.sh` — 1s playback with
   codec SLIM RX muxes at ZERO: AFE + bus channel data start without the
   codec analog stage. Wedge => AFE/bus-level fault (try slimbus_dev_id=1
   patch in q6afe_slim_port_prepare next, then 8k mono). Survival =>
   analog side (PA inrush/micbias) — retry full path with HPH only and
   low volumes.
2. `SPX_TEST=slim ./scripts/spx-run2-pio-full.sh` — full audible 1s.
3. A journal sync loop runs during playback so the next collapse leaves
   evidence. DP-route bisection is NOT possible (card has no
   DISPLAY_PORT_RX backend dai-link).

Open question for the user: was ANY sound audible before the collapse?
If yes, the entire path incl. amplification is proven and only the
data-start stability remains.

### Run 5 (same-boot mute tests): DSP refuses START with error 9; NO wedge

IRQ-less bring-up clean again (chip id, card, "no MBHC" warns as
designed). Two mute-test attempts (codec muxes ZERO) both failed at:

    qcom-q6afe: cmd = 0x100e5 (AFE_PORT_CMD_DEVICE_START) error = 0x9
    AFE enable for port 0x4000 failed -22  (SLIMBUS_0_RX)

and the machine stayed perfectly healthy through both (PCM closed after,
no holders, PipeWire never adopted the card - Dummy Output only).

Findings:

- First attempt used Front_Center.wav = MONO; the stereo retry also got
  error 9, so the port state was already poisoned by then. Error 0x9 per
  downstream numbering = ADSP_EALREADY ("already processed") - the DSP
  considers the port started, and since the apps side never marked it
  started, q6afe never sends a STOP -> stuck until ADSP restart. Our
  pinned driver does not survive ADSP restart -> reboot is the cleanup.
- A REFUSED start is completely harmless: APR healthy, no fabric stress.
  Whatever wedges the platform happens only when a start is ACCEPTED and
  the q6asm frontend feeds real samples.
- Sharpened wedge theory: when real samples flow, the ADSP reads the PCM
  buffer from DDR through apps_smmu SID 0x1821 (`iommus` on q6asmdai).
  A SID/translation mismatch there = ADSP-side AXI fault = fabric wedge,
  the same failure class as the BAM descriptor-fetch wedge. The mute
  tests never reached q6asm data flow (START refused), hence no wedge.
- Mono WAVs are rejected by this firmware's AFE (likely channel-count vs
  2-slot ch-map mismatch) - playback tests must be stereo 48k S16. The
  script's play_short now uses `timeout 3 speaker-test -c 2 -t sine` and
  captures dmesg to /tmp/spx-test-dmesg.log, grepping smmu/fault/afe
  lines after, with the journal sync loop running.

### Next boot ladder

1. `./scripts/spx-run2-pio-full.sh` (bring-up + mixers, no playback)
2. `SPX_TEST=mute ./scripts/spx-run2-pio-full.sh` - stereo, analog off.
   - START accepted + survives => data flow OK muted; go to 3.
   - START accepted + wedge => check /tmp/spx-test-dmesg.log + journal
     for arm-smmu faults right before the DPU timeouts; if present, the
     q6asmdai SID 0x1821 mapping is the target (compare against the SPX
     IORT/ACPI; consider whether the WoA firmware expects S1 bypass).
   - error 9 again on a CLEAN boot => not stale state but a real
     config/cal refusal; next lever: set slimbus_dev_id explicitly in
     q6afe_slim_port_prepare (q6afe.c:1331), try DEVICE_2 (=1).
3. `SPX_TEST=slim ./scripts/spx-run2-pio-full.sh` - audible stereo tone.

### Run 6: THE KILLER IS THE STREAM-CLOSE PATH, NOT DATA START

Clean boot. SPX_TEST=mute: AFE DEVICE_START refused with error 9 again -
on the FIRST AFE command of the boot (no prior q6 activity, PipeWire
never adopted the card), stereo. So error 9 is NOT stale state.
Correlation so far: starts with codec muxes at ZERO get refused (2/2);
starts with muxes at AIF1_PB get accepted (2/2). Unexplained.

SPX_TEST=slim (muxes AIF1_PB): START ACCEPTED, speaker-test ran the full
3 s (tone audibility to be confirmed by user), then on close got stuck
in D state with wchan=snd_pcm_release; loadavg climbed past 17 with
tasks piling up behind it (sudo/dmesg wedged too). Same slow-motion
collapse as the original wedge run - which ALSO died right after
speaker-test finished and closed the stream (DISCONNECT_PORT timeouts,
AFE close -110).

CONCLUSION: data flow is fine; the platform dies in the STREAM TEARDOWN
sequence: q6afe port STOP / wcd934x slim_stream_disable (CHAN_CTRL +
RECONFIGURE_NOW + DISCONNECT_PORT to the master) - the ADSP stops
responding mid-teardown and the kernel piles up in uninterruptible
waits, ending in a platform reset.

Next levers (in order):
1. Determine which teardown step hangs: instrument wcd934x trigger STOP
   and q6afe_dai_shutdown with pre-logs; reorder (AFE STOP before codec
   slim disable, or vice versa); try skipping DISCONNECT_PORT/channel
   teardown entirely (leave channels defined - downstream keeps channels
   across stops in some modes).
2. Workaround for usable desktop audio meanwhile: never close the
   stream - PipeWire keeps the sink open; configure UCM/profile so the
   port starts once per boot and stays running.
3. Error 9 riddle: compare ZERO vs AIF1_PB mux state at START time -
   possibly DPCM powers DAPM before BE prepare in this flow; check
   whether wcd934x .startup/.hw_params (ch map?) behave differently
   when the path is unrouted.

### Teardown parking implemented (installed)

- sound/soc/codecs/wcd934x.c: `spx_persist_stream` param - trigger STOP
  skips slim_stream_disable/unprepare; START reuses the live stream
  (spx_stream_live flag); hw_params reuses the existing sruntime.
    snd-soc-wcd934x.ko 191a712e62154202d59495e11a6f86f3eee122ac6b3a79516cc6c3e04c54c386
- sound/soc/qcom/qdsp6/q6afe-dai.c: `spx_no_port_stop` param - shutdown
  leaves the port running (is_port_started stays true); prepare reuses a
  running port (config pinned at 48k/2ch/S16 by the BE fixup anyway).
    q6afe-dai.ko 1b47bc37c7376e399bef2ea4d5fa45c66f567d8eb8c61747da94c1ac406a94e5
- Script sets both params (modprobe arg + sysfs fallback) and the slim
  test now plays TWICE to prove the play->stop->play cycle.

### Run 7: wedge DURING play even with teardown parked -> causality fixed

With teardown parked, the slim test still collapsed the platform within
seconds of play start; the journal sync loop persisted exactly one sync
before IO died. Re-reading Run 4 with this lens: the DPU timeouts there
ALSO preceded the DISCONNECT/AFE-close errors. CONCLUSION: teardown was
never the killer - it merely times out because the system is already
dying. THE POISON IS THE DATA FLOW ITSELF.

### ROOT CAUSE FOUND: wrong SMMU StreamID for the audio path (IORT)

The SPX IORT (linux-surface/acpidumps, surface_pro_x_sq2/iort.dsl,
named component at line ~1300) maps `\_SB.ADSP.SLM1.ADCM` to the apps
SMMU (base 0x15000000) with output StreamIDs:

    0x1B21          (input 0x07030000) <- audio PCM buffer stream
    0x1B46          (input 0x07030001)
    0x1B4D count 4  (input 0x07030002)
    0x1B53          (input 0x0703000B)
    0x1B58          (input 0x0703000C)
    0x1B5C count 2  (input 0x0703000D)

Our DT had `iommus = <&apps_smmu 0x1821 0x0>` on q6asmdai - the sdm845
value. On sc8180x the bank is 0x1B, not 0x18. So the moment the ADSP
read the q6asm PCM buffer it emitted SID 0x1B21, the SMMU had no
matching stream entry, and the unmatched/stalled transaction wedged the
fabric (DPU canary first, then ADSP death, then platform reset). This
also explains the mapping-is-fine observation (mapping is apps-side
only) and almost certainly the ENTIRE BAM saga: slimbam/slim-ngd use
sdm845's 0x1806, which is presumably also 0x1Bxx on this firmware
(moot in PIO mode; candidates above, e.g. 0x1B46/0x1B4D).

Fix landed: sc8180x.dtsi q6asmdai `iommus = <&apps_smmu 0x1b21 0x0>`.

    /boot/dtb/qcom/sc8180x-surface-pro-x.dtb
        90487aee438ff10e3d1d296233fc890dd81475ac0f7993f5a836d784fa7053dc
    (backup .20260611-215528)

Next boot: `SPX_TEST=slim ./scripts/spx-run2-pio-full.sh` - with the
correct SID the ADSP's buffer reads translate; teardown parking stays
on for this run (one variable at a time was sacrificed for speed; if
stable, un-park teardown in a later run to see if it was ever broken).

### Full IORT-vs-DT SMMU audit (everything else checks out)

All `iommus` in the booted DT compared against the SPX IORT
(surface_pro_x_sq2/iort.dsl, apps SMMU @0x15000000):

| DT node            | DT SID(s)                        | IORT                          | verdict |
|--------------------|----------------------------------|-------------------------------|---------|
| geni-se-qup x3     | 0x4c3, 0x603, 0x7a3              | \_SB.QUP set incl. these      | OK      |
| ufshc              | 0x300                            | \_SB.UFS0 {0,0x2E0,0x300}     | OK      |
| mdss               | 0x800 mask 0x420 = {800,820,C00,C20} | GPU0 display set, exact   | OK      |
| gpu (adreno_smmu)  | CB 0 / 5 on SMMU@2CA0000         | GPU0 -> SMMU@2CA0000          | OK      |
| dwc3 x3            | 0x60 / 0x140 / 0x160             | USB2 / USB0 / USB1            | OK      |
| wcn3990-wifi       | 0x640 mask 0x1                   | \_SB.AMSS.QWLN 0x640 cnt 1    | OK      |
| q6asmdai           | 0x1b21 (fixed from 0x1821)       | ADCM 0x1B21                   | FIXED   |
| slimbam            | 0x1806 (sdm845)                  | ADCM 0x1B2x+ bank             | WRONG, unused (PIO) |
| slim-ngd           | 0x1806 (sdm845)                  | same                          | WRONG, unused (PIO) |

So the only bad SIDs ever in this DT were the three audio ones we added
from sdm845 - and the 0x1806 pair retroactively explains the entire BAM
wedge saga (descriptor fetch with an unmatched SID = fabric stall).
Both are now annotated in sc8180x.dtsi; exact BAM SID undetermined
(candidates: 0x1B46, 0x1B4D-0x1B50, 0x1B53, 0x1B58, 0x1B5C-0x1B5D) and
irrelevant while PIO mode is used.

Non-SMMU ACPI cross-checks: SLM1 MMIO 0x171C0000/0x2C000 + IRQ 195
(=SPI 163) match the DT; SLM2 (BT SLIMbus, 0x17240000, SPI 291) is
deliberately absent; codec reset GPIO 143 fixed earlier; codec INTR
(GpioInt pin 0x100) still unresolved -> IRQ-less codec.

Future bring-up treasure from the IORT (not in DT yet, for later):

- \_SB.ARPC (FastRPC): ADSP CBs 0x1B23-0x1B25; CDSP banks 0x10xx/0x14xx
- \_SB.USBA 0x1B2F: ADSP USB-audio offload path
- \_SB.GPU0.AVS0: venus/video SID sets (0x20xx/0x23xx, 0x0A00-, 0x0E00-)
- \_SB.SEN1 (sensors 0x4E3, 0x5A1+2), \_SB.TSC5 (touch 0x620+0xF),
  \_SB.NPU0, \_SB.IPA (0x520+2), \_SB.JPGE, \_SB.SDC2, QSPI0/1, QDSS
- PCIe root complexes: 0x1C80/0x1D00/0x1D80/0x1E00 (+0x7F each)

### CORRECTION: I was wrong. The IORT-derived SID change DID break the GPU.

The user called this out and was right. I had misread the GRUB menu —
the "RECOVERY: known-good DTB" entry in /boot/grub/grub.cfg explicitly
overrides the devicetree:

    menuentry "Arch Linux ARM (RECOVERY: known-good DTB, no audio)" {
        devicetree /dtb/qcom/sc8180x-surface-pro-x.dtb.orig
        ...
    }

versus the regular entry:

    menuentry "Arch Linux ARM (linux-surface)" {
        devicetree /dtb/qcom/sc8180x-surface-pro-x.dtb
        ...
    }

So when the user picked RECOVERY and got a working display, they
**were** booting a different DTB file (the .orig, sha256 00880e42…),
not the same file. The dtb diff (decompiled via dtc):

    /tmp/good.dts  (00880e42, working)        /tmp/broken.dts (90487aee, hangs)
    sound {                                        <-- GONE
        compatible = "qcom,sc8280xp-sndcard";
        audio-routing = "RX_BIAS", "MCLK", "AMIC1", ...;
        wcd-playback-dai-link { ... };
        wcd-capture-dai-link  { ... };
    };
    ... (broken DTB also has iommus 0x1b21 vs 0x1821 on q6asmdai)

The two changes ship together. I claimed "only the SID changed on
the audio path" — that was wrong; the broken DTB ALSO dropped the
entire `sound {}` machine-driver block. Whether the SID change alone
or the sound-block removal alone or the combination caused the display
hang is not yet pinned down. Currently reverted to 0x1821 in source,
next DTB rebuild will be 45c1496f… (same as the pre-SID-experiment
state), restoring both the SID and (if the build system re-adds it
from the board DTS) the sound block. To be verified before any audio
test.

### Why the broken DTB lost the sound {} block (from web search)

Likely: a dtc decompile-recompile roundtrip on a DTB built from an
earlier `sc8180x.dtsi` snapshot, OR a build that compiled the user's
local board DTS without picking up the modified sc8180x.dtsi / -wcd9340.dtsi
that creates the label nodes (&sound, &wcd9340, &slim, &lpasscc,
&q6asmdai, &q6afedai, &q6routing) the sound block references. The
local sc8180x-surface-pro-x.dts source has the block intact
(lines 318-356 at HEAD 3d83d8ff8b3c) and `git log` shows the block
was added in a single commit. No Kconfig / Makefile / overlay
silently drops it. Source of truth: local dts, has the block; on-disk
broken DTB, doesn't - cause is in the build/install chain, not the
source.

### Initramfs rebuilt with GPU firmware (installed)

### Initramfs rebuilt with GPU firmware (installed)

Added to /etc/mkinitcpio.conf `FILES=` and rebuilt both images:
  /usr/lib/firmware/qcom/a680_sqe.fw  /usr/lib/firmware/qcom/a680_gmu.bin

Installed hashes:
  /boot/initramfs-linux-surface.img          b675a1979c91... (kms + fw, 63M)
  /boot/initramfs-linux-surface-fallback.img f99a6a83d242... (no-kms, 29M)
  /boot/dtb/qcom/sc8180x-surface-pro-x.dtb  90487aee438f... (SID-fixed)
  /etc/mkinitcpio.conf                      0a2c48036a8e...
  backup: /etc/mkinitcpio.conf.bak-20260611-222550

mkinitcpio verified both a680_*.fw and drivers/gpu/drm/msm/msm.ko are
inside the kms initramfs; the fallback (no-kms) image has neither, as
intended. Reversible: drop the two FILES= lines and rerun
`sudo mkinitcpio -P`.

Now actually run the audio test on the (untested so far) SID-fixed DTB:
reboot to the kms initramfs entry (NOT the no-kms fallback) and
SPX_TEST=slim ./scripts/spx-run2-pio-full.sh

### Silent-speaker fix in source: added Left Spk / Right Spk / Headphone routes

The user reported "no sound" through every audio test. Suspect: missing
audio-routing entries. Investigation: db845c (WCD9340 + sdm845-sndcard,
the canonical reference for SPX) routes the internal speakers via
WSA881x SoundWire amps: "SpkrLeft IN", "SPK1 OUT" + "SpkrRight IN",
"SPK2 OUT". SPX has no WSA amps (the speakers are driven direct by
the WCD9340's internal class-D), so the route collapses one step
(no SpkrLeft IN prefix), and the machine driver's "Left Spk" /
"Right Spk" DAPM widgets (sdm845.c:560-561) are the pin sinks.

Added to /arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts sound {}
block (line 322-336):

    audio-routing =
        "RX_BIAS", "MCLK",
        "Left Spk",   "SPK1 OUT",          // <- load-bearing
        "Right Spk",  "SPK2 OUT",          // <- load-bearing
        "Headphone Jack", "HPHL",
        "Headphone Jack", "HPHR",
        "Int Mic",    "DMIC0",
        "AMIC1", "MIC BIAS1",
        "AMIC2", "MIC BIAS2",
        "AMIC3", "MIC BIAS3",
        "AMIC4", "MIC BIAS4",
        "DMIC0", "MIC BIAS1",
        "DMIC1", "MIC BIAS1",
        "DMIC2", "MIC BIAS3",
        "DMIC3", "MIC BIAS3";

This is independent of the SID-display-hang issue. Even on the
working DTB (.orig, 00880e42), playback was silent because the
codec's class-D outputs were never wired to the machine-driver
speaker pins. With these routes added, the next DTB build (c20439c8…)
will have them. NOT YET INSTALLED (waiting for user go on the
DTB install).

### ROOT CAUSE: 0x1B21 is the SLIMbus NGD ADCM's DMA stream, NOT the q6asmdai PCM stream

Re-parse of the SPX IORT (linux-surface/acpidumps/surface_pro_x_sq2/iort.dsl):

- `\_SB.ADSP.SLM1.ADCM` named-component (the WCD9340 codec's parent
  audio decoder chip module on the SLIMbus NGD) owns apps_smmu SIDs:
  0x1B21, 0x1B46, 0x1B4D-50, 0x1B53, 0x1B58, 0x1B5C-5D. These are
  ADSP-side DMA streams the kernel should never bind to q6asmdai.

- `\_SB.ARPC` named-component (the apps remoteproc proxy: q6asm,
  q6afe, q6adm, fastrpc) owns the audio apps-side SIDs: 0x1B23, 0x1B24,
  0x1B25, 0x1401, 0x1421, 0x1441, 0x1001, 0x1021, 0x1041. The q6asmdai
  PCM stream lives here; likely candidates are 0x1B22 or 0x1B26-0x1B2E
  (gaps in the ARPC audio bank not claimed by any device).

- `\_SB.USBA` owns 0x1B2F (USB-audio offload, unrelated).

- The IORT input base 0x0703xxxx (ADSP-internal) and 0x1703xxxx
  (apps-side) are two different namespaces remapped at the apps_smmu
  boundary; "input base" in the IORT named-component is NOT a SID
  the apps kernel programs for q6asmdai.

By putting 0x1B21 on q6asmdai, I created a context-bank collision at
apps_smmu between the apps-side q6asmdai and the ADSP-side SLIMbus
NGD decoder. The NGD's existing 0x1B21 traffic was routed to the new
CB (q6asmdai's pgd), ADSP-side SLIMbus NGD transfers faulted, the NGD
state machine wedged (m_work stays in `reconf` completion), AOSS-side
clock votes stalled, dispcc couldn't be reprogrammed, panel froze at
last framebuffer. The "static / right side cut off" was a downstream
effect of the audio wedge, not a GPU issue.

Decision:
- 0x1B21: NEVER use for q6asmdai. Reverted in source (45c1496f… DTB).
- 0x1821: keep as the sdm845 historical boot-safe placeholder. It
  doesn't actually route audio to the ADSP correctly, but in PIO
  mode (no apps_smmu DMA on the SLIMbus NGD) it doesn't cause a CB
  collision either. Don't touch without a known-good replacement.
- True correct q6asmdai SID for SPX: unknown publicly. To pin it
  down: enable arm-smmu-v3 debug + DMA-API trace on a single APR
  start, observe the actual SID the ADSP fastrpc accepts. Or check
  the Windows DMAR IORT for an analogous apps-side q6asmdai device's
  stream ID.

### Two-agent disagreement on what 0x1B21 is for

Two of the web-search agents investigated the same IORT SID and
arrived at contradictory interpretations. Both agree that 0x1B21 is
the IORT output SID for an `\_SB.ADSP.*` named component on apps_smmu,
and that 0x1821 is a sdm845 carry-over (no master on SPX emits it,
the apps SMMU programs a dead CB for it). They disagree on which
ADSP device owns 0x1B21:

- **Agent 1 ("IORT counter-evidence")** says 0x1B21 is the SLIMbus NGD
  ADCM's DMA stream (the WCD9340 codec's parent audio decoder chip
  module on the ADSP). Putting it on q6asmdai forces a CB collision,
  NGD/ADSP wedge, AOSS clock votes stall, dispcc can't reprogram,
  panel freezes at last framebuffer. The "static / right side cut off"
  is downstream of the audio wedge, not a GPU issue. The q6asmdai
  apps-side SIDs (0x1B23-25) live in the `\_SB.ARPC` named component.

- **Agent 4 ("What 0x1821 is actually used for")** says 0x1B21 is the
  q6asm apps-side PCM-buffer SID, the SMMU has a valid CB for it,
  and on a clean boot no apps-SMMU traffic happens for the q6asmdai
  path anyway, so the SID change cannot cause a boot-time display
  hang. The display hang must be the missing `sound {}` block
  (which both agents agree was a separate regression in the broken
  DTB). 0x1821 is just dead code in the apps SMMU's SME table.

Both agents agree the safe action is: don't try 0x1B21 again, don't
touch the SID without a definitive test, and try 0x1B46 as the next
experimental SID (also from the IORT ADSP bank; if it boots cleanly,
Agent 4 is right; if it also hangs, Agent 1 is right and the
display hang is something else - the missing sound block is the
prime suspect).

**In-tree state as of this writeup:** SID 0x1821 reverted in
`sc8180x.dtsi`; `0x1B21` annotated as the IORT-claimed-but-untested
value. New DTB `c20439c8c13d…` (audio-routing extended, SID
reverted) ready in-tree, NOT installed. The `.orig` DTB
(00880e42…) is the safe display baseline.

### Status: no public record of audio working on SPX in mainline

The fork survey (linux-surface/surface-pro-x issue #21, sc8180x-mainline
gitlab, mainline-status, all related upstream/downstream repos)
confirms **no one has ever gotten end-to-end audio working on the
Surface Pro X in mainline Linux.** Every prior attempt was abandoned;
the canonical issue is still open. The closest analogs that DO work
(X13s, Arcata, Blackrock on sc8280xp) use AudioReach LPASS + WCD9380
+ SoundWire + WSA amps - a structurally different SoC generation. The
SPX is a headless-compute-style exception: the Flex 5G (only other
public sc8180x device) has no sound node in upstream DTS.

The bring-up effort is therefore not blocked on a missing DTB line
or a missing kernel patch - it is blocked on a structural mismatch
between the SPX's pre-AudioReach ADSP firmware and the available
machine drivers / DAI cells. Highest-value next experiment: string
disassemble /lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn
for 'audioreach', 'q6apm', 'q6afe', 'q6asm', 'lpass_rx_macro', 'WCD9380',
'WCD9340' symbols. If the firmware is AudioReach, the entire sound
block + DAI wiring must be redone in the AudioReach idiom (X13s
template) AND the q6apm/q6prm/lpass-macro infrastructure ported from
sc8280xp.dtsi into sc8180x.dtsi. If legacy, the current path is
correct and the silence is a QMI/IRQ/codec-config problem worth
bisecting. Either way, this single string disambiguation costs ~1
minute and answers the single biggest open question.

### Error correction: I claimed the SPX DTB used qcom,sc8280xp-sndcard; it does not

The current in-tree SPX DTB (`sc8180x-surface-pro-x.dts` line 319)
uses `qcom,sdm845-sndcard`, the only machine driver in mainline that
handles WCD9340-on-SLIMbus. The `.orig` DTB's sound block uses
`qcom,sc8280xp-sndcard` - a driver that requires AudioReach + WCD9380
+ SoundWire, so it would not probe SPX hardware. The "RECOVERY"
known-good DTB got a working display because that incompatible was
silently rejected, leaving the rest of the DT intact. It never
produced working audio. The user has been hearing silence on every
test partly because of this.

### Agent 5: IORT is informational for q6asmdai; SLIMbus NGD owns 0x1B21

The fifth web-search agent read the live kernel code and confirmed
`iort_iommu_configure_id()` is only called from the ACPI device path
(`drivers/acpi/scan.c:1635`). The q6asmdai is a DT-only platform
device (no ACPI companion), so the IORT does not configure its
iommu_fwspec. What gets programmed is whatever the DT `iommus`
property says, full stop.

The IORT is relevant only for ACPI-probed devices. The SLIMbus
NGD (`\_SB.ADSP.SLM1.ADCM`) is ACPI-probed; q6asmdai is
DT-probed. So the apps_smmu SMR entry for q6asmdai is independent
of any IORT mapping. The apps_smmu SMR entry for the NGD is
governed by the NGD's IORT mappings (0x1B21, 0x1B46, 0x1B4D-50,
0x1B53, 0x1B58, 0x1B5C-5D).

This means: putting 0x1B21 on q6asmdai via DT does not move any
ADSP-side traffic - it just makes the kernel try to attach a second
context bank for SID 0x1B21. SMMU-500 SMR/CBAR/S2CR is 1:1; the
second attach is rejected, and the SLIMbus NGD's existing CB for
0x1B21 is the one that gets used by the NGD's master. The NGD
continues working. q6asmdai either gets no CB (its DMA faults
cleanly) or fights with the NGD (the conflict Agent 1 theorized).

Either way, 0x1B21 (and 0x1B46, 0x1B4D-50, 0x1B53, 0x1B58,
0x1B5C-5D - all the ADCM SIDs) should be **off-limits** for
q6asmdai. The candidate pool is the ARPC bank: 0x1B22, 0x1B26-2E
(gaps), and the explicitly listed 0x1B23-25 / 0x10xx / 0x14xx.
None of these is 0x1821.

The IORT is reliable evidence of *which SIDs are in active use*
(by which ACPI devices) and *which are not yet claimed*; it is
*not* reliable evidence of what SID the apps-side q6asmdai
DT-probed device should use. That can only be found empirically
(arm-smmu-v3 debug + DMA-API trace, or a Windows DMAR IORT for
the analogous app-side q6asmdai device).

### Agent 6: 0x1B21 is sc8180x's 0x1821 (same stream, +0x300 SoC offset)

The sixth web-search agent counted SMMU nodes across every mainline
qcom dtsi and found exactly two on sc8180x: `apps_smmu` at
0x15000000 and `adreno_smmu` at 0x2ca0000. There is no third SMMU;
no `lpass_smmu` or `lpass_lpi_smmu` exists in any mainline qcom
dtsi, and the binding doc `arm,smmu.yaml` has no such compatible.

The 0x1Bxx SIDs in the IORT are **sc8180x's SMRG remap of sdm845's
0x18xx ADSP bank with a +0x300 offset**. Concretely:

| sc8180x IORT SID | sdm845 equivalent (IORT or DT) | Function (inferred) |
|---|---|---|
| 0x1B21 | 0x1821 | q6asmdai audio playback |
| 0x1B46 | 0x1846 | q6afe-lpass or BAM-adjacent |
| 0x1B4D-50 | 0x184D-50 | 4 contiguous, typically a BAM |
| 0x1B53 | 0x1853 | |
| 0x1B58 | 0x1858 | |
| 0x1B5C-5D | 0x185C-5D | |

Every other SoC in mainline puts `q6asmdai`'s `iommus` on `apps_smmu`:
sdm845 uses 0x1821, sm8250 uses 0x1801, sc8280xp's q6apmdai uses
0x0c01, lemans's q6apmdai uses 0x3001, sm8550 uses 0x1001/0x1061.
**All audio SIDs are on `apps_smmu`; no LPASS-specific SMMU exists
on any qcom SoC in mainline.**

So the question is fully resolved: 0x1B21 IS the correct apps_smmu
SID for the q6asmdai audio playback stream on sc8180x. The sdm845
default of 0x1821 is a 0x300-off placeholder; on sc8180x it points
into a SMRG slot the ADSP never emits. The active SIDs (0x1B21,
0x1B46, 0x1B4D-50, 0x1B53, 0x1B58, 0x1B5C-5D) are all
legitimately in use by ADSP-side streams. They cannot be shared.

`iommus = <&apps_smmu 0x1B22 0>` or `0x1B26 0>` or another gap
in the ARPC bank is the only remaining candidate for the apps-side
q6asmdai SID. The kernel cannot determine that value from tables;
only `arm-smmu-v3` debug + DMA-API trace during a single APR
start will show which SID the ADSP fastrpc server actually accepts.

### FINAL SYNTHESIS of the 10-agent IORT/SID investigation

(2 agents died on API limits; 7 reported; one was redundant.)

Established, with sources, across agents:

1. sc8180x has exactly TWO SMMUs (apps @15000000, adreno @2ca0000).
   No LPASS SMMU exists on any mainline qcom SoC.
2. All q6asmdai-class audio SIDs live on apps_smmu on every SoC.
3. 0x1821 on q6asmdai is the sdm845 value; on sc8180x no master
   emits it -> dead-but-boot-safe placeholder.
4. The IORT's 0x1Bxx bank = sdm845's 0x18xx ADSP bank + 0x300
   (sc8180x SMRG offset). So 0x1B21 corresponds to sdm845's 0x1821.
5. BUT: the only place 0x1B21 appears in any Qualcomm downstream
   tree is `&msm_audio_ion` (the PCM buffer pool), and on the SPX
   IORT it is listed under \_SB.ADSP.SLM1.ADCM (the SLIMbus audio
   device, ACPI-probed). Empirically, putting it on the DT-probed
   q6asmdai hung the display (twice-confirmed mechanism candidates:
   apps_smmu CB conflict with the NGD's ACPI mapping, or ION-vs-DAI
   stream confusion in firmware SMMU programming).
6. The IORT only configures ACPI-companion devices
   (drivers/acpi/scan.c:1635); q6asmdai is DT-only, so its SID is
   purely what we write in DT.
7. No one has EVER had audio working on SPX (or any sc8180x) in
   mainline. Legacy AFE/ASM path on this SoC is unverified territory.

DECISIONS (final):
- q6asmdai stays at 0x1821. Do not retry 0x1B21 or any ADCM-bank SID.
- If real PCM DMA is ever exercised and faults, candidates are the
  ARPC-bank gaps (0x1B22, 0x1B26-2E) or empirical discovery via
  arm-smmu fault logs on first APR_MAP_MEMORY.
- Before more legacy-path debugging, run the 1-minute LPASS
  generation check:
    strings /lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn \
      | grep -icE 'audioreach|apm_|q6afe|q6asm'
  AudioReach symbols => rewrite sound block in X13s idiom.
- Pending install (on user go): in-tree DTB c20439c8… = SID
  reverted + speaker/headphone audio-routing added. Safe baseline
  remains .orig (00880e42) via the RECOVERY GRUB entry.

### Firmware check + DTB c20439c8 installed

strings qcadsp8180.mbn: audioreach=0, apm_=0, q6afe=0, q6asm=0, but
AFE=985, ASM=87, ADM=102, elite=157 => LEGACY ELITE LPASS confirmed.
The q6afe/q6asm/q6routing + sdm845-sndcard approach is correct.

Installed /boot/dtb/qcom/sc8180x-surface-pro-x.dtb = c20439c8…
(SID 0x1821 kept, speaker/headphone audio-routing added). Backup
timestamped; .orig (00880e42) still available via RECOVERY entry.

Next boot (regular entry): display should work (this DTB ≈ the
pre-0x1B21 state + routing); then:
  SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
With the Left/Right Spk routes now present, DAPM can finally power
SPK1/2 OUT — this is the first test where sound is actually possible.

### MECHANISM CONFIRMED (code) + decisive boot prepared

q6asm-dai.c:425 sends `IOVA | (sid_nibble << 32)`; q6asm.c mem-map puts
the nibble in MSW. The ADSP ORs it onto ITS OWN SID base = 0x1B20 on
sc8180x -> emits 0x1B21 reading the PCM buffer. Kernel mapped the IOVA
under 0x1821 only -> USF abort (USFCFG=1) -> ADSP bus error mid-DMA ->
the ~10s silent fabric wedge on every playback start. Forensics of the
last wedge: clean cliff at 23:36:00, zero playback-phase logs, no SMMU
fault persisted (console died before flush).

DT boots never parse the IORT -> no SMR conflict possible for 0x1B21;
the earlier "0x1B21 hung the display" was the corrupt DTB (missing
sound block). 0x1B21 retried cleanly now.

Prepared (installed):
- DTB a8caddad… : q6asmdai iommus = 0x1b21 (on the good c20439c8 base
  with speaker routing + sdm845-sndcard).
- GRUB regular entry cmdline: ramoops.record_size=0x20000
  ramoops.console_size=0x40000 (continuous console-to-RAM; survives
  warm reset - validate via /sys/fs/pstore/console-ramoops-0) +
  arm-smmu.disable_bypass=0 (safety net: unmatched SIDs pass through
  instead of aborting). RECOVERY entry untouched.

Next boot (regular entry):
  SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
Outcomes: tone plays -> DONE (then drop disable_bypass to confirm
0x1B21 alone suffices). Wedge -> read /sys/fs/pstore/console-ramoops-0
after reboot for "Blocked unknown Stream ID 0xNNNN" = the true SID.

### WEDGE FIXED + speakers found: WSA amps on SoundWire after all

SID 0x1b21 on q6asmdai = NO MORE CRASHES. Full play->stop->play cycle
stable, AFE port runs, DAPM path On end-to-end. Silence root cause:
Windows qcauddev8180.inf has SlaveInfo=2 + SpeakerProtectionParameters
(V/I-sense smart-amp) => TWO WSA-class SoundWire amps on the codec's
swm@c85 - the earlier "no WSA on SPX" conclusion was WRONG. SPK1/2 OUT
feed SoundWire, not analog pins; without the swm node nothing is
connected.

Installed:
- DTB 24fdc8da…: swm@c85 + left/right_spkr (sdw10217201000, powerdown
  via wcdgpio 1), dai-link codecs = left/right_spkr + swm 0 + wcd9340 0,
  routing SpkrLeft/Right IN <- SPK1/2 OUT. No interrupts-extended on swm.
- soundwire-qcom.ko 50fa0863…: IRQ optional -> spx poll thread
  (30ms, runs the threaded handler; regmap over SLIMbus PIO).
- Script now loads gpio_wcd934x + soundwire_qcom + snd_soc_wsa881x.

Next boot: SPX_TEST=slim ./scripts/spx-run2-pio-full.sh - the script's
INT7/INT8 routes are NOT yet in it; after the card is up also run:
  amixer -c0 cset name='RX INT7_1 MIX1 INP0' RX0
  amixer -c0 cset name='RX INT8_1 MIX1 INP0' RX1
  amixer -c0 cset name='COMP7 Switch' on; amixer -c0 cset name='COMP8 Switch' on
  amixer -c0 cset name='SpkrLeft COMP Switch' on 2>/dev/null
  amixer -c0 cset name='SpkrRight COMP Switch' on 2>/dev/null

### 2026-06-12: amps enumerate; polled-SWR races fixed; reboot needed

The WSA amps ARE there: sdw:0:0:0217:2010:00:1 and :2 (= 2x WSA8810,
matches sdw10217201000) enumerated via the polled SoundWire mode.
Remaining failures this boot:
- Boot-time "SWR CMD error, fifo status 0x3e00xxxx" storms: the SPX
  poll thread ran the irq handler DURING in-flight FIFO commands; the
  handler's CMD_ERROR flush destroyed pending read data -> retry
  storms -> wsa881x init writes failed -> runtime-PM error latched
  (-22 at every pm_runtime_get) -> BE prepare failed -> no playback.
- One transient ASM Memory_map error[1] (later attempts mapped fine).
- Rebind attempt mid-storm wedged the SWR link ("link failed to
  connect") - bus needs a clean boot.

Fix installed: soundwire-qcom.ko 7301d7f8… adds spx_cmd_busy atomic;
rd/wr cmd paths mark busy, the poll thread stands off while set
(broadcast wait releases busy before waiting so the poller can
complete it). All cmd exits decrement.

Next boot: SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
Expect: no CMD-error storm at wsa881x init, both amps bind with
working runtime PM, BE prepares, and the tone reaches the speakers.

### 2026-06-12 #2: cmd-storm fixed; new blocker = SWR runtime-PM link cycle

The spx_cmd_busy standoff removed the CMD-error storm. Remaining boot
issues: "wr fifo err write overflow", "SWR bus clsh detected",
"swrm_wait_for_frame_gen_enabled: link status not disconnected",
wsa881x "Initialization not complete, timed out" -> runtime-PM error
latched -> BE open fails (-22) -> no playback. Diagnosis: the SWR
master's runtime-PM cycle (suspend -> frame-gen re-enable on resume)
is unreliable in IRQ-less mode; commands queue into a link that is
down -> fifo overflow / device init timeouts.

Fix installed: soundwire-qcom.ko 13a37357… adds pm_runtime_forbid in
polled mode (link stays up permanently). Script now also does a
warm-up open (first ASM mem-map of each boot fails with DSP error[1],
recurring transient).

Next boot: SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
Watch for: clean wsa881x init (no "Initialization not complete"), no
frame-gen errors. If init is clean, the BE can finally prepare and
the tone should reach the WSA8810s.

### 2026-06-12 #3: WSA runtime-suspend/re-enum loop identified and fixed

This boot was the cleanest yet (link pinning works) but playback still
failed: WSA amp runtime-suspend asserts the SHARED shutdown GPIO
(wcdgpio 1, both amps), resume then requires SoundWire
re-enumeration, and the polled master's auto-enum FAILS (interrupt
2048 = AUTO_ENUM_FAILED) -> "Initialization not complete, timed out"
-> runtime-PM error latched -> BE open fails. Proven live: a rebind on
a quiet bus brought amp 1 to runtime_status=active, but the next
suspend/resume cycle re-broke it.

Fix installed: snd-soc-wsa881x.ko 83529f25… - pm_runtime_forbid at
probe; the amps enumerate once at boot and never power-cycle.

Next boot: SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
Success signature: both sdw:0:0:0217:2010:00:* runtime_status=active
after the card loads, no "Initialization not complete", BE opens.

### 2026-06-12 #4: full failure anatomy - SWR timing vs PIO-speed regmap

pm_runtime_forbid on master+amps held (no init timeouts, amps stayed
bound). The remaining instability is now precisely characterized:

1. SWR master registers are accessed via the WCD9340 SLIMbus regmap =
   PIO transport = ~ms per access. qcom.c command timing assumes
   MMIO speed: usleep_range(250) between RD cmd and fifo read,
   500us poll steps, tight retry budgets. Result: "rd fifo avail err
   read underflow" (response not yet arrived), trf failures on
   addr 202 (DPN_PortCtrl) and 3103, phantom slave addresses
   (0000:0065, 0500:3e65 "no bus MCLK" - noise parsed as devices).
2. The flush/retry storms are themselves SLIM messages and saturate
   the PIO transport: NEW failure this boot - the codec's own
   CONNECT_SOURCE channel hookups timed out (MC:0x60 LA:0xce/0xcf
   failed:-110, "Error Setting slim hw params"). Two boots ago
   (without WSA traffic) these all worked: coupling, not regression.
3. First-FE-open ASM mem-map error[1] persists (warm-up handles it).

NEXT SESSION, one surgical patch to drivers/soundwire/qcom.c:
- In SPX polled mode, scale all command timing for slow regmap:
  * after RD cmd write: wait >= 5-10ms (not 250us) before reading
    the RD fifo; verify rcmd_id with patient retries (sleep 2-5ms,
    not 500us; raise MAX_FIFO_RD_RETRY).
  * after WR cmd: allow fifo drain check with ms-scale sleeps.
  * consider serializing the whole cmd path with a mutex so poller
    handler register reads can't interleave mid-command (spx_cmd_busy
    only stops the poller BETWEEN its handler runs; reads inside a
    running handler still interleave).
- Optionally rate-limit/disable the CMD_ERROR fifo-flush in polled
  mode (each flush kills an in-flight legit response).
Success criteria: zero "read underflow" during wsa881x init AND no
MC:0x60 -110 during hw_params. Then the tone plays or the next layer
shows itself cleanly.

State preserved: all module/DTB hashes earlier in this doc; platform
is crash-free throughout - iterate freely.

PATCH INSTALLED for next boot: soundwire-qcom.ko (see sha above this
line in shell log) - PIO-speed timing in polled mode: RD-cmd settle
250us->5-6ms, retry sleep 500us->5-6ms, handler CMD_ERROR flush
disabled (rd path flushes itself). Test: SPX_TEST=slim script run;
success = zero "read underflow" during wsa init and no MC:0x60 -110.

### 2026-06-12 #5: tx_lock starvation deadlock found and fixed

The PIO-timing patch worked: init phase clean (amps bound, no init
read-underflows). Remaining failures were confined to dai-link
prepare, where wcd934x CONNECT_SOURCE messages and WSA SoundWire port
programming run CONCURRENTLY over the same PIO SLIM transport. Root:
qcom_slim_ngd_xfer_msg held tx_lock through the 1-second usr-ack
wait (inherited mainline structure, harmless on fast DMA). With SWR
register I/O riding the same transport: CONNECT waits 1s holding the
lock -> SWR reads stall -> underflow/retries -> manager busy -> the
CONNECT ack itself delayed -> -110 -> repeat. Mutual starvation.

Fix installed: slim-qcom-ngd-ctrl.ko 7fa94bf2… - PIO branch releases
tx_lock right after the FIFO write (the ack arrives via the RX poller
and needs no lock); the usr-ack wait runs unlocked.

Next boot: SPX_TEST=slim script. Success = no MC:0x60 -110 lines, no
read-underflow during prepare, link_prepare completes - tone plays.

### 2026-06-12 #6: SLIM txn use-after-free Oops + PM underflow + SWR interleaving — all fixed

The SPX_TEST=slim run with the tx_lock-starvation fix produced a kernel
Oops that killed the `spx_slim_pio` RX thread mid-run:

    pc : complete+0x58 ... x19: 0000000000000000
    slim_msg_response+0xa8 -> qcom_slim_ngd_rx -> qcom_slim_ngd_pio_rx_once
    note: spx_slim_pio[2578] exited with irqs disabled / preempt_count 1

plus two "Runtime PM usage count underflow!" on qcom,slim-ngd.1, on top
of the still-present SWR -61/-5 prepare storms. Root causes (all three
confirmed in code, all fixed and installed):

1. **Use-after-free in `slim_msg_response()`** (the Oops): it did
   `idr_find` under `txn_lock`, dropped the lock, then dereferenced the
   txn. During the timeout storm, late replies raced waiters that had
   already timed out and returned — the on-stack `completion` was a dead
   stack frame. Once the PIO RX thread died, every SLIM reply was lost
   and the whole bus degraded to timeouts.
   Fix (`messaging.c`): find + `idr_remove` + memcpy + `complete()` now
   happen in ONE `txn_lock` critical section; a concurrently timing-out
   waiter blocks in `slim_free_txn_tid()` (same lock) until delivery is
   done, so the stack frame is still alive.

2. **Runtime-PM double-put** (the underflow): on timeout the waiter did
   `pm_runtime_put_autosuspend()`, and the late reply did it AGAIN in
   `slim_msg_response()`. New rule: whoever removes the tid from the IDR
   owns the put. `slim_free_txn_tid()` now removes conditionally
   (only if the entry still belongs to this txn) and returns bool;
   `slim_do_transfer()` and `qcom_slim_ngd_xfer_msg_sync()` only put
   when they actually claimed the tid. `slim_do_transfer()` also frees
   the tid on ANY xfer error (was: only -ETIMEDOUT), closing the other
   stale-tid window.

3. **SWR poller/command interleaving** (the -61/-5 storms): the
   `spx_cmd_busy` atomic only stopped the poller from STARTING a handler
   run; a handler already in flight (multi-ms over the SLIM regmap) kept
   interleaving its register reads with FIFO commands -> stale rcmd_id,
   read underflow, retry storms. Replaced with `spx_cmd_lock` mutex:
   the poller holds it across the WHOLE handler run, rd/wr cmd paths
   take it unless running on the poller thread itself (slave callbacks
   inside the handler), and broadcast releases it before waiting so the
   poller can complete it. Also: write-completion timeout no longer
   FLUSHES the command FIFO (the flush killed other queued/in-flight
   commands and turned one slow command into a storm); a genuinely stuck
   FIFO is flushed by the fifo-full path of the next command.

Installed (build-install.sh, ts 20260612-165402):

    slimbus.ko             4489e33e06ad665303946862022680cb9b9cde015ab90526ae5b5dbb3d3067c4
    slim-qcom-ngd-ctrl.ko  ea4b6225494d9d1464a71a3054dd2857c5501cffe6c8e939399ba67755a74479
    soundwire-qcom.ko      8c4ab70ded63a13ff8d463803a851cf7c4571cce52fbe576c51ade301bf52749
    (DTB/mfd/codec/q6afe-dai unchanged content, reinstalled same)

This boot is unusable for retest (PIO thread dead after the Oops, module
pinned). Next boot:

    SPX_TEST=slim ./scripts/spx-run2-pio-full.sh

Success signature: no "read underflow"/"flushed SWR command FIFO" storm
during wsa881x init and prepare, no "Runtime PM usage count underflow",
no Oops, link_prepare completes, tone plays. If prepare still fails
sporadically, the remaining suspects are SWR bank-switch timing under
the 30ms poll cadence (lower msleep in qcom_swrm_spx_poll) and the
"Port collision" on retry (sdw stream re-prepare while parked ports stay
enabled — unpark wcd934x/q6afe teardown to test).

### 2026-06-12 #7: spx_cmd_lock ABBA deadlock (poller vs prepare) — fixed

The #6 build deadlocked at the mixer/prepare step instead of storming.
Live /proc/<pid>/stack confirmed a textbook ABBA:

    wireplumber: sdw_prepare_stream (holds bus_lock)
                 -> qcom_swrm_cmd_fifo_wr_cmd -> waits on spx_cmd_lock
    swrm_poll:   holds spx_cmd_lock across the whole handler
                 -> sdw_handle_slave_status -> waits on bus_lock

Holding spx_cmd_lock across the handler was wrong: the handler takes
SoundWire bus locks, so spx_cmd_lock must be a LEAF lock. New scheme
(soundwire-qcom.ko bdba23038f43…):

- rd/wr cmd paths take spx_cmd_lock unconditionally in polled mode
  (commands fully serialized, including ones issued from inside the
  handler — the poller no longer holds the mutex, so no recursion).
- The poller stands off via the reinstated spx_cmd_busy atomic (skips
  a 30ms round while a command is in flight) instead of locking.
- Broadcast still releases the lock before waiting so the poller can
  run the handler that completes it.

The deadlocked boot is unrecoverable (D-state holders pin the bus);
reboot, then: SPX_TEST=slim ./scripts/spx-run2-pio-full.sh

### 2026-06-12 #8: pre-reboot adversarial audit — three more latent bugs fixed

Static audit of everything the next boot will execute, done WITHOUT
burning a reboot:

1. **The scripted playback test has NEVER actually run.** warmup() uses
   `timeout 2 speaker-test ...`; timeout exits 124, and `set -eu` then
   silently kills the script at the warm-up line (visible in every past
   run: output stops at "warm-up open"). All the prepare/storm traffic
   we have been debugging in those runs came from WirePlumber, not the
   script. Fixed: `|| true` + `timeout -k`. The script also now parks
   wireplumber/pipewire during SPX_TEST runs (trap restores them) and
   prints an automatic regression-check grep after each play.

2. **The #7 standoff still had the original storm hole.** spx_cmd_busy
   only stopped the poller from STARTING a handler pass; a command
   starting 2ms after a handler pass began would overlap it — exactly
   the pre-#6 interleave (guaranteed during prepare: seconds of
   commands vs 30ms poll cadence). Fixed with a two-way store-buffering
   handoff (no lock across the handler, so no #7-style ABBA):
   - cmd paths: mutex -> inc spx_cmd_busy -> smp_mb -> wait while
     spx_handler_active.
   - poller: set spx_handler_active -> smp_mb -> recheck busy; back off
     if a command slipped in, else run the handler.
   - commands issued FROM the poller thread (slave callbacks inside the
     handler) skip lock+wait: already exclusive by the protocol.
   Both sides store-then-load with full barriers, so at least one side
   always sees the other.

3. **Bank-switch broadcast wait was 100ms** against a 30ms poller
   cadence with multi-ms SLIM regmap handler passes — polled mode now
   waits 1000ms.

Also verified statically (no reboot needed):
- Script mixer path vs driver control names: INT7/8 + COMP7/8 +
  SpkrLeft/Right {COMP,BOOST,DAC} Switch + PA Volume all exist
  (wsa881x.c kcontrols x sound-name-prefix in sc8180x-wcd9340.dtsi).
- sdm845.c "Left Spk"/"Right Spk" DAPM pins have NO pin switches ->
  always connected; DTB routing SpkrLeft/Right IN <- SPK1/2 OUT present.
- Handler CMD_ERROR/WR_OVERFLOW flushes correctly gated to irq mode.
- Lock order is a consistent total order: bus_lock -> msg_lock ->
  spx_cmd_lock -> (regmap-slimbus) tx_lock. spx_cmd_lock is a leaf.
- Every exit of qcom_swrm_cmd_fifo_{wr,rd}_cmd unlocks.

Installed: soundwire-qcom.ko 2deca4107393…

Next boot: SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
This is the FIRST boot where the scripted test will actually execute.
