# 2026-10-14 Vulkan corruption: reproduced windowlessly, cause localised, workaround deployed

boxes closed: 3 of 47; newly closed: none. Boot `95e14bba-f6b5-4400-8091-b43fe585069f`,
7.3.0-rc2-spx-mainline-20261004bg+, Mesa Turnip 26.2.1. No reboot.
Automatic after this work: 25/49 functional pass, 34 blocked, 0 fail, 0 error.

- **Reproducer:** `tools/spx/mesa/partial-load-store.c` (headless Vulkan,
  every pixel compared with a CPU model). Unpatched driver, `TU_DEBUG=gmem`:
  about 890,000 of 5,529,600 pixels wrong after the first partial
  LOAD/STORE frame; `TU_DEBUG=sysmem` and the default autotuner: all correct.
- **Localised:** render areas aligned to 16x4 (fast event-blit store) are
  correct; unaligned areas, or `TU_DEBUG=unaligned_store`, are wrong inside
  the whole render area. Priming the tile buffer with a constant in one
  process and probing in the next returns that constant: the slow store reads
  **stale tile-buffer contents**, not the current pass. Storing through the
  per-tile resolve event into a staging buffer and copying the exact area
  (`SPX_TU_FIX=event_stage` experiment) is correct. So reading the tile
  buffer as a texture does not work on this GPU.
- **Refuted (each tested on hardware):** 2D vs 3D store engine, extra waits,
  sample-average bit, colour-cache flush before the store, FULL vs AVOID_CCU
  layout, colour-cache fraction, load alignment / 3D load, clear path,
  binning on/off, conditional load/store, low-32-bit address aliasing.
- **Deployed workaround, not a root fix:**
  `tools/spx/mesa/0001-turnip-a680-avoid-slow-gmem-store.diff` makes the
  A680 render in system memory for passes that would need the slow store.
  Private build in `/usr/local/lib/spx-turnip`, selected by
  `VK_DRIVER_FILES` in `/etc/environment` (new logins). With it the test
  passes under forced GMEM, forced unaligned store and defaults.
  `GSK_RENDERER=opengl` is left in place; GTK on Vulkan was not re-tested
  visually.
- **Row:** `graphics.vulkan.dynamic-damage` now runs the test in GMEM mode
  with the system's effective ICD: pass on this boot.
- **Open:** the proper fix is a staged event store (or whatever makes GMEM
  texture reads valid on A6xx gen2) upstream in Turnip; the override pins the
  driver across Mesa updates. See `tools/spx/mesa/README.md`.
