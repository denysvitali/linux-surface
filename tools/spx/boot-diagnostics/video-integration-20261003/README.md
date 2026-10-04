# SQ2 video integration inventory, 2026-10-03

D03 is **missing integration / untested**. This investigation identifies a
fitted video engine and concrete driver/configuration gaps; it does not establish
supported codec formats, secure firmware authentication, decoded output, encoding
or sustained playback. The latest actual mainline result remains
[terminal AX](../RESULT-20261003ax.md). No new kernel was built, installed or queued.

The subsequent [native startup audit](../video-startup-20261003/README.md)
confirms the queue subset, exposes SYS_INIT architecture2 versus current Linux1,
and narrows nonsecure SID2300/mask60 from the retained SQ2 SMMU INF. That later
evidence supplements this sealed inventory; interrupt/UC/power/secure loading
and real-media acceptance remain open. The subsequent
[Iris1 IRQ source candidate](../video-iris1-20261003/README.md) adds a bounded
interrupt path and private aggregate-object build, with no enabled codec resource
or hardware media result.

The guarded read-only inventory ran on actual known-good boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release `6.18.3-1-surface+`, at
13934.66–13935.40s uptime. No `/dev/video*`, `/dev/media*`, video/media class
entries or codec platform device exists in that snapshot. Its effective config
contains `VIDEO_QCOM_VENUS=m`, `V4L_MEM2MEM_DRIVERS=y` and
`V4L2_MEM2MEM_DEV=m`; the frozen AX config disables `V4L_MEM2MEM_DRIVERS` and
has neither effective Venus nor mem2mem support. FFmpeg's compiled codec list is
userspace inventory only. No codec node was opened, firmware loaded or media run.

## Retained device resources

Pinned SQ2 DSDT `e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8`
places a `Venus` engine, ID4, within `GPU0`. Both `GPU0._CRS` alternatives
declare video MMIO at `0x0aa00000`, size `0x200000`, with level/high GSIs206/207
named `VIDC_INTERRUPT` / `VIDC_WD_INTERRUPT` by both RESI alternatives. Subtracting
the GIC SPI base32 gives174/175; the driver still needs a deliberate policy for
the separate watchdog interrupt. The static ENGS property `DecMaxFps=60` is a
declared setting, not a measured capability or exhaustive format limit.

The literal ENGS, PMCL and G4MD trees contain148,1110 and1487 packages whose
declared counts all verify. Full ordered values are preserved in `inventory.json`,
including the five `VideoNonSecurePT` / `VideoSecurePT1..4` page-table records.
The nonsecure record declares a virtual range starting `0x00100000`, length
`0xbff00000`; four secure ranges start at `0xc0000000..0xf0000000`, length
`0x10000000` each. Field meanings beyond the visible names/values and driver
input-ID construction require explicit tracing before translating them to DT.

The retained IORT's GPU0 component has51 mappings. Ten input IDs with engine
prefix4 route to the SMMU node at table offset `0x30`, whose base is
`0x15000000`:

| Input ID(s) | Output SID(s) |
| --- | --- |
| `04030000 / 04030001 / 04030002` | `2300 / 2320 / 2340` |
| `04090000 / 04090001` | `2301 / 2305` |
| `040a0000 / 040a0001` | `2303 / 2323` |
| `040b0000 / 040b0001 / 040b0002` | `2304 / 2324 / 2344` |

Each has ID Count0 and flags0. These are exact retained mappings. The inference
that the first group belongs to the named nonsecure page table is plausible from
the engine prefix and security grouping, but input-ID packing has not been
verified in the SQ2 miniport. **No Linux SID mask or context-bank policy is
accepted from this inventory.** The SM8150 reference's `0x1300`/mask`0x60`
cannot be copied unchanged onto the SQ2.

G4MD's component4 contains FSTATE0 with no actions, FSTATE1 with18 ENTER/24 EXIT
actions and FSTATE2 with21 ENTER/31 EXIT actions. Both EXIT lists begin with
MMCX request64, then XO/AHB clocks and software enable of `mvsc_gdsc`,
`mvs0_gdsc`, `mvs1_gdsc`. They contain raw CLOCK14/15 pairs separated by DELAY1,
all three GCC AXI clocks, Iris/MVSC/MVS0/MVS1 clocks, and raw FOOTSWITCH3 for
MVS0/MVS1. FSTATE2 also contains raw CLOCK9 arguments18/20. Names, order and raw
fields are retained; the untraced CLOCK14/15/9 semantics and DELAY units are not
treated as established Linux sequencing. PMCL declares core rates
533/444/365/338/240/200MHz and0, matching the six non-XO values in current
`videocc-sm8150.c`; live votes, transitions and performance remain unobserved.

## Three firmware images, kept distinct

| Origin | Declared VIDEO.IR.1.2 build | SHA-256 |
| --- | --- | --- |
| Retained 2020 driver package | 00040-PROD-1 | `bb75ac2dfcedf0bb53fb8364e66a82ffeab144168a76ca2110abaf2c0e8e2672` |
| Installed Linux firmware path | 00042-PROD-1 | `4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928` |
| Retained 2022 driver package | 00061-PROD-1 | `c89f95f8443b5ed729493f294e5ea4089c6967ea49fff9c38cf34cc33d8183cc` |

All are ELF32 ARM images with five program headers, three Linux-MDT-loadable
segments and relocatable bit27. The lowest loadable physical address is
`0x0f500000`; the page-aligned end is `0x0fa00000`, a five-MiB span. These link
addresses are not a proposed Linux DRAM carveout. Each retained INF names its
firmware; neither retained package is byte-identical to the installed image.

The [offline reviewer](verify_video.py) compiles the **actual** Linux
`mdt_header_valid`, `mdt_phdr_loadable` and `qcom_mdt_get_size` functions against
native firmware/ELF type scaffolding. All three original images return five MiB
under ASan/UBSan. This checks header/load-span interpretation, not PAS9 secure
authentication, memory ownership or the complete MDT loader. The first native
compile failed on Linux's unsigned-address/negative-error ternary under
`-Werror=sign-compare`. Its original source/stderr are preserved; the successful
review retains that function verbatim and uses the kernel's
`-Wno-sign-compare` convention.

## Driver comparison and next integration boundary

Current Venus has a dormant `VPU_VERSION_IRIS1` enum and legacy register
definitions, but no SM8150/SC8180X OF match/resource record. Current SC8180X DT
has VIDEOCC, GCC AXI clocks and their resets, but no codec consumer or assigned
video firmware carveout. Existing providers alone cannot expose acceleration.

The exact primary reference is
[Android MSM commit28cc5c521b21f92fa6f8a5a6be16960100f70a7a](https://android.googlesource.com/kernel/msm/+/28cc5c521b21f92fa6f8a5a6be16960100f70a7a/arch/arm64/boot/dts/qcom/sm8150-vidc.dtsi),
with eight source files and their URL/byte/hash receipts retained. Its SM8150
resource uses VPU_VERSION_5, while `venus_hfi.c` selects HFI_PACKETIZATION_4XX
and vpu5_ops. Its DT includes three GCC AXI proxy clocks, core/MVS0/MVS1 clocks,
and controller/video/CVP power supplies. Native evaluation of23 common legacy
register/address/mask definitions agrees with current Linux definitions.
This comparison is reference evidence, not proof of the SQ2 HFI packet ABI.
Two initial `hfi_iris1.c` / `hfi_venus.c` fetches returned404; actual filenames
were discovered from the preserved Gitiles directory listing.

The reference also initializes DSP queue/UC mapping registers at CPU-CS
offsets`0x34/0x38/0x3c` and preserves interrupt-mask bits while clearing watchdog
bit4/CPU bit2 for vpu5. Current Linux's legacy `venus_run` / `venus_boot_core`
do not provide that Iris1-specific setup. These are candidate differences to
reconcile against the SQ2 miniport before a scoped driver change; this audit
does not establish that either is the sole missing operation.

Next, trace the SQ2's actual HFI setup and input-ID construction, resolve its
MMCX/GDSC/AXI/reset sequencing and validate a non-overlapping firmware carveout.
Then add the dedicated binding/DT/driver/config candidate, compile and archive
all artifacts, and select a fresh trial once with known-good recovery preserved.
First hardware evidence must include firmware/HFI initialization and advertised
formats; subsequent real-media tests must check output and actual acceleration,
then encoding, sustained use, idle/resume and combined regression. D03 stays open.

## Sealed evidence

- `/var/tmp/spx-video-integration-20261003-v1`:38 files, manifest
  `f7049b043c472599086e33d5c477b90a06606b68cd05d88c3e4bf50a23892c5f`.
- `/var/tmp/spx-video-state-20261003-v1`:25 files, manifest
  `2e43bc44c2c4ad0445d78a63fc2d7e12a049fb75690cd24e3e20bb40c61550e9`.
- `/var/tmp/spx-video-review-20261003-v2`:17 files, manifest
  `f266060aab18509d403beca0f18a1e9c8bbfb775988f143f6c05f8334191848e`.
- Durable AX `offline-video-integration-20261003`:98 files, manifest
  `f03ee85137a75657142a65ee6b4d818394e46a637269d397d10efc5c16118c8e`.
  All original/copy hashes verify, including the first compile failure. Frozen
  AX518 preparation/499 build/208 installed files,34 helpers/three payloads and
  all5183 known-good files/links/payloads/EFI/default verify unchanged. Nine kernel
  sources remain exact against the corrected camera-clock/power audit state;
  next selection is empty and no EFI BootNext is present.

The [offline auditor](audit_video.py), [read-only actual collector](collect_video_state.py)
and reviewer preserve original inputs, full literal trees, raw command output,
native sources/binaries and scope limits. All47 feature acceptance boxes remain
open. Automatic recovery across EFI/early-kernel hangs remains unvalidated.
