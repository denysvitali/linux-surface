# SQ2 camera DMA and resource correspondence

C01 offline evidence, 2026-10-03, after actual AT returned automatically to
known-good UUID `74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b`. No new trial is selected.

The retained SQ2 IORT contains all **16** stream IDs described by the historical
`<&apps_smmu 0xa00 0x4e0>` specifier. The old v23 comment saying eight streams is
incomplete: mask bit `0x400` also covers `0x0e00` aliases. The complete set is
`0x0a00/20/40/60/80/a0/c0/e0` and `0x0e00/20/40/60/80/a0/c0/e0`.
It excludes the separate `0x20xx` ISP clients. Retain the mask; narrowing it to
`0x00e0` would lose eight firmware mappings.

The active UTF-16 `qcsmmu8180.inf` MAP records in both
`SMMU_V1_Registry_Settings_Dynamic` and `SMMU_V2_Registry_Settings_Dynamic`,
lines300/606, assign client1/VM4/CB21 the bytes `ff 0a 00 04 e0`. Its declared
SID/mask columns agree with v23 and the actual IORT mappings. The CB21
`S1_CAMERA_HLOS` label is a retained vendor comment; Linux allocates its own
context bank and must not be forced to CB21. No vendor binary is executed.

IORT node `\_SB.GPU0.AVS0` at table offset `0x1649` has31 mappings. Its requester
IDs `0x01030006` through `0x01030015` map individually to the16 camera SIDs,
with `id_count=0`, flags0 and output reference `0x30`, the SMMU at `0x15000000`.
The Linux IORT implementation defines `id_count` as count minus1, so each record
maps one ID. Reviewing all26 nodes finds no other apps-SMMU mapping overlapping
these16 IDs. ARPC's57 mappings are separate; it is the FastRPC component.
DSDT `GPU0.AVS0._DEP` references MMU0/IMM0/**VFE0**, corroborating the namespace
relation. This placement does not make the camera a Linux GPU DMA consumer or
authorize moving its mappings to the GPU driver.

All20 historical Linux MMIO ranges are contained in the matching firmware's
read/write resources. All20 IRQs have a corresponding edge/active-high GSI;
DT SPI numbers are GSI minus32. MPCS has four separate PHY ranges; VFE0 contains
eight combined VFE/CSID ranges, other ISP resources, a retained memory region
and24 interrupts. Only the20 CAMSS resources below are selected.

| Resource | Base | Size | SPI | GSI |
| --- | --- | --- | --- | --- |
| csiphy0 | 0x0ac65000 | 0x1000 | 477 | 509 |
| csiphy1 | 0x0ac66000 | 0x1000 | 478 | 510 |
| csiphy2 | 0x0ac67000 | 0x1000 | 479 | 511 |
| csiphy3 | 0x0ac68000 | 0x1000 | 448 | 480 |
| vfe0 | 0x0acaf000 | 0x4000 | 465 | 497 |
| csid0 | 0x0acb3000 | 0x1000 | 464 | 496 |
| vfe1 | 0x0acb6000 | 0x4000 | 467 | 499 |
| csid1 | 0x0acba000 | 0x1000 | 466 | 498 |
| vfe2 | 0x0acbd000 | 0x4000 | 463 | 495 |
| csid2 | 0x0acc1000 | 0x1000 | 462 | 494 |
| vfe_lite0 | 0x0acc4000 | 0x4000 | 469 | 501 |
| csid0_lite | 0x0acc8000 | 0x1000 | 468 | 500 |
| vfe_lite1 | 0x0accb000 | 0x4000 | 360 | 392 |
| csid1_lite | 0x0accf000 | 0x1000 | 359 | 391 |
| vfe_lite2 | 0x0acd2000 | 0x4000 | 761 | 793 |
| csid2_lite | 0x0acd6000 | 0x1000 | 759 | 791 |
| vfe_lite3 | 0x0acd9000 | 0x4000 | 760 | 792 |
| csid3_lite | 0x0acdd000 | 0x1000 | 476 | 508 |
| vfe3 | 0x0ace0000 | 0x4000 | 764 | 796 |
| csid3 | 0x0ace4000 | 0x1000 | 762 | 794 |

The VFE/CSID region splits are exact: each0x4000 VFE followed by its0x1000 CSID
tiles one firmware0x5000 range. Resource containment supports the address/IRQ
description, not programming compatibility with SC8280XP, clocks, interconnect
votes or analog wiring. Firmware still identifies Spectra390; the reused
CAMSS profile's version and register operations require separate validation.

Reproduce using system Python/libfdt and a fresh output directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_dma_contract.py /var/tmp/spx-camera-dma-contract-new
```

The12-file output's11-entry manifest is
`3fceaa9f67e3f4a965015ddf1246dab4c136fc3858607cd9de68dcc78e88c962`.
It preserves the full original DSDT/IORT/INF/v23 source/DTB, local Linux
IORT/SMMU/CAMSS implementation, audit source, reconstructed6467-byte IORT
(valid ACPI checksum) and complete JSON findings. Original source bytes remain
unchanged. Receiver analog supply ownership, capture, DMA fault behavior,
physical privacy and C01 acceptance remain open.

A separate review compares the reconstructed IORT byte-for-byte with the original
`acpidump.out`, checks all1396 numeric ACPICA fields against their declared
byte offsets, and verifies each of the eight VFE/CSID pairs exactly tiles its
firmware range. The20-file durable archive at
`/var/lib/spx-boot-diagnostics/attempts/20261003at/offline-dma-contract-20261003`
preserves original inputs/output, full raw dump, review and contemporaneous
records. Its `archive-sha256.txt` is
`34420817551d9cc27c7b5740c5bde49a489830a4a0ab543c8075c606996f9751`.
Current known-good boot/default, empty next entry, absent BootNext and all47
acceptance checks still open were verified during that archive.
