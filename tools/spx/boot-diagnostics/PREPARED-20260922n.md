# SPX audio stage 5, step 0 — trial N, 2026-09-22

N advances the guarded audio probe from stage 4 to stage 5, explicitly
selecting step 0. It reuses the exact L kernel, modules, DTB and initramfs
that completed M. The release remains `7.3.0-rc2-spx-mainline-20260922l+`,
and the installed boot slot remains `/boot/spx-trial-20260922l/`.
No rebuild or module installation is needed.

[M's result](RESULT-20260922m.md) covers 734.11 seconds. All 288 result files
were hash-verified before stopping the replacement fallback. With startup
logging disabled, touch reached ready, all driver and SPI error counters
were zero, IPTSD remained active with no restarts, and virtual touchscreen
and pen devices appeared. Graphics, Wi-Fi, modem and audio stage 4 remained
healthy. This successful control does not establish an intermittent touch
failure fix or verify physical gestures. No recovery return occurred.

The [exact-L stage-5 review](AUDIO-STAGE5-L-REVIEW-20260922.md) verifies the
source and module. Step 0 adds reads of INT_STAT and INT_EN after the four
stage-4 reads, then stops. It performs no explicit synchronous MMIO writes;
the preceding QMI request still changes firmware state. The two new reads
are arguments of one log call, so their relative order is unspecified.
Keep the child runtime-suspended and all existing guards unchanged.

The ordered command line changes only the attempt marker and audio stage,
then appends the explicit step selector:

```diff
-spx_attempt=20260922m
+spx_attempt=20260922n
-slim_qcom_ngd_ctrl.spx_probe_stage=4
+slim_qcom_ngd_ctrl.spx_probe_stage=5
+slim_qcom_ngd_ctrl.spx_stage5_step=0
```

`spi_hid.startup_diag=0`, pinning, the 600-second observation window and all
other tokens remain unchanged. Require a successful QMI acknowledgment,
the actual INT_STAT value, INT_EN zero, the `stage 5 step 0: no writes`
marker, explicit stage-5 stop and child enable completion. Preserve any
unexpected register value without live corrective writes. No soundcard or
playback is expected at this stage. Stage-5 step 3 remains excluded because
of the historical delayed reset after interrupt enablement.

Origin boot: `5306363a-95b7-4d6c-b93f-c85118fdf8a5`.
M result SHA-256:
`bae83eac8a7dceafee26dffd0db6609362e89ea38cbc64da263b144899b97b38`.

| Artifact | SHA-256 |
| --- | --- |
| Kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

Preparation must preserve its own complete build archive and recheck all
payload, module, recovery and runtime hashes. Keep `spx-known-good` as the
persistent default, verify boot identity and pending GRUB/EFI selections,
and select N once. On continuation, check boot identity, uptime and return
timers first. If extending observation, arm a 20-minute replacement before
stopping the original timer. Hash the actual >=600-second result before
stopping that replacement or selecting another experiment.

No live audio stage change, forced runtime resume, pinned-module unload or
rebind, ADSP restart, or live MSM display unbind/rebind. Automatic recovery
across an early hang remains unvalidated. The user has authorized these boots.
