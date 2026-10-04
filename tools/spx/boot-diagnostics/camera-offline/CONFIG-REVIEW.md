# Offline camera configuration and build review

The six-symbol camera fragment resolves successfully. CCI, all three sensors
and CAMSS compile; **strict modpost and linking pass for all 16 camera and
support modules after a one-line CAMSS Kconfig fix in the isolated source**.
The active source/config and runtime were not changed. Nothing was installed,
loaded, probed or booted, and no full kernel build was performed.

## Result and source defect

`camera-review.config` requests VIDEO_DEV, VIDEO_QCOM_CAMSS, I2C_QCOM_CCI,
VIDEO_OV13858, VIDEO_OV5693 and VIDEO_OV7251 as modules. All six survive
olddefconfig. The inherited MEDIA_SUPPORT=m, camera/platform/V4L platform
support, ARCH_QCOM, IOMMU_DMA, clocks, I2C, regulators and media-controller
settings satisfy their prerequisites.

Unmodified Kconfig selects scatter-gather VB2 buffers, but local
`camss-video.c:177` and `:793` also reference `vb2_dma_contig_memops`.
Object compilation succeeds; strict modpost correctly fails on that missing
symbol. `VIDEOBUF2_DMA_CONTIG` is hidden, and the diagnostic
`camera-local-dependencies.config` is discarded by olddefconfig. The resolved
config after that diagnostic exactly matched the initial six-symbol result.

The proposed `camss-dma-contig-kconfig.patch` adds
`select VIDEOBUF2_DMA_CONTIG` to CAMSS. It passes `git apply --check` against
the active tree but **remains unapplied there**. Parent/root authorized its
application only in the isolated snapshot. With the patch, olddefconfig
selects VIDEOBUF2_DMA_CONTIG=m, and all 16 explicit .ko targets pass strict
modpost and final linking. No undefined-symbol warning bypass was used.
The first corrected-Kconfig attempt retained the old 15-target list;
the final passing invocation explicitly added videobuf2-dma-contig.ko.

## Effective configuration

`resolved.config` is the final full configuration; `effective-camera.config`
and `config.diff` expose the relevant result. Their `*-unpatched.*` versions
preserve the original resolution. Additional selected settings include:

- VIDEO_V4L2_I2C=y, VIDEO_V4L2_SUBDEV_API=y, VIDEO_CAMERA_SENSOR=y.
- V4L2_ASYNC=m, V4L2_FWNODE=m, V4L2_CCI=m, V4L2_CCI_I2C=m.
- VIDEOBUF2_CORE=m, VIDEOBUF2_V4L2=m, VIDEOBUF2_MEMOPS=m,
  VIDEOBUF2_DMA_SG=m and, after the isolated fix, VIDEOBUF2_DMA_CONTIG=m.

Olddefconfig also exposes the inherited camera-lens/radio menu defaults;
no unrelated camera or radio driver was added to the explicit build targets.

## Paths and exact commands

- Active source: `/home/dvitali/Documents/git/linux-surface-next`.
- Source commit: `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b` plus current tracked worktree changes.
- Work: `/var/tmp/spx-camera-config-20260922-6x_9qvel`.
- Clean tracked-source snapshot: `/var/tmp/spx-camera-config-20260922-6x_9qvel/source`.
- Isolated output: `/var/tmp/spx-camera-config-20260922-6x_9qvel/build`.
- Native toolchain: gcc 16.1.1 20260430; ARCH=arm64; four jobs.
- Baseline tracked changes: `/var/tmp/spx-camera-config-20260922-6x_9qvel/source-worktree.patch`.
- Exact final target list: `/var/tmp/spx-camera-config-20260922-6x_9qvel/module-targets.txt`.

Commands and exit statuses are retained in the phase logs. The successful
configuration/preparation commands were:

```sh
sh scripts/kconfig/merge_config.sh -m -O /var/tmp/spx-camera-config-20260922-6x_9qvel/build /var/tmp/spx-camera-config-20260922-6x_9qvel/base.config tools/spx/boot-diagnostics/camera-offline/camera-review.config
make -C /var/tmp/spx-camera-config-20260922-6x_9qvel/source O=/var/tmp/spx-camera-config-20260922-6x_9qvel/build ARCH=arm64 olddefconfig
make -C /var/tmp/spx-camera-config-20260922-6x_9qvel/source O=/var/tmp/spx-camera-config-20260922-6x_9qvel/build ARCH=arm64 -j4 modules_prepare
```

`camera-objects.log` records all five explicit driver object targets, successful
in 20.36 seconds. `camera-modules-patched-complete.log` records the exact final
16-target `make` command and success. It builds CCI, the three sensors, CAMSS,
media-controller core, videodev, V4L2 DV timings/async/fwnode/CCI, and five VB2
modules (common, memops, dma-sg, dma-contig and v4l2).

A copy of existing G `vmlinux.o` supplies kernel exports for strict modpost;
it was not rebuilt. Its baseline hash is in `build-inputs.sha256`.
The export tree has no .git metadata, so the module release is
`7.3.0-rc2-spx-mainline-20260922g` without the running kernel's trailing `+`.
These artifacts establish compile/link compatibility only; they are not a
complete deployable camera kernel and must not be installed into G.

Direct O= configuration against the active built tree was rejected by Kbuild.
No active cleanup was performed. The initial rsync snapshot was stopped after
163.89 seconds of file-list processing; a tracked-file tar stream then
completed in 101.39 seconds. Both attempts and the successful olddefconfig are
logged. The clean snapshot contains 96,180 tracked paths.

## Preserved evidence and integrity

`camera-modules.json` records paths, sizes, SHA-256, vermagic and dependencies
for all 16 modules. `camera-modules.sha256` and `camera-objects.sha256` provide
artifact manifests. The archive `/var/tmp/spx-camera-config-20260922-6x_9qvel/camera-build-evidence.tar.gz` contains all 16 modules, baseline
and final configs, tracked-worktree patch and the isolated Kconfig patch.
Its SHA-256 is `e785d3a1dfac0384e27b13aa0e882e6c4e6cf0395912e015e6e3231ec0af4978`; see `camera-build-evidence.sha256`.

All 47 active input hashes, including .config, Module.symvers, vmlinux.o and
camera source files, were verified unchanged after the final build;
`active-input-integrity.json` retains the comparison. The active CAMSS Kconfig
was separately compared with the isolated version and differs only by the
isolated added selector.

Active `.config` before/after SHA-256:
`bce9cd54b597a55c58e2264a94d25a877bf358dcc26f357d4673753471264bc2`.
Final isolated config SHA-256:
`0e30af08f4a7b8be4352ada8ec106b6cbaabb4463ab9e9618dcb033c12997784`.

Remaining work belongs to the camera integration review: apply/review the
Kconfig fix in the intended source branch, finish symbolic DT/binding and rail
ownership work, then build/archive a complete distinct camera candidate before
any hardware enumeration or capture trial. This review does not validate
DT topology, power sequencing, sensor communication or capture.
