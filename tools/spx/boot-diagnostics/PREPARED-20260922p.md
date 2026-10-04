# SPX PIO receive/reactive-capability trial P — 2026-09-22

P is a distinct `7.3.0-rc2-spx-mainline-20260922p+` build containing the
reviewed NGD capability-retry correction. Every retry restores the original
message length before transfer consumes the length byte. The second hunk
corrects the misleading no-TX diagnostic. Touch, GPU, QRTR and other driver
logic remain unchanged from L; configuration changes only LOCALVERSION.

[O's final result](RESULT-20260922o.md) covers 611.87 seconds and 296 verified
evidence files. The isolated INT_CLR sequence completed with zero observed
statuses, but its separate unlogged operand remains unknown. Input startup,
FD680 graphics, Wi-Fi and remote processors stayed healthy. O performed no
recovery return. Physical input, sustained reliability and audio transport
remain unverified.

The [PIO source review](AUDIO-PIO-STAGE7-STEP6-20260922.md) defines P's scope:
controller enablement, continuing RX FIFO consumption and possible reactive
REPORT_SATELLITE transmission. It includes eight reads and three writes
before starting the thread; subsequent RX/TX activity is asynchronous and
has no fixed total count. This is a coherent transport diagnostic; it does
not register the SLIM controller or create a soundcard. Keep DMA, nonzero
INT_EN writes, full registration and PDR auto-enable disabled. The module
stays pinned and the child runtime-suspended. Existing SSR/removal/runtime
limitations remain as documented; no live recovery mutation is planned.

Relative to O's ordered command line, replace attempt O with P, stage 5
with 7, and stage-5 step 2 with 0. Append stage-7 step 6, PIO 1 and capability
retries 0 once. Every other selector and runtime policy remains unchanged:

```text
slim_qcom_ngd_ctrl.spx_probe_stage=7
slim_qcom_ngd_ctrl.spx_stage5_step=0
slim_qcom_ngd_ctrl.spx_stage7_step=6
slim_qcom_ngd_ctrl.spx_pio_mode=1
slim_qcom_ngd_ctrl.spx_pio_cap_retries=0
```

Step 6 returns before the proactive capability waiter. Reactive messages and
the worker's bounded NACK retries remain possible. Require successful QMI,
actual initial and CFG readback values, thread start/early heartbeats, the
corrected soak marker, stop-before-registration and child enable completion.
The helper can log errors while returning success, so those stop markers
alone cannot pass the test. No capability-DONE marker is expected at step 6.
No INT_EN readback occurs on this path; do not add a live register read.
Record all RX/TX, timeout, NACK, thread, PDR/SSR, IRQ, GPU and input outcomes.
A worker or first-FIFO log alone does not prove successful message delivery.

The full build/archive passed independent checks: 985 files, 272 symlinks,
187 modules with matching vermagic, 202 module-tree files, and all 54 actual
initramfs modules. Embedded configuration and private initrd logger match.
SPI-HID is loaded from the installed module tree, not the initramfs.

| Artifact | SHA-256 |
| --- | --- |
| Kernel | `dd6428bb9627b5bbff130b4b537663c7550ad1ce9a353caa6381aefa3fcd4d65` |
| Initramfs | `ed82fa0ed659fd1163682114f6be5f45c37fadec63b6da873f4402c557736f68` |
| DTB, unchanged | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| Configuration | `ae2115043d59097edb445500fbd0eac81e92279afc76ab6de223bea253640fcb` |
| NGD module | `e174c83da26a2909bfbc8aefa4891e51b53cf97d5c8b65ce02c31d88023d9e3a` |
| SPI-HID module | `1137075e1bc898a5408a7261e4b4bb8f3b996fa625c7da2e31c8a085e9010d03` |

NGD build ID: `9d798dbb17629e682c22a58b87a4e2049623c410`.
SPI-HID build ID: `a553336c86ec10a580b2842baf01be15e2c31d4c`.
Build manifest SHA-256:
`84df0c3afb1e75bf374f8f5027285f412539d948c860648ee40541c8cb96447e`.
The [artifact review](ARTIFACT-REVIEW-20260922p.md) records actual checks.

The retained origin is O boot `2e177f51-cc3c-482f-9203-faf678e0529c`, release L.
Its immutable result SHA-256 is
`14e612628f5d590ed590a108e78357d9cfa744f6599a89aecce11e66d01952e8`.
Installation must archive and hash the consumed L trial slot before freeing
its space for `/boot/spx-trial-20260922p/`. Keep L modules and the three
known-good recovery files. Preserve `spx-known-good` as persistent default,
verify the installed P module tree and payloads, recheck current boot ID and
GRUB/EFI pending selection, then select P once.

On continuation check identity, uptime and timers first. Arm a 20-minute
replacement before stopping the original 600-second timer when extending
observation. Archive and verify the actual >=600-second result before stopping
the replacement or choosing another test. No live NGD parameter change,
forced runtime resume, pinned-module unload/rebind, ADSP restart, or MSM
unbind/rebind. Automatic early-hang recovery remains unvalidated; the user
has explicitly authorized these experimental boots.

Deployment completed on O at 2956.98 seconds. All 202 installed module-tree
files, 187 modules, three P payloads, retained L modules and recovery hashes
passed. The consumed L slot is preserved under P's `retired-boot-slots/`;
only its three old `/boot` payloads were removed. Independent installed review
at 2992.54–2995.85 seconds passed and left no pending boot selection. Its
report SHA-256 is `18832ddd572bdb1b5606385370f0239b86718ed85becb7d97f1ce396af59473d`.
The reviewed queue SHA-256 is
`d04581b0aba99e37649412a896561a92cfba8df261c2e0ef67bba1b5af1e13c1`.
This records installation; the P hardware result must be collected after
its one-shot boot.
