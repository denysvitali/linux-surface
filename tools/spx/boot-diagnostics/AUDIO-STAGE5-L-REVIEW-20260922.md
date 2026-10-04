# Audio stage 5 step 0 on the reused L build — 2026-09-22

**A fresh stage-5, step-0 boot is the recommended next audio experiment,
conditional on completing and hash-verifying M's result first.** Reuse the
exact L kernel, modules, DTB and initramfs used by M. This review does not
prepare or select a boot, access live NGD registers, or claim an M observation
of 600 seconds. It introduces no source or configuration change.

This updates the prospective K references in
[the earlier stage-5 review](AUDIO-STAGE5-20260922.md) to the actual L/M
artifact baseline. K subsequently failed touch publication. L's completed
[629.82-second result](RESULT-20260922l.md) established the expected stage-4
audio stop and clean input enumeration with startup diagnostics enabled.
[M](PREPARED-20260922m.md) is the identical build with startup diagnostics
disabled. Its own completed result must determine whether to proceed; L's
success does not resolve intermittent touch failure or prove physical input.

## Exact provenance

The offline checker compared the current NGD source with the archived build
commit and verified that neither L nor M's archived source diff changes that
file. Both archives' NGD artifact and staged module agree with their build
and module manifests and with the installed module.

| Item | Identity |
| --- | --- |
| Build commit | `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b` |
| Release and module vermagic prefix | `7.3.0-rc2-spx-mainline-20260922l+` |
| `drivers/slimbus/qcom-ngd-ctrl.c` Git blob | `f7ca305ba9221bb43d08b39cf266bb2f4ba57e28` |
| NGD source SHA-256 | `ac5977296b408d6096b67675f4e1ff1b1267a796bb3d57e55abf33cddb1a392b` |
| `slim-qcom-ngd-ctrl.ko` SHA-256 | `31df6e27e5f8058dd9ff33bf2320cd38dc5e5a6ea4049771b72179210b380f1d` |
| NGD module GNU build ID | `06213c39d0aab6e3e6ea12b63f8223c8e32a97ca` |

The installed module is under
`/usr/lib/modules/7.3.0-rc2-spx-mainline-20260922l+/kernel/drivers/slimbus/`.
These are archive/installed-file checks, not a claim that this review examined
the loaded module's note. Whole-build and payload reuse was independently
checked in [M's preparation review](PREPARATION-REVIEW-20260922m.md); fresh
preparation must recheck all module, payload, recovery and runtime hashes.

## Proposed N command-line delta and effective state

From M's ordered command line, replace exactly these two tokens and append
the explicit step selector once:

```diff
-spx_attempt=20260922m
+spx_attempt=20260922n
-slim_qcom_ngd_ctrl.spx_probe_stage=4
+slim_qcom_ngd_ctrl.spx_probe_stage=5
+slim_qcom_ngd_ctrl.spx_stage5_step=0
```

Keep `spi_hid.startup_diag=0`, `slim_qcom_ngd_ctrl.spx_pin_after_qmi=1`,
the 600-second window and every other token unchanged. Do not edit any live
module parameter; NGD parameters are writable even though this experiment
uses only boot-time selection. Keep the L release/payload paths; N names a
new experiment, not a rebuilt kernel.

After boot, verify stage 5, step 0, pin Y and refcount 1. Require all of
`spx_allow_dma`, `spx_allow_int_en`, `spx_allow_full`, `spx_pio_mode`,
`spx_pdr_auto_enable`, `spx_qmi_bypass_lookup`, `spx_dump_windows`,
`spx_pio_debug_reads`, `spx_pio_tx_nowait` and `spx_pio_verbose` to remain N.
Require stage-6/7 steps 0, selection instance -1, selection mode 0,
power-response type -1, NGD base override -1 and DMA-mask bits 0. Poll RX
remains Y but this stage starts no poller. Child runtime state must remain
`suspended`, active time `0`, control `auto`. Input diagnostics must be N,
mode 0444, with no `startup-diag:` journal records.

## Source boundary and required evidence

The reviewed path performs SELECT_INSTANCE/pinning before the
[stage helper](../../../drivers/slimbus/qcom-ngd-ctrl.c#L2526) sends QMI ACTIVE
(`pm_req=2`, response-type TLV omitted). The QMI request changes firmware
state; the following MMIO-only description does not make the entire boot
read-only. The disabled window-dump helper returns without register access.

| 32-bit read | Physical address | Scope |
| --- | --- | --- |
| Top-level version | `0x171c0000` | Existing stage-4 read |
| Child STATUS | `0x171c1004` | Existing stage-4 read |
| Child CFG | `0x171c1000` | Existing stage-4 read |
| Child RX_MSGQ_CFG | `0x171c1008` | Existing stage-4 read |
| Child INT_STAT | `0x171c1014` | New stage-5 read |
| Child INT_EN | `0x171c1010` | New stage-5 read |

The first four reads are sequenced as listed. The last two occur as
arguments of one `dev_info()` call; C does not specify their relative order.
The combined marker appears only after both return, so a missing marker
cannot identify which read stalled. The logged `rx_msgq_cfg` reuses the
earlier value. Step 0 resets a software completion, prints its marker and
returns before any staged write: **six explicit register reads, no explicit
MMIO writes on this synchronous path**. It does not register the controller
or enable transport. `readl_relaxed()` provides no per-access timeout.

Require the pin marker, successful QMI response `result=0x0 error=0x0`,
`SPX: staged QMI power request acked`, then these source-defined messages:

```text
SPX: top-level NGD raw version register=0x2020000 ver=0x202
SPX: child NGD read status=0x40c cfg=0x0 rx_msgq_cfg=0x0
SPX: stage 5 controlled write step=0 int_stat=0x<observed> int_en=0x0 rx_msgq_cfg=0x0
SPX: stage 5 step 0: no writes
SPX: stopping after staged hardware probe (spx_probe_stage=5)
SPX: child probe: enable done
```

The first two numeric sets are the L stage-4 baseline; preserve any deviation.
`<observed>` is a documentation placeholder: record the actual INT_STAT value
without requiring zero. INT_EN zero is the intended disabled baseline, not
a value established by an N parameter. A nonzero result is unexpected;
preserve it and do not write zero live. No soundcard is expected, including
the existing delayed loader's no-card failure. Audio playback remains open.

## Asynchronous limits and decision boundary

The parent Linux IRQ is enabled after `IRQF_NO_AUTOEN` registration. After
ACTIVE acknowledgment sets `mmio_alive`, child runtime suspension is the
expected ISR barrier. If that state changes, the ISR can read INT_STAT and
write INT_CLR regardless of the selected step. Runtime resume can call
power-up, whose register writes precede later setup guards. PDR auto-enable N
blocks the UP auto-enable branch; it does not disable DOWN/cleanup handling.
Pinning prevents ordinary unload after QMI mutation, not every asynchronous
access. The disabled allow flags do not block stage-5 cases 1/2 writes.

Do not force runtime resume, change power/control, change stage live,
unload/rebind the pinned module, restart ADSP, or unbind/rebind MSM display.
**Stage-5 step 3 and interrupt enablement remain excluded**: the historical
6.18 experiment reset after successful disable readback. Stage 6 step 0
already performs writes and is outside this review, as are later transport,
DMA, codec and playback stages.

Only after M's completed archive is verified should root decide whether to
prepare N. Preserve `spx-known-good` as persistent default, use a distinct
one-shot request, recheck live boot ID and GRUB/EFI pending selection, and
retain the established logging/fallback procedure. Observe N for at least
600 seconds; independently record input outcome, desktop/EGL, Wi-Fi,
remote processors, guards and every reset/fault signature. Hash the completed
result before stopping its replacement fallback or selecting another trial.
An input failure remains a failed component result. The user authorized
these boots; automatic recovery from an early MMIO hang remains unvalidated.

Offline evidence is in `/var/tmp/spx-audio-stage5-l-review-20260922/`: the
source snapshot, installed-module notes, checker and `review.json` comprise
four verified files. `sha256.json` SHA-256 is
`4449d351e4883a6f910db4c6d5afd2004f80d197d61774066d27aa0860758344`.
Archive this evidence with the next preparation; no boot state was changed
by this review.
