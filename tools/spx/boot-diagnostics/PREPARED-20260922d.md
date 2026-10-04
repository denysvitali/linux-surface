# SPX A680 GBIF initialization candidate — 2026-09-22

**Result: bounded graphical trial passed.** GNOME ran through the three-minute
window and the return service completed an orderly reboot. The previous HFI/GMU
failure did not recur. See [RESULT-20260922d.md](RESULT-20260922d.md) for
evidence, remaining component failures and validation limits. The preparation
description below is historical.

Trial `20260922d` tests one GPU code correction after
[C reproduced the graphical hang](RESULT-20260922c.md) without custom GPU
frequency writes. It adds `.gbif_cx = a640_gbif` to the A680 catalog entry.

Commit `60a4e18e0e8a` moved four `GBIF_QSB_SIDE*` register writes out of GPU
`hw_init()` into catalog-driven GMU initialization. The previous family check
included A680, but its catalog entry omitted the new pointer. This restores
the four existing `0x00071620` values using the refactored initialization path.
Two independent source reviews confirmed the omission. Whether it causes
this device's graphical hang remains a hardware-test question.

The release is `7.3.0-rc2-spx-mainline-20260922d+`, based on source commit
`907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b` plus archived worktree changes.
Relative to A/B/C, the kernel code changes only the A680 catalog pointer;
the earlier framebuffer flag correction remains. The active config changes
only `CONFIG_LOCALVERSION`. The CMAC board-fragment correction remains staged
for a later build and is deliberately absent from this test.

The graphical target, `spx_gpu_profile=skip`, unchanged DTB, early logging,
APSS watchdog and 180-second return timer match C. The collector additionally
records cached SMEM highest-bank-bit and DRAM-frequency debugfs data. This
supports investigation of a separate UBWC change if needed; no UBWC code
change is included in D.

## Verification and archives

- Native Image, DTB and all 185 modules built; embedded config matches exactly.
- Staged and installed module dependencies pass without diagnostics.
- All 55 diagnostic tests and strict checkpatch pass.
- Initramfs contains the exact rebuilt MSM module, executable initrd logger,
  matching service and its enablement link. Kernel compression round-trips.
- The first initramfs assembly omitted standard hooks because `-D` overrides
  the search path. Its failed image/log are retained. Explicit custom,
  `/etc/initcpio` and `/usr/lib/initcpio` roots produced the verified image.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `59ede5f419cb94428892fa67e4f51041acc45faad11968ad671bebd25f135c6e` |
| Initramfs | `1df17aed6fbe7f352b4dbe33d5a10694fc9bc274284ea3f6b14c952f894ff0ed` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| MSM module | `4e64bf093c24cc40d695229db9f61bffc33fd3dfe770d2e33514099b58cfa54f` |

The complete permanent archive is
`/var/lib/spx-boot-diagnostics/attempts/20260922d/`; `build/` includes source,
config, binaries, all modules and validation logs. Installed boot paths are
under `/boot/spx-trial-20260922d/`. The completed A/B/C boot slot was copied,
hash-checked and retained as `retired-boot-slot/` before reclaiming its space.
The known-good kernel, initramfs and DTB remain unchanged and hash-verified.

Preboot recovery ID is `a1bd085a-2694-42d6-9cb1-951281c968e1`. Read the
actual manifest and `reboot-requested` marker before selecting any boot;
this note is not a successful-test result. Keep `spx-known-good` persistent
default and select D once. Preserve its trial and recovery evidence before
the next experiment. No live MSM unbind/rebind.

The continuation helper now explicitly selects Happy's remote daemon mode,
avoiding C's interactive `stdin is not a terminal` failure. Thirteen helper
tests pass, but automatic post-reboot prompt delivery still requires verification.
