# Surface Pro X (SC8180X) camera stack — reverse-engineering notes

## Scope

This document captures static-analysis findings from the Windows ARM64
camera driver dump at `/home/dvitali/Documents/drivers/` and the
ICP firmware it ships. It is the input to the (future) reverse
engineering of the SC8180X Spectra 390 ISP register layout.

What is **in** scope here: identify the chip variant, map the
firmware's IPC command surface, document the proprietary tuning blob
format, and enumerate the work the Linux CAMSS port will need to do.

What is **out** of scope here: reverse-engineering the CSID/CSIPHY/VFE
register definitions, porting the chromatix blob parser, decoding the
ICP ↔ CPU shared-memory protocol.

## 1. Hardware facts (confirmed)

| Item | Value | Source |
|---|---|---|
| SoC | Qualcomm SC8180X (Snapdragon 8cx / SQ1) | `qccam*8180.sys` filenames |
| ISP | Qualcomm Spectra 390 | `qccamisp8180.inf` ("Spectra 390 ISP") |
| Titan variant | TITAN 170 v2 | `chipInfoTitan170v2` string in ICP ELF |
| CSI PHYs | 4 (`MipiCsiPhy0..3`); 3 used on SPX | `qccammipicsi8180.sys` strings |
| CCI busses | 4 (`cci_0..3` in `camcc-sc8180x`) | `drivers/clk/qcom/camcc-sc8180x.c` |
| MCLK outputs | 8 (`mclk{0..7}_clk_src`) | `camcc-sc8180x.c` |
| Rear sensor | OmniVision **OV13858** (13 MP, 4-lane) | `surfaceprox_camrear.inf` (`OVTID858`) |
| Front sensor | OmniVision **OV5693** (5 MP, 2-lane) | `surfaceprox_camfront.inf` (`OVTI5693`) |
| IR sensor | OmniVision **OV7251** (VGA, 1-lane) | `surfaceprox_camaux.inf` (`OVTI7251`) |

ACPI HIDs (for cross-reference with the Windows-side topology, only
useful if booting Windows to dump ACPI tables):

| HID | Device |
|---|---|
| `QCOM0435` | Camera Platform Device |
| `QCOM0428` | Camera ISP Device (loads `CAMERA_ICP_AAAAAA.elf`) |
| `QCOM04A4` | Camera MIPI-CSI Device |
| `QCOM0436` | Camera JPEG-E Device |
| `QCOM0406` / `OVTI5693` | Front (OV5693) |
| `QCOM0429` / `OVTID858` | Rear (OV13858) |
| `QCOM04A5` / `OVTI7251` | IR (OV7251) |

## 2. ICP firmware analysis (`CAMERA_ICP_AAAAAA.elf`)

### 2.1 Format

- 3,597,528 bytes
- ELF 32-bit LSB, **ARM** EABI5, statically linked
- `Section` names look Hexagon-ish (`REX_CORE_RO`, `REX_CORE_RW`,
  `SysLibArmRom`, `AMSS_HEAP_SEG`, `PAGE_TABLE`) — leftover from
  the QC Hexagon toolchain. The ELF machine type is ARM; treat the
  code as ARM32 Thumb-style.
- **Not stripped, has debug_info.** 11,277 symbols, 1,831 functions.
- Section layout (high level):
  - `REX_CORE_RO` (r-x, 0x315d8 bytes) — code
  - `SysLibArmRom` (r-x, 0x100 bytes) — syscall/rom stubs
  - `REX_CORE_RW` (rw-, 0x8bb0 bytes) — initialised data
  - `REX_CORE_ZI` (rw-, NOBITS) — zero-initialised data
  - `AMSS_HEAP_SEG` (rw-, NOBITS, 2 MB) — heap
  - `PAGE_TABLE` (rw-, 0x44000 bytes) — page tables
  - `.debug_info`, `.debug_str`, `.debug_line`, `.debug_loc`,
    `.debug_frame`, `.debug_pubnames`, `.debug_pubtypes` — full DWARF

### 2.2 Source-tree (from `.strtab`)

Paths in the symbol table reference `Z:\b\fw_core\HLD\...`. The
following top-level directories are referenced (samples):

- `Z:\b\fw_core\HLD\IPE\FrameDataCollator\src\` — IPE frame data collator
- `Z:\b\fw_core\HLD\IPE\...` — Image Processing Engine
- `Z:\b\fw_core\HLD\BPS\...` — Bayer Processing Segment
- `Z:\b\fw_core\HLD\ICP\...` — Image Control Processor
- `Z:\b\fw_core\HLD\CPAS\...` — Camera Platform Abstraction Layer
- `Z:\b\fw_core\HLD\Sensor\...` — sensor drivers
- `Z:\b\fw_core\HLD\CDSP\...` — Camera DSP
- `Z:\b\fw_core\utils\...` — utility code

Top-level blocks the firmware supports (the strings `CAMERA_ICP_DEVICE_*`):

| Token | Block | Notes |
|---|---|---|
| `CAMERA_ICP_DEVICE_A5` | ICP HW id A5 | Titan 170 v2 / Spectra 390 |
| `CAMERA_ICP_DEVICE_BPS` | Bayer Processing Segment | |
| `CAMERA_ICP_DEVICE_CDM` | Command DM (Data Mover) | |
| `CAMERA_ICP_DEVICE_IPE` | Image Processing Engine | |
| `CAMERA_ICP_DEVICE_CPE` | (not seen in this binary) | present on newer Spectra |

### 2.3 IPC and error surface

Error codes (`CAMERAICP_E*`):

```
CAMERAICP_SUCCESS
CAMERAICP_EFAILED
CAMERAICP_EUNSUPPORTED
CAMERAICP_EBADPARM
CAMERAICP_EHWVIOLATION
CAMERAICP_EABORTED
CAMERAICP_ENOMEMORY
CAMERAICP_ECDMERROR
CAMERAICP_ETIMEDOUT
```

ICP domain commands (function names):

```
ICPDomainCreate
ICPDomainCmdHandler
ICPDomainDestroy
ICPDomainResumeWarmBoot
ICPDoaminPrepPC   ← sic, "Doamin" misspelled in QC source
```

Host-interface functions:

```
ICPHostInterface_init
ICPHostInterface_destroy
ICPHostInterface_driverTask
ICPHostInterface_interrupt_service
ICPHostInterface_postMessage
ICPHostInterface_postHFIEventNotify
ICPHostInterface_raiseHostIRQ
```

ICP-HAL functions (the layer the Linux driver will speak to):

```
ICPHalInitSfrBuffer
ICPHalGetDeviceVersion
ICPHalGetQueueTableProps
ICPHalGetSharedmemProps
ICPHalGetUncachedmemProps
ICPHalSetAPIVersion
ICPHalSetHFIVersion
ICPHalSetInitRequest
ICPHalSetInitResponse
ICPHalProgramInterruptEnableToHost
ICPHalTriggerInterruptToHost
ICPHalPollForHost
ICPHalFreezeWd
ICPHalDisableFreezeWd
```

Lifecycle / state machine:

```
ICPInit
ICPIdleTask
ICP_DRIVER_UNINITED
ICP_DRIVER_INITED
ICP_DRIVER_DESTROY
ICPDriverState_t
ICPDestroy
ICPVTable
ICP:SYS_INIT command
ICP SS WD Timeout   ← watchdog timeout string
```

### 2.4 CPAS interface

`CPAS_TOP_CPAS_0_HW_VERSION` and `CPAS_TOP_CPAS_0_TITAN_VERSION` are
the read-back registers a Linux driver uses to confirm chip variant
at probe time. `CPAS_CDM` / `cpas_cdm_seqid` are the Camera Platform
Abstraction Layer CDM (Command/Data Mover) hooks.

### 2.5 Framework / runtime

- `rcinit_*` — RC Framework init
- `rcevt_*` — RC event
- `rcecb_*` — RC event callback
- `DALSYS_*` — Device Abstraction Layer (DAL) system
- `DAL_*` — DAL core
- `HAL_dog*` — hardware watchdog
- `err_fatal_*` — QC error-handling subsystem (with the famous
  `err_emergency_error_recovery` / `err_fatal_jettison_core` /
  `rex_jettison_core` sequence that the Linux driver should never
  observe in normal operation)
- Musl libc (`src/stdio`, `src/errno`, `src/string`, …) statically
  linked for stdio / string helpers

### 2.6 What the Linux CAMSS port needs from this binary

- **Version handshake** — call `ICPHalGetDeviceVersion` /
  `CPAS_TOP_CPAS_0_TITAN_VERSION` and assert `Titan 170 v2`.
- **API/header handshake** — `ICPHalSetAPIVersion`,
  `ICPHalSetHFIVersion` to negotiate the protocol version the
  firmware expects.
- **Init sequence** — `ICP_INIT → ICPDomainCreate → ICPHalSetInitRequest
  → ICPHalTriggerInterruptToHost → ICPHostInterface_init → ...`
- **Per-frame command submission** — `ICPDomainCmdHandler` over a
  shared queue (`ICPHalGetQueueTableProps` /
  `ICPHalGetSharedmemProps`).
- **Watchdog** — `ICPHalFreezeWd` during config / unfreeze on stream
  start. `ICPHalDisableFreezeWd` on teardown. The `ICP SS WD Timeout`
  error string is the watchdog trip wire to surface to the user.

The exact shared-memory layout, the command descriptor format, the
response queue, and the interrupt-cause encoding must be re-derived
from this binary — none of it is public.

## 3. QTI Chromatix tuning blob format

All seven blobs start with the same 20-byte header:

```
00..0f  ASCII "QTI Chromatix Header" + NUL pad
10..13  uint32_le  data_size  (size of the chromatix payload, excluding header)
14..   data_size bytes of payload
```

Sizes observed:

| File | header 0x10 size (decoded) | Total file |
|---|---|---|
| `sensormodule.aux_ov7251.bin`  |  52,328 |  52,344 |
| `sensormodule.ffc_ov5693.bin`  |  91,112 |  91,128 |
| `sensormodule.rfc_ov13858.bin` | 278,408 | 278,424 |
| `tuned.aux_ov7251.bin`         | 375,672 | 375,688 |
| `tuned.ffc_ov5693.bin`         | 829,616 | 829,632 |
| `tuned.rfc_ov13858.bin`        | 1,963,432 | 1,963,448 |
| `tuned.default.bin`            | 8,271,184 | 8,271,216 |

Payload is an opaque, length-prefixed tag-stream. Tokens visible in
`strings(1)` output across the three tuning blobs:

- `AECParamExtension` — auto-exposure extended parameters
- `AWBExtensionParam` — auto-white-balance extension
- `aecDepth` / `aecMultiCamSync` / `aecSkipCtrl` — AEC (auto-exposure)
- `awbSceneChangeConvergeV1` — AWB
- `abf34_ife` / `abf40_bps` / `bpcbcc50_ife` — denoise / bad-pixel /
  lens-shading tuning pinned to specific IFE / BPS modules
- `QTI Chromatix Header` — repeated at the head of every sub-section

The format is the same proprietary blob that ships in the upstream
QC `techpack/camera` driver (`msm_camera_chromatix.*`). It is not
documented and not parseable without either the QC source tree or a
heavily-informed RE effort. For the purposes of the Linux port, the
right approach is to ship the blobs verbatim and have a `request_firmware`
consumer that hands the bytes to a parser (the parser is the
hardest piece of the port — *not* something this document solves).

## 4. Linux CAMSS port — what the dump buys us, what it doesn't

What we have and **don't** need to RE:

- The sensor drivers (`drivers/media/i2c/ov13858.c`, `ov5693.c`,
  `ov7251.c`) are mainline and reusable as-is — only DT binding work.
- The camcc clock controller (`drivers/clk/qcom/camcc-sc8180x.c`) is
  mainline and exposes every clock/reset the cameras need.
- The blobs are usable verbatim: copy them under
  `/lib/firmware/qcom/surface/` (helper: `scripts/extract-surface-camera-fw.sh`).
- The hex addresses of the CSIPHY/CSID/VFE/IPE register regions are
  *probably* recoverable from the `qccamisp8180.sys` PE binary by
  following the ACPI `_CRS` packet at the start of the driver's
  `DriverEntry` path — but this needs a Windows-side tool to dump.

What we still need to RE (the actual port work):

1. **CSIPHY register layout for SC8180X** (3-phase, 1.0 HW).
   The closest upstream is `camss-csiphy-3ph-1-0.c` (used by
   sc8280xp, sm8550). May work as-is — needs an experiment.
2. **CSID register layout for SC8180X.** `camss-csid-gen2.c` or
   `camss-csid-680.c` are candidates. Unknown without reading
   `qccamisp8180.sys` to see which generation it programs.
3. **VFE vs IFE.** The SC8180X has the *newer* IFE (Image Front End)
   block, not the older VFE. Upstream Linux CAMSS only has the
   older VFE drivers (`camss-vfe-4-1` … `camss-vfe-680`) plus a
   thin gen3 wrapper. There is **no IFE driver upstream** — this is
   the central gap.
4. **ICP firmware load protocol.** The exact mailbox register,
   shared-memory carve-out, and boot sequence. The `.inf` says
   `qccamisp8180.inf` installs the device; the `.sys` is the
   actual loader.
5. **BPS / IPE / CDM programming.** Even with the ICP firmware
   loaded, the host CPU still has to configure frame descriptors,
   the output pixel format, and the IFE pipeline taps. The QC
   driver uses roughly 30 IOCTLs to drive a single capture; each
   corresponds to a `cam_icp_*` / `cam_ipe_*` / `cam_bps_*` call.
6. **Sensor → CSIPHY → CSID → IFE lane map and clock tree.** This
   is in the ACPI `_DSD` for each `QCOM04XX` device. Without an
   ACPI dump from Windows we have to guess from the upstream
   `ov*.c` link-frequency defaults and the camcc `mclk{0..7}_clk`
   counts. The guesses are good enough to bind; the question is
   whether they produce clean images.

### 4.1 Closest upstream SoC: sc8280xp

The sc8280xp port (`drivers/media/platform/qcom/camss/camss.c` —
the `sc8280xp_resources` struct at line 4414, the DT node at
`arch/arm64/boot/dts/qcom/sc8280xp.dtsi:4332`) is the right
structural template. Differences expected:

| Item | sc8280xp | sc8180x (expected) |
|---|---|---|
| VFE/IFE | VFE only | VFE + IFE + IFE-Lite (mixed) |
| CSID gen | gen2 | gen2 (likely) or gen3 |
| CSIPHY | 3-phase 1.0 | 3-phase 1.0 (likely identical) |
| ICP firmware | not used in upstream | required (Titan 170 v2) |
| `camss_subdev_resources` | 4 CSIPHY + 4 CSID + 4 VFE + 4 VFE-Lite | 3 or 4 CSIPHY + 3 or 4 CSID + VFE/IFE mix |

### 4.2 ACPI dump path (requires Windows reboot)

To get the per-sensor topology (PhyId, CSID slice, virtual channel,
I2C address, CCI index, MCLK, reset GPIO, regulator paths), boot
into Windows and run (as Administrator):

```cmd
acpidump -b
move /y acpidump_*.dat C:\dump\
```

Then decompile on Linux with `iasl -d ssdt*.dat` and grep for the
`QCOM04XX` device scopes. The per-sensor `_CRS` and `_DSD` packages
hold the topology.

We **cannot** do this step from a Linux boot because this tree
boots with DT-only and does not expose `/sys/firmware/acpi/tables/`.

## 5. Filesystem layout (after running the helper)

After `scripts/extract-surface-camera-fw.sh`:

```
/lib/firmware/qcom/surface/
├── CAMERA_ICP_AAAAAA.elf          # 3.6 MB  ARM32 ICP firmware
├── sensormodule.aux_ov7251.bin    # 52 KB   IR sensor module data
├── sensormodule.ffc_ov5693.bin    # 91 KB   front sensor module data
├── sensormodule.rfc_ov13858.bin   # 278 KB  rear sensor module data
├── tuned.aux_ov7251.bin           # 376 KB  IR per-unit tuning
├── tuned.default.bin              # 8.3 MB  default QTI tuning
├── tuned.ffc_ov5693.bin           # 830 KB  front per-unit tuning
└── tuned.rfc_ov13858.bin          # 2.0 MB  rear per-unit tuning
```

## 6. Open questions for a future driver port

1. **IPE-Lite vs IPE.** Is the IPE-Lite block present in TITAN 170 v2,
   and if so, is it used for the OV7251 IR stream (smaller, lower
   latency)? The `CAMERA_ICP_DEVICE_IPE` token is present but
   `IPE_LITE` is not seen — likely same block, different config.
2. **UBWC format version.** The `IsUbwcCmdFormat` symbol exists;
   which UBWC version does the firmware negotiate? TITAN 170 v2 is
   expected to use UBWC 2.0 or 3.0.
3. **Jpeg-E device.** `QCOM0436` / `qccamjpege8180.inf` exists;
   does the upstream V4L2 path need to add a JPEG codec, or is JPEG
   done in firmware?
4. **Per-frame interrupt budget.** `ICPIdleTask` is referenced; the
   firmware does some work in the idle task. Linux CAMSS currently
   uses a tasklet — that may need to be threaded.
5. **Production routing for OV7251.** The IR sensor is proven on PHY3 and
   captures through the full CSID0 -> VFE0 RDI0 path.  It remains open whether
   a production stack should instead reserve a CSID-Lite/VFE-Lite slice for it.

## 7. Status of this repository

As of 2026-08-09, all three Surface Pro X raw camera paths work end to end:

- The Surface Windows SMMU configuration identifies VFE context bank 21
  (`S1_CAMERA_HLOS`) as SID `0x0a00`, mask `0x04e0`.  The validated v22
  camera tree carries that exact `iommus` tuple.
- The CSID incrementing generator produced two 2592x1944 packed RAW10
  frames at IOVAs `0xff800000` and `0xff000000`.  This proved the
  CSID -> VFE -> SMMU -> RAM path and corrected the earlier false result
  from untouched, pre-zeroed buffers.
- Exact bounded ID probes established the remaining Windows topology without
  sweeping unsafe CCI buses: rear OV13858 at CCI0 bus 0 address `0x10`, MCLK0,
  reset GPIO22, PHY2; IR OV7251 at address `0x60`, MCLK3, enable GPIO23, PHY3.
- The v23 graph binds front/rear/IR as `4-0036`, `3-0010`, and `3-0060`, with
  immutable links to PHY0/PHY2/PHY3 respectively.
- With every sensor test pattern disabled, the OV5693 produced two
  2592x1944 `pBAA` frames, the OV13858 two 2112x1568 `pgAA` frames, and the
  OV7251 two 640x480 `Y10P` frames.  STREAMON, DMA completion, and STREAMOFF
  succeeded for each sensor.  All three decoded previews show real scenes.
- The three raw captures, previews, capture logs, and checksums are archived
  under `/var/log/spx-camera-archive/v23-multi-20260809/` on the test machine.
- `scripts/spx-camera-stream.sh` supports `SPX_CAMERA_SOURCE=csid-testgen`,
  `sensor-bars`, and `sensor-real`, plus `SPX_CAMERA_SENSOR=front|rear|ir`.
  `scripts/spx-raw10-to-pgm.py` converts any of the packed RAW10 buffers into
  a contrast-stretched grayscale preview when given the captured dimensions
  and stride.
- `spx-camera-probe.service` is deliberately disabled and has no automatic
  reboot actions.  The previous automatic systemd shutdown wedged after a
  successful capture; manual camera runs now remain online for inspection.

Still open: describe the working combined DT as normal board source rather
than the historical decompiled v23 artifact, integrate the direct PMIC rail
sequence with a proper regulator/power-domain driver, and expose a
user-friendly debayered/processed stream.
