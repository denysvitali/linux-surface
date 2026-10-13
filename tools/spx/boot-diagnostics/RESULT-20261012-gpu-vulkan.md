boxes closed: 3 of 47; newly closed: none.

# GPU Vulkan investigation in progress

Boot6272005e-0a08-41e9-b9b6-2166ff0a04f1,
kernel7.3.0-rc2-spx-mainline-20261004bg+, Mesa26.2.1/GTK4.22.4/Mutter50.4.
User requested full GPU support/parallel agents, explicitly reopening Vulkan
investigation. D02 recorded GL/GLES evidence remains closed; no Vulkan/full-GPU
acceptance claimed. Four bounded workers: Turnip, GTK, MSM, Wayland presentation.

Coordinator rendered saved public widgets.node via native gtk4-rendernode-tool
Vulkan andGL. Both visually clean; diff sparse edge pixels, no repeated strips.
OffscreenPNG proves this fixture/render-texture path, not compositor/scanout.
Retained6.18 Vulkan reference also clean;2.96% versusCairo alone is not proof
of corruption. CLI renderer name is gl (opengl rejected, then corrected).
Visible widgets preview explicitly selects GskVulkanRenderer on TurnipAdreno680
(API1.3.354), Wayland scale2:1052x829logical->2104x1658swapchain, mailbox.
User asked to inspect text and resize once; physical appearance pending.
No new kernel GPU/IOMMU/hang warnings or boot change. NormalOpenGL defaults
untouched. No MSM unbind/reload, reboot, sound or camera/microphone capture.

FD680 supported in Mesa; existing kernelUBWC parameters override fallback.
No numeric hbb/swizzle/SoC-alias patch justified. No constants/source changed.
Logs/images /var/tmp/spx-gpu-vulkan-20261012/; original corruption TextEditor may still be specific to
WSI, scale or app workload; clean fixture does not prove that bug resolved.
Matching-scale2x fixture Vulkan also visually clean, sparseGLedge differences.
Exact upstreamMesa#15349: SPX/a680GTK Vulkan glitch; sysmem avoids, unaligned_store
worsens (note3450413). Indicates GMEM/damage path, not unsupportedFD680. No fix
claimed. Next one scrolling/damage workload baseline vs per-processTU_DEBUG=sysmem,
plus live readonlyDRMUBWC query. Native partialGMEMstore source uses CP_BLIT,
while full-image offscreen can use fastBLIT_EVENT_STORE; clean staticPNG does
not rule out this path. User now reproduces scroll corruption in publicfixture: screenshot shows repeated
colored strips below rows15/16. Identical per-processsysmem comparison started;
User reports same scroll/resize actions clear with TU_DEBUG=sysmem. Both select
GskVulkanRenderer/TurnipAdreno680; one process variable changed. This verifies
GMEM avoidance workaround on real display, not rootcause or fullVulkan support.
Both test windows stopped, device lock released, persistent defaults unchanged.
BoundedGMEMCPU-side diagnostic2f296f119a36 saved under tools/spx/mesa; private
Mesa26.2.1 configure and Turnip-only build passed (exit0), private devenvICD ready.
LiveGPUtest deferred while concurrent user-requested Chromium/Venus recovery
session owns device; canonicalkernelbuild lock handed over, no GPUdevice action. No packets/renderselection
changed. Limits256 selectedpasses/512 emittedstores; conditionalstore log is
notGPU-execution proof. PrivateICD only; distrodriver untouched. Build initially
failed generatorMako selection; retry uses projectvenvPATH+MesonnativePython. ReadonlyDRM query
currentHBB16/swizzle6/macrotile1; no numeric correction inferred. Forced supported
unaligned_store on same2x offscreen fixture produces byte-identical render pixels;
this alone does not reproduce dynamic damage failure. No patch justified yet.
No broad extraGL tests or fake full support.
