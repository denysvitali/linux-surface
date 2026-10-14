# A680 Turnip partial load/store regression

On Surface Pro X (Adreno 680), Mesa Turnip 26.2.1 corrupts GMEM render
passes that need the slow tile store: an area unaligned to 16x4, or
`TU_DEBUG=unaligned_store`. That store samples GMEM as a texture and reads
stale contents from an earlier render pass. Aligned fast event-blit stores
and system-memory rendering are correct.

Established on hardware on 2026-10-14: `partial-load-store.c` compares every
pixel of every frame with a CPU model. With unpatched Turnip and
`TU_DEBUG=gmem`, the first partial LOAD/STORE frame has about 890,000 of
5,529,600 wrong pixels. `0001-turnip-a680-avoid-slow-gmem-store.diff` selects
system-memory rendering for A680 passes that would need the slow store; it
passed with `TU_DEBUG=gmem`, `TU_DEBUG=gmem,unaligned_store` and default settings.
This is a workaround, not a root-cause fix or general Vulkan conformance.

`experiment-staged-event-store.diff` (`SPX_TU_FIX=event_stage`) also produced
correct pixels by resolving each tile through the event into a staging buffer,
then copying the exact area. It needs two earlier experimental diffs absent
from this repository and is not a standalone fix. This isolates reading GMEM
as a texture as the defect class. Refuted causes: 2D versus 3D store engine,
extra waits, pre-store CCU colour-cache flush, FULL versus AVOID_CCU GMEM layout,
colour-cache fraction, load alignment/3D load, clear path, hardware binning,
conditional load/store and low-32-bit address aliasing with a buffer.
`0001-turnip-bound-gmem-diagnostics.patch` contains the earlier bounded diagnostics.

## Driver build and installation

From a Mesa 26.2.1 source checkout, apply the workaround and configure an
incremental build directory (paths below are examples):

```sh
patch -p1 < /path/to/0001-turnip-a680-avoid-slow-gmem-store.diff
meson setup build-spx -Dvulkan-drivers=freedreno -Dgallium-drivers=
ninja -C build-spx src/freedreno/vulkan/libvulkan_freedreno.so
```

Meson needs Mesa's build dependencies. The maintainer's private build reused
the options of an existing build directory, rather than this minimal example.

The device installation has the driver at
`/usr/local/lib/spx-turnip/libvulkan_freedreno.so` and its ICD manifest at
`/usr/local/share/spx-turnip/freedreno_icd.aarch64.json`, pointing to that library.
The system-wide selection in `/etc/environment` is:

```text
VK_DRIVER_FILES=/usr/local/share/spx-turnip/freedreno_icd.aarch64.json
```

To revert, remove that line; existing processes must restart with the override
unset. This override pins Turnip across distribution Mesa updates: rebuild the
private driver or remove the override when Mesa is updated.
`GSK_RENDERER=opengl` remains set separately.

## Windowless test

Needs Vulkan headers and the Vulkan loader development library:

```sh
gcc -std=c11 -O2 partial-load-store.c -lvulkan -o spx-vk-partial-load-store
VK_DRIVER_FILES=/usr/local/share/spx-turnip/freedreno_icd.aarch64.json \
  TU_DEBUG=gmem ./spx-vk-partial-load-store
```

The installed binary is `/usr/local/lib/spx-turnip/spx-vk-partial-load-store`.
Its `Device:` line identifies Turnip and the driver build. `PASS; elapsed ...`
with exit 0 means every frame matches; `FAIL; elapsed ...` with exit 1 means a
pixel mismatch. Exit 2 is an error; exit 77 means no supported hardware Turnip
device. The automatic validator forces `TU_DEBUG=gmem` and uses the system ICD
selection; affected passes still use the patched driver's sysmem workaround.
