# SPX audio bring-up - status & next steps (2026-06-10, evening)

## THE ROOT CAUSE (found!)
`qcom-ngd-ctrl.c` had the QMI power enum **swapped** by an old experiment:
`SLIMBUS_PM_ACTIVE_V01 = 1 / INACTIVE = 2` (canonical wire encoding is
INACTIVE=1 / ACTIVE=2). Every "power on" we ever sent was a power-OFF.
The ADSP acked it (valid request), block stayed gated, registers read 0,
capability exchange timed out. Fixed; verified: after the fix, stage 3 read
`ver=0x202`, cfg=0x2020000 — NGD alive for the first time.

All historical lore from before this fix is suspect, including the
"MSFT firmware collapses the core on power-off" comment in runtime_suspend
(observations were made with inverted on-wire semantics).

## Fixes landed in source today
1. Enum swap reverted; select_inst TLV order restored (instance 0x01 first).
2. ISR gated by `ctrl->mmio_alive` (set on power-on ack, cleared on
   power-off/QMI exit) - NGD MMIO while gated wedges the CPU silently.
3. Teardown restructured: `qcom_slim_ngd_ctrl_remove` now releases PDR and
   unregisters the SSR notifier unconditionally. Previously these lived in
   the CHILD remove, which never runs when the child probe fails -> unload
   leaked a live SSR notifier -> oops in freed module text on ADSP stop
   (this killed boot #3 today when restarting remoteproc2).
4. BAM DMA IRQ now returns `IRQ_NONE` on empty source status and logs the
   first IRQ sources. The previous stage-7 crash looked like a hardirq storm,
   but NGD ISR did not log at all, so BAM is the next suspect.
5. Stage 6 now has deeper descriptor/BAM logging instead of more stop points:
   RX/TX channel request, coherent buffer addresses, every RX descriptor
   submit, BAM prep/issue/start, channel register init, and the EVNT_REG kick.
6. Stage 6 now tears DMA back down before returning. The previous build left
   RX pipe 3 armed after staged probe completed; the machine started missing
   DPU frame deadlines about 150 ms later, after `EVNT_REG write done`.
7. BAM now treats `bam_clk` as required when the DT supplies a `clocks`
   property. The booted DT has `clocks = <&lpasscc 1>` but BAM previously
   probed with `has_clk=0`, leaving `lpass_q6ss_ahbs_aon_clk` unvoted while
   RX DMA was kicked.
8. Root cause of `has_clk=0`: `sdm845-lpasscc` registers two QCOM clock
   providers on the same OF node. The second provider, for QDSP6SS clocks,
   shadows the first provider, and its sparse table has NULL at IDs 0/1.
   `qcom_cc_clk_hw_get()` now returns `-ENOENT` for sparse holes so OF clock
   lookup can continue to the earlier AHB provider.
9. BAM with a real clock still needs the DT `num-channels` / `qcom,num-ees`
   values because this remotely controlled block can report zero if its
   hardware ID registers are read before the SLIMbus/ADSP side is fully
   powered. The driver now always seeds those DT values when present.

Installed 2026-06-10 23:02:
- `/boot/vmlinuz-linux-surface`
  `5ccc9915d444e42045f86704427a72e31beea85a2d40ef22507e014d97833ab8`
- `/boot/dtb/qcom/sc8180x-surface-pro-x.dtb`
  `ac2d311c5f32c9e43664e819b1ee26b008fdd671642ffe91989ae9df323cd051`
- `/lib/modules/6.18.3-1-surface+/kernel/drivers/slimbus/slim-qcom-ngd-ctrl.ko`
  `9e594a1f3a32d3868c4456c7a1f3d913c530917ffef81d68036a07bdecbaba24`

Backups were created with suffixes `20260610-214101`, `20260610-220702`, and
`20260610-222311`, plus kernel-only backups `20260610-223803` and
`20260610-225404`, `20260610-230215`.

## Hard-won operational rules
- NEVER read 171c0000+0x2000 (wedges CPU permanently; killed boot #1).
- NEVER pass `spx_select_mode=1` (explicit satellite TLV): firmware rejects
  it with error 0x5a AND the SLIMbus QMI service then refuses ALL further
  power requests (result 0x1) until ADSP restart/reboot. Omit mode (default).
- Avoid unload/reload cycles when possible; boot #2 died on a reload right
  after the first real power-on/off cycle (suspected stale level IRQ +
  gated MMIO read in ISR — now guarded by mmio_alive, unproven).
- ADSP restart (`echo stop > /sys/class/remoteproc/remoteproc2/state`) was
  the trigger for the notifier UAF — safe only with the fixed module.

## After reboot
Module is blacklisted; nothing autoloads. `spx_probe_stage` defaults to 1 and
`spx_select_mode` defaults to 0, which means the mode TLV is omitted.

First command after boot:

    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=6

Before modprobe, verify the new BAM clock behavior:

    dmesg -T | grep 'SPX: BAM probe' | tail -1

Expected:

    SPX: BAM probe ... has_clk=1 preset_channels=23 preset_ees=4
    SPX: BAM init done channels=23 ees=4
    SPX: BAM DMA registered irq=132 channels=23

If BAM says `failed to get bam_clk`, `bam_clk lookup returned NULL`,
`has_clk=0`, or fails probe with `-22`, do not run the stage-6 probe; fix
the BAM/clock setup first.

Stage 6 stops before `NGD_CFG_ENABLE`. It powers on through QMI, writes the
safe NGD interrupt/rx-timeout registers, requests BAM RX/TX channels, posts RX
DMA descriptors, and then stops.

Expected stage-6 log shape:

    SPX: staged QMI power request acked
    SPX: top-level NGD raw version register=0x2020000 ver=0x202
    SPX: child NGD interrupt/rx-timeout writes done
    SPX: DMA init start
    SPX: DMA init RX phase
    SPX: requesting RX DMA channel
    SPX: BAM alloc[...] pipe=3 ...
    SPX: RX DMA channel requested ... chan_id=3
    SPX: RX desc[0] prep ...
    SPX: BAM prep[...] pipe=3 ...
    SPX: RX desc[31] submitted ...
    SPX: BAM issue[...] pipe=3 ...
    SPX: BAM start[...] pipe=3 calling init_hw
    SPX: BAM pipe=3 writing P_RST assert/deassert
    SPX: BAM pipe=3 writing DESC_FIFO_ADDR=...
    SPX: BAM pipe=3 writing P_CTRL=...
    SPX: BAM start[...] pipe=3 writing EVNT_REG=...
    SPX: RX DMA descriptors issued
    SPX: DMA init TX phase
    SPX: requesting TX DMA channel
    SPX: BAM alloc[...] pipe=4 ...
    SPX: TX DMA channel requested ... chan_id=4
    SPX: DMA init done
    SPX: staged DMA cleanup start
    SPX: terminating RX DMA channel chan_id=3
    SPX: BAM terminate pipe=3 ...
    SPX: releasing RX DMA channel chan_id=3
    SPX: BAM free pipe=3 ...
    SPX: RX DMA channel released
    SPX: terminating TX DMA channel chan_id=4
    SPX: TX DMA channel released
    SPX: staged DMA cleanup done
    SPX: stopping after staged hardware probe (spx_probe_stage=6)

The previous stage-6 build reached `DMA init done`, then DPU frame timeouts
started shortly after, with no NGD or BAM IRQ logs. If this build stays stable,
the crash was caused by leaving RX pipe 3 armed after the staged probe. If it
still causes DPU frame timeouts or input lag, the last `SPX: BAM ...` line
before the timeouts is the important one. Collect dmesg and do not jump to
stage 7.

If stage 6 is stable, reboot fresh and then run:

    sudo modprobe slim_qcom_ngd_ctrl spx_probe_stage=7

Expected: "QMI power-on acked" → "NGD ver=0x202, waiting for capability
exchange" → "capability exchange DONE" → "SLIM controller Registered" →
wcd9340 enumerates (DTB has codec@1,0 under slim@1; wcd934x mfd + codec
modules are installed).

If capability exchange times out: do NOT unload/retry blindly; collect
dmesg first. The IRQ (GIC SPI 163) and BAM DMA rx path get exercised for
the first time at this step.

## After codec enumerates
sound card: board dts has SLIM Playback/Capture dai-links (q6afe SLIMBUS_0)
+ wcd9340; machine driver + UCM needed (see c630 as reference: alsa-lib
>= 1.2.4, sdm845 UCM2 profiles).
