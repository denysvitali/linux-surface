# SPX camera inventory — 2026-09-22

The next useful camera work is to reconstruct the proven v23 camera tree as
normal symbolic DT source and resolve its power-control integration. Raw
capture has already worked on all three cameras in the sibling tree; this is
not a fresh ISP or sensor-address discovery problem. No camera, I2C, SPMI or
MMIO operation was performed for this inventory.

## Current mainline state

Inventory boot: `3af15a82-c6ed-4d5e-b165-b332e3869793`, release
`7.3.0-rc2-spx-mainline-20260922g+` reused by trial H. The live DT contains no
CCI, CAMSS or camera sensor nodes, and `/dev/video*` is absent.

The active `.config` agrees with `/proc/config.gz`:

| Prerequisite | Current setting |
| --- | --- |
| `MEDIA_SUPPORT` | `m` |
| `VIDEO_DEV` | disabled |
| `I2C_QCOM_CCI` | disabled |
| `VIDEO_QCOM_CAMSS`, `VIDEO_OV13858`, `VIDEO_OV5693`, `VIDEO_OV7251` | absent because their dependencies are disabled |
| `SC_CAMCC_8180X` | `m` |
| `MEDIA_CONTROLLER`, `IOMMU_DMA`, `ARM_SMMU` | enabled |

The source already carries `qcom,sc8180x-camss` and its resource table in
`drivers/media/platform/qcom/camss/camss.c`, plus the SC8180X-specific
Spectra 390 GEN2 1.0 PHY profile selection in `camss-csiphy-3ph-1-0.c`.
The three sensor drivers and `i2c-qcom-cci.c` are present. CCI uses the existing
`qcom,msm8996-cci` fallback in the historical SPX DT; it has no separate
SC8180X match entry. CAMCC has its own binding, but SC8180X CCI/CAMSS binding
coverage is absent from the checked schema files.

The local CCI diagnostics and CAMSS `spx_stop_after` control are also retained.
The latter gates `s_stream()` stages in `camss-video.c`; it does not prevent
controller probe-time MMIO. The 7.3 CAMSS/CCI implementations differ from the
current 6.18 sibling, including upstream runtime-PM, CSID port/virtual-channel,
and VFE interrupt changes, so old binary modules cannot be reused.

## Existing verified capture evidence

The later status section of `../linux-surface-kernel/docs/spx-camera-recon.md`
supersedes that document's early speculation about mandatory ICP/Chromatix
work for raw capture. Its actual combined tree is
`../linux-surface-kernel/docs/camdtb/v23.dts`.

All nine entries in
`/var/log/spx-camera-archive/v23-multi-20260809/SHA256SUMS` verified during this
inventory. The capture logs each record successful STREAMON, two nonempty
frames and STREAMOFF:

| Sensor | Archived format | Bytes per frame |
| --- | --- | --- |
| Front OV5693 | 2592×1944 `pBAA` | 6,314,112 |
| Rear OV13858 | 2112×1568 `pgAA` | 4,139,520 |
| IR OV7251 | 640×480 `Y10P` | 384,000 |

The archive retains the raw pairs and decoded previews. The accompanying
notes report sensor test patterns disabled and real scenes. This is preserved
historical evidence, not a new capture test on 7.3.

The proven v23 topology differs materially from the standalone scaffolds:

| Sensor | CCI0 bus | MCLK | Reset/enable | PHY |
| --- | --- | --- | --- | --- |
| Rear OV13858 | 0 | 0 | GPIO22, active-low reset | 2 |
| IR OV7251 | 0 | 3 | GPIO23, active-high enable | 3 |
| Front OV5693 | 1 | 2 | GPIO12, active-low reset | 0 |

All three use 19.2 MHz MCLK and the tested CCI buses use 100 kHz. Preserve the
v23 graph's sensor/receiver lane distinctions and its verified IOMMU mapping;
do not regenerate them from a related SoC. The old
`drivers/spx_extras/spx-camera-sensors.dtso` instead contains guessed clocks,
24 MHz, different bus placement, 400 kHz and missing supplies. The old
`spx-camss.dtso` also has stale PHY windows. Neither is a deployable substitute
for v23 despite their `status = "okay"` declarations.

## Concrete remaining work

1. Extract a camera-only symbolic DTS/DTSI from v23, resolving numeric
   phandles against its own tree and named clock/GPIO bindings. Include CCI,
   sensor pinctrl, endpoints, CAMSS interrupts/clocks/interconnects and IOMMU
   references. Keep this offline and disabled until reviewed; do not copy the
   entire old combined platform tree over current audio/GPU/QRTR work.
2. Prepare a separate build-only camera config fragment enabling `VIDEO_DEV`,
   `I2C_QCOM_CCI`, CAMSS and the three sensor modules. Let Kconfig resolve the
   V4L2/VB2 dependencies; build the modules and DT without installing them.
   Add SC8180X schema coverage and validate the extracted topology against the
   current bindings and retained driver resource tables.
3. Design proper ownership and sequencing of the actual camera rails. v23's
   fixed, always-on supply nodes are placeholders: its companion script
   raises PMIC LDO14_A, LDO17_A and LDO1_A directly through the experimental
   SPMI helper before sensor binding. `spx_cam_power.c` deliberately refuses
   its old RPMh LDO14 vote because that path wedged the RSC and shutdown.
   Turning those placeholders into ordinary RPMh votes would regress that
   known failure. The direct helper source is retained, but it is not a
   production regulator/power-domain integration.
4. Only after those reviews, prepare a distinct logged camera boot and staged
   enumeration/capture plan. Existing capture scripts are historical evidence,
   not commands to run during the current audio trial. Real-frame verification
   and a processed/debayered userspace camera stream remain later milestones.

Provenance hashes:

- v23 DTS: `e69f2637abc57ec2eca28925ce9b3e5c984e1d0085f06c0f45d6148fb92899d7`
- capture manifest: `e7c3bb900154f61511bd98fa7a60cb668627677bffb7c231ab60ccbb8e524982`

Only this status note was added. No source, config, installed unit, boot entry
or runtime device state was changed.
