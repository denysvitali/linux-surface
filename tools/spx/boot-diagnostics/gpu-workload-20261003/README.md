# AU offscreen GPU workload preparation

Targets D02 and supplies regression evidence for F02. This is a prepared test;
the sustained run on AU has not happened and no hardware acceptance is closed.

Unmodified glmark2 tag2023.01, commit
`42e3d8fe3aa88743ef90348138f643f7b04a9237`, builds two native ARM64 GBM
executables. The GBM backend opens explicitly selected `/dev/dri/renderD128`;
it does not call DRM master or modesetting functions. Its separate DRM backend
does query display resources even for offscreen rendering, and is excluded.
Sources: [pinned GBM backend](https://github.com/glmark2/glmark2/blob/42e3d8fe3aa88743ef90348138f643f7b04a9237/src/native-state-gbm.cpp),
[pinned offscreen canvas](https://github.com/glmark2/glmark2/blob/42e3d8fe3aa88743ef90348138f643f7b04a9237/src/canvas-generic.cpp).

`plan.json` specifies800×600 rendering,15 scenes per API,60seconds per scene,
three30second idle windows per API and expected-image validation before/after.
That is1800seconds of rendering across OpenGL and OpenGL ES, plus180seconds idle.
The scenes cover array/VBO drawing, texture filters, lighting, conditional
shaders, bump maps, simulated desktop blur/shadows and buffer updates. This
does not establish Vulkan, video acceleration, visible panel correctness or
heavy compositing by the actual desktop shell.

The root collector runs the benchmark as the existing unprivileged user with a
clean environment, records each open DRM node, preserves raw XML/stdout, and
checks exact scene/options/duration, hardware renderer, API and positive timing
results. Kernel logs, taint, GPU runtime-PM counters, frequencies, thermals,
connectors and the same running GNOME Shell process are observed. There is no
display, power, governor, driver binding or module change. A subprocess deadline
does not recover a kernel hang; the separately authorized one-shot/recovery loop
is still required for AU. The collector does not select or deploy a boot.

On known-good UUID`74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b`, release
`6.18.3-1-surface+`, the final reference smoke uses one-second scenes/idle windows.
Ten executions pass:60 expected-image checks and30 timed scene rows. OpenGL4.6
compatibility and OpenGL ES3.2 contexts report `FD680`, freedreno,
Mesa`26.2.1-arch1.1`. FD samples show only renderD128. GPU active/suspended states
are observed, GNOME Shell retains its PID/start time and taint remains4096,
the known-good kernel's existing out-of-tree module bit. AU requires initial
taint0. This short older-kernel reference is test preparation, not D02 acceptance.

Original failures are preserved:

- Pacman's download user could not traverse the initial0700 temporary directory.
  Retrying with traversable public benchmark directories succeeded; package and
  detached signature verify against the Arch Linux ARM build key. Nothing was
  installed or upgraded. That package lacks GBM binaries, so the actual fixture
  comes from the pinned native source build.
- The initial collector correctly rejected known-good's4096 taint under its
  candidate-only zero-taint assumption, before rendering. Reference mode now
  requires a stable initial value; candidate mode still requires zero.
- Cel shading has no expected-image validator and reports Unknown. It was
  replaced before the plan froze; Unknown is never accepted as Success.
- Default-precision GLES conditional validation reports Failure: expected
  RGB`0x25`, actual`0x1b`, distance17.320508. Desktop GL passes the same scene;
  requesting fragment precision`default,high,default,default` makes GLES pass.
  Debug output preserves the original `mediump float` shader and high-precision
  comparison. A requested software control still reported FD680, so it is not
  evidence about a software renderer. The remaining precision/oracle difference
  is unresolved; it is not relabeled as a pass or proven kernel defect. The
  sustained plan explicitly tests high precision for this scene. The language
  permits distinct precision guarantees, which motivates this inference but
  does not prove this particular numerical result is conformant.
  [GLSL ES precision rules](https://registry.khronos.org/OpenGL/specs/es/2.0/GLSL_ES_Specification_1.00.pdf), section4.5.
- A substring fault matcher falsely matched `Default` in a normal IOMMU message.
  Word boundaries fix the observer. Raw failed and corrected results are retained;
  the unchanged positive fault cases still reject GPU/IOMMU failures.

Independent replay recomputes all ten final results from the archived XML.
Eight altered XML fixtures are rejected: software renderer, Unknown, Failure,
zero FPS, wrong duration, missing scene, wrong scene and wrong API. Nine actual
kernel-style fault signatures are detected, including GMU watchdog and MSM
hangcheck/lockup; the benign IOMMU default message is not considered a fault.
The final matcher extension was replayed against the same raw smoke evidence;
the exact collector used for that smoke is preserved separately.

Durable archive:
`/var/lib/spx-boot-diagnostics/gpu-workloads/20261003au`,1651 files, rehashed manifest
`6994fa099d486ceb63259d3bd52bc2554afe447344c98e02a7db4611e1906ce4`.
It contains source, binaries/assets, toolchain/package evidence, all failed
iterations, precision comparisons, final smoke, both reviewers and negative
fixtures. Final smoke manifest:
`f95ad4d9751ed0ac66f5e832688dd7a5958c9949cbc82fbee9c11f5607c28ed7`.

Next: finish/archive the distinct AU full build; review installed boot/recovery
and bounded collection, boot once and collect the actual sustained result.
Keep D02/F02 and the other hardware checks open until their functional criteria
and common-final-candidate requirements are met.
