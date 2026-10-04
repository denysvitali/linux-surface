# SQ2 Iris1 interrupt candidate, 2026-10-03

D03 remains **missing board integration / untested on hardware**. Linux Venus
now has an explicit Iris1 interrupt path: preserve the wrapper mask while
unmasking CPU bit2 and watchdog bit4, acknowledge a pending DSP source at CPU-CS
`0x104` with7, then a pending CPU source at`0x1c` with1. The Iris1 path does not
write the legacy wrapper interrupt-clear register. No existing OF resource
selects Iris1 yet. No DT, installed configuration, firmware load or boot selection
changed; latest actual mainline result remains [terminal AX](../RESULT-20261003ax.md).

The candidate changes [hfi_venus.c](../../../../drivers/media/platform/qcom/venus/hfi_venus.c)
and [hfi_venus_io.h](../../../../drivers/media/platform/qcom/venus/hfi_venus_io.h).
The earlier corrected camera-clock changes remain intact. This is preparation
for a dedicated SC8180X integration, with no claim of working video.

## Device evidence and policy

The [auditor](audit_contracts.py) verifies eight original ARM64 exception-bounded
ranges and41 instruction contracts in original2020 `qcdxkm8180.sys`, SHA256
`049da069400c124746e2f6ef0bd5851c603d865b3c1867e0c47c74e27c46220b`.
Selected linear disassembly and both original SMMU tables are retained. This is
not a complete control-flow graph or observed Windows execution.

`VedDecodeAndClearInterrupt` recognizes the normalized Venus510 version.
The examined direct-window path reads status at`0xe000c`. Its chip test
`(chip-0x4f) & 0xfffffff7 == 0` selects the`0x4f/0x57` branch. That branch
acknowledges status bit1 with7 at`0xd2104`, and bit2 with1 at`0xd201c`, with
barriers after each selected write. The legacy wrapper-clear write is on the
other-chip branch. Linux uses ordered `writel` operations in the candidate.
The assignment of a fitted SQ2 chip/live hardware-version value remains
unobserved. These source contracts justify an experimental Iris1 path, not
hardware acceptance or equivalence across every Iris1 platform/firmware.

The mask change follows the related Qualcomm Android `interrupt_init_vpu5`:
read the wrapper mask and clear CPU/watchdog bits, preserving other bits.
Its source explicitly calls`0x1f6` the reset mask, agreeing with the original
miniport's initial mask field. The miniport masks/unmasks sources elsewhere;
its initial value alone is not used as Linux's enabled mask. Android's generic
interrupt-clear routine still uses the older wrapper path, so that routine is
not evidence for the SQ2 DSP acknowledgement. The candidate combines the pinned
mask policy with the device-specific original acknowledgement contract.
Reference: [Qualcomm Android source at pinned commit28cc5c5](https://android.googlesource.com/kernel/msm/+/28cc5c521b21f92fa6f8a5a6be16960100f70a7a/drivers/media/platform/msm/vidc/venus_hfi.c).

## UC address policy resolved further

The Venus510 branch copies the original table at RVA`0x1b56b0` into engine
offset`0x7060`, and the ARID table at`0x1b58c0` into`0x7268`. Each has a16-byte
header and four72-byte context records. The first nonsecure record in both has
start`0x25800000` and length`0xba800000`, ending at`0xe0000000`. The original
startup calculation therefore yields **UC IOVA`0xdf000000`, window16MiB** when
those retained values are used. The ARID table identifies the first context with
`0x04030000`; the other contexts have`04090000/040a0000/040b0000`.

`VedInitVideoCore` passes this UC base to `VedVcmAlloc` with reserve-at1,
kernel-mapping-required1 and allocation output at engine`+0x120`. The selected
SMMU callback table points to `VedVcmAlloc` and `VedVcmReserveMemory`. The latter
uses the reserve-at operation and obtains the device address, rejecting addresses
above32bits. The former separately calls `MmAllocatePagesForMdlEx`, backs the
reservation and maps pages into CPU space. The original UC base thus describes
an **I/O virtual-address reservation**, not physical firmware storage. The queue
allocation size is three factor-dependent queues plus192 bytes and12KiB; it is
not a16MiB physical allocation merely because the UC window has that size.

Retained ASL `VideoNonSecurePT` declares a different pool (`0x100000` plus
`0xbff00000`). The relationship between that declaration and the miniport's
runtime tables remains unresolved; neither is relabelled as a live IOVA window.
No IOVA or physical-memory address is hard-coded into the Linux candidate.
Linux's existing UC/queue allocation path remains unchanged pending the complete
dedicated resource and firmware startup experiment.

## Validation and remaining integration

The [native reviewer](verify_interrupts.py) rehashes the inventory and re-decodes
all41 contracts. It compiles **verbatim current Linux `venus_boot_core` and
`venus_isr` bodies**, actual generation macros/enums/register definitions, and
the preserved pre-change function bodies. Only the pre-change function names
are renamed. Mock `readl/writel`, sleep and error reporting access synthetic RAM;
no codec, SMMU, Windows routine or firmware operation runs.

With `CONFIG_VIDEO_QCOM_IRIS` both disabled and enabled, **996 native cases**
pass:768 interrupt-status cases,216 startup success/error/timeout cases and12
absent-HFI cases. **820 comparisons** confirm identical register traces, return
values and IRQ status for the other generations. Iris1 checks use literal
device register addresses/values independently of the candidate macros. Three
changed DSP-acknowledgement, watchdog-bit and DSP-register candidates are rejected.
ASan/UBSan report no errors. The candidate diff has no whitespace, checkpatch
errors, warnings or strict checks.

The private [builder](build_venus.py) starts from the exact96937-file frozen AX
source and applies exactly four current source changes: the two previous camera
clock corrections and the two Iris1 files. Its configuration enables Venus and
V4L2 mem2mem and selected buffer helpers only in the private build. Aggregate
Venus core/decoder/encoder objects are built and linked for AArch64; this is not a full kernel link, loadable
module installation, boot or functional video check. Complete command output,
configuration deltas, source manifest/deltas and object provenance are retained.

Follow-up: the [power/memory candidate](../video-power-20261003/README.md) now
implements all-domain power, paired bridge resets and clock ordering, with
native failure tests and verified relocatable MDT loading. Hardware power and
secure loading remain unvalidated. Next add a dedicated SC8180X resource/binding/DT/config with
architecture2 and the evidenced nonsecure SID2300/mask60. Keep the ASL/miniport
virtual-address discrepancy explicit. Build/archive a full fresh candidate,
then record actual firmware/HFI startup and advertised formats before decoded
output, encoding, sustained playback, idle/resume and combined regressions.
Separate watchdog IRQ routing, runtime mask behavior and the rest of the packet
ABI remain unvalidated. Never re-arm terminal AX. All47 feature acceptance boxes
remain open; automatic recovery across EFI/early-kernel hangs remains unvalidated.

## Evidence locations

- `/var/tmp/spx-video-iris1-contracts-20261003-v3`:15 files, manifest
  `3bb3dfcd86755512b811bda2e955bce5083c2e42c2e93ffc53f550629f8eee21`.
- `/var/tmp/spx-video-iris1-review-20261003-v1`:34 files, manifest
  `020884464a59f7378ef5b984bc1ec0dc7fc5edca56c2041c006e282a0b21992c`.
- `/var/tmp/spx-video-iris1-build-20261003-v1`:29 top-level files, manifest
  `c7f973f60bfc7c1302e16b8ac04299acc755a2187286049db41c3c19a367d6cb`.
  Fresh source/output trees remain preserved with exact base and delta provenance.
- AX `offline-video-iris1-20261003`:183 files, manifest
  `3b915a9b6ca07d136a20819be407cbc7b258f6c0f96fe1ef37e5d3006bcc7396`.
  All96937 final private-source records independently verify against the frozen
  base and exactly four deltas. The only seven semantic configuration changes
  are Venus, mem2mem and selected buffer helpers; other new entries are disabled.
  Build/native artifacts, Kbuild files, discovery, intermediate contracts and
  fresh recovery/source provenance are sealed. Prior151 startup files, nine
  corrected clock/power sources and frozen AX/known-good recovery artifacts
  verify unchanged on boot`b6b4f20b`, release`6.18.3-1-surface+`, empty next/noBootNext.
  The archive contains a pre-seal README; reconciled records are frozen separately.
  Intermediate contracts v1/v2 and discovery disassembly stay
  preserved; the prior [native startup evidence](../video-startup-20261003/README.md)
  remains sealed and unchanged.
