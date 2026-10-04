# GLES conditional discrepancy: measured readback and rounding model

The initially prepared diagnostic has now executed after AX's verified return
on known-goodb6b4f20b-376f-4577-b282-677ad4ae0ec8. The preparation narrative
below is retained as history; its sealed20-file packet remains unchanged.

The unprivileged offscreen GLES3.2 FD680/Mesa26.2.1 run exits0 with30 renderD128
FD witnesses and unchanged4096 taint. It reports medium precision10 bits and
range15/15. Its nondithered RGBA8 step readbacks are:

| Steps | Mediump | Highp |
| --- | ---: | ---: |
| 0 |160|160|
| 1 |64|65|
| 2 |193|194|
| 3 |132|133|
| 4 |9|11|
| 5 |27|33|

Mediump reproduces the original default-precision failed27 pixel. Highp33 falls
within the original37±5 per-channel oracle tolerance. Original failed glmark2
evidence remains a Failure; no validator or frozen AX criterion is changed.

The first CPU model assumes round-to-nearest half conversion; that assumption
predicts36 and does not match the actual27. A distinct
[round-toward-zero model](gles-precision-rtz-review.py) instead predicts **all12
measured pixels exactly**. It includes half conversion of mediump d/arithmetic
and, for both variants, conversion at the mediump gl_FragColor output before
normalized8-bit color rounding. Initial d becomes0.62646484375 instead of the
round-to-nearest0.626953125; the five conditional steps amplify that difference.
Each modeled half conversion stays within a relative2^-10 storage error on
these values. GLSL ES1.00's mediump declaration for gl_FragColor also explains
why the highp-arithmetic output model requires a final lower-precision conversion.
[Khronos specification](https://registry.khronos.org/OpenGL/specs/es/2.0/GLSL_ES_Specification_1.00.pdf),
sections4.5 and7.2. This is an exactly matching numerical hypothesis, not actual
instruction tracing or general driver conformance certification. The measured
diagnostic has not run on the mainline candidate; that comparison remains open.

Actual5-file diagnostic manifest:
`158c033f226813e471fd0d256ba65dc81ec9b135d909ae1200a9a1da76aa5ee1`.
Independent3-file rounding review manifest:
`b537d54f7655a00b61a07896eca79e4172e7780be10cd31598ac16092fda78df`.
Archives under `/var/lib/spx-boot-diagnostics/gpu-workloads/`:
`20261003-precision-readback-result/` and `20261003-precision-rtz-review/`.
The [guarded runner](run-gles-precision-readback.py) requires actual AX return
review, uses a30s deadline/raw stdout/stderr/5ms FD sampling and seals failures.
It was demonstrated to reject actual AX before launching the executable.

D02 remains open. The frozen glmark2 reference records expected RGB0x25 and
actual0x1b with the default mediump fragment shader on FD680/Mesa26.2.1. The
explicit highp variant passes. Original logs, shaders and failed XML remain
unchanged in the sealed1651-file AU GPU workload archive. Neither result is
relabeled, and the AX sustained workload/criteria remain frozen.

[CPU rounding model](gles-precision-model.py) uses the actual read_pixel(293,89)
and a pixel-center coordinate hypothesis(293.5,89.5). The frozen CanvasGeneric
passes that read coordinate directly to glReadPixels; it does not flip Y.
With initial arithmetic binary32, five conditional steps predict RGB34 under
binary32 rounding and36 under binary16 storage/arithmetic. Neither reproduces
the retained27. This rejects the simple explanation that half precision alone,
with that evaluation order, accounts for the observed pixel. It does not reject
all permitted precision/optimization explanations or establish a driver defect.

GLSL ES1.00 specifies minimum precision and permits implementations to provide
more; expression precision follows operands, and queries expose actual reported
ranges/precision. Those rules motivate measuring intermediate readback rather
than declaring the arbitrary benchmark oracle universally exact.
[Khronos specification](https://registry.khronos.org/OpenGL/specs/es/2.0/GLSL_ES_Specification_1.00.pdf),
sections4.5 and5.12–5.13. This is an inference, not a conformance result.

[Prepared native diagnostic](gles-precision-readback.c) compiles with
gcc -std=c11 -O2 -Wall -Wextra -Werror and pkg-config EGL/GLESv2/GBM.
It opens only renderD128 as an unprivileged user, requires FD680 and a GBM EGL
surfaceless GLES3 context, and renders a triangle to an800×600 RGBA8 framebuffer.
It reports GL/EGL versions and glGetShaderPrecisionFormat, then records pixels
at each of0–5 steps for default mediump and highp. No DRM master, connector,
modesetting, live binding/module/power operation or boot selection is requested.
Its explicit nondithered framebuffer differs from glmark2's default context,
so it is a diagnostic comparison rather than a substitute validator.

The diagnostic has **not run on hardware**. Do not execute concurrently with AX's
frozen sustained workload. First collect AX's RTC/GPU/final result and actual
guarded known-good return; then run the separate bounded diagnostic with exact
boot/artifact/userspace provenance, stdout/stderr and render FD evidence. Context
or framebuffer failure must be retained as failure, not silently retried through
another renderer. Any mismatch remains open pending measured values and compiler
evidence. Vulkan, visible desktop/panel correctness and full D02 acceptance are
still untested by this preparation.
