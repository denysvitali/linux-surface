# SQ2 video startup contracts, 2026-10-03

D03 remains **missing integration / untested on hardware**. The retained SQ2
miniport constructs a `SYS_INIT` packet with architecture value **2**; current
Linux Venus sends **1**. Native checks confirm that Linux's existing packet
builder can construct the byte-identical value-2 packet. This is a concrete
candidate requirement for a dedicated SQ2 resource/transport change. Firmware
acceptance of either value, the remaining packet ABI and accelerated media remain
unobserved. Latest actual mainline result is still [terminal AX](../RESULT-20261003ax.md).
No kernel, DT or configuration changed, and no trial was selected.

The subsequent [Iris1 IRQ candidate](../video-iris1-20261003/README.md) changes
two Venus source files and passes native/private aggregate-object validation.
It traces UC reserve-at/page backing and records the ASL/table discrepancy.
That later source work does not alter this sealed constructor evidence; no
enabled SC8180X resource or hardware codec result exists yet.

## Pinned device instructions

The original 2020 `qcdxkm8180.sys` is
`049da069400c124746e2f6ef0bd5851c603d865b3c1867e0c47c74e27c46220b`.
The [auditor](audit_startup.py) verifies ten original ARM64 exception-bounded
ranges and45 instruction contracts. Full selected linear disassembly is retained;
it is not a full control-flow graph, complete call graph or Windows startup run.
No 2022 miniport selection is inferred from this original image.

`VedStartEngine` reads the wrapper hardware-version register at video offset
`0xe0000`, retains the low16 bits separately, and clears them before dispatch.
`vedInitPlatformConfigs V1` has an explicit normalized `0x50100000` branch,
labelled `Venus510` by its debug string. That branch selects the `0x1abd40`
callback table whose entries refer to `HfiVenus5XHT` routines, and sets the initial
interrupt-mask field to `0x1f6`. `VedInitVideoCore` writes the field to wrapper
offset`0xe0010`. This proves the branch/table contract; **the device's live
hardware-version value has not been read**. Subsequent masking, separate watchdog
IRQ handling and the corresponding Linux policy still need reconciliation.
The related Android SM8150 sequence clears watchdog bit4/CPU bit2 in a preserved
mask; current Linux's legacy sequence writes8. These cannot be treated as the
same initial policy simply because their register addresses agree.

`VedInitVideoCore` calls `VedHfiSysInit` at RVA`0x3597bc`. Its original builder
at`0x355a3c..0x355a58` writes these three little-endian words:

| Field | SQ2 miniport | Current Linux call | Linux builder with argument2 |
| --- | --- | --- | --- |
| Packet size | 12 | 12 | 12 |
| Command | `0x10001` | `0x10001` | `0x10001` |
| Architecture | **2** | **1** | **2** |

The legacy queue table has a24-byte header followed by three56-byte queue headers,
192 bytes total. Types are`0x01010000 | index`. The miniport's queue-size factor
is shifted14 bits to bytes, then divided by4 for queue words. Current Linux's
819200-byte queues correspond to factor50. Both leave `pkt_drop_cnt` unchanged
inside the examined builders, so allocation initialization matters. Windows
initializes debug `rx_req=1`; Linux deliberately sets it to0 to suppress debug
interrupts. That difference does not invalidate the shared layout.

The selected `VedHfiReset` paths use CPU-CS base`0xd2000` and offsets:

| Offset | Retained operation |
| --- | --- |
| `0x54 / 0x50` | Queue-table IOVA / queue-present1 |
| `0x5c / 0x60` | SFR / optional memory-map IOVA |
| `0x64` | Sum of two engine-SMMU description words at`+0x24/+0x28`, minus16MiB |
| `0x68` | UC region size16MiB |
| `0x48 / 0x4c` | Initialize control / poll status |

In particular, the retained UC base calculation is **not a direct write of the
queue-table IOVA**. The two description words and their runtime allocation
relationship remain to be traced. Linux currently declares its shared region
from the queue-table IOVA with a computed3MiB size. The Windows16MiB UC window
is distinct from the five-MiB firmware load span. No RAM carveout is derived
from these virtual-address calculations, and no required allocation size is
silently substituted into Linux.

`VedPilLoadAndReset` calls the retained PIL load routine and then sends
IOCTL`0x9c412410`, named `IOCTL_PIL_TZ_AUTH_IMAGE_AND_RESET` in its failure
message. The request's buffer contains4. This supports an authenticated firmware
startup path, but does not establish Linux PAS9 compatibility, secure memory
ownership or successful loading of any installed image.

## Retained SMMU stream groups

The original `qcsmmu8180.inf` is
`1e9e06a07882260542c51dbe6d1f9bf9a4f1becd91406cacf1977266d9676379`,
DriverVer03/20/2020,1.0.1040.0000. Both revision1/revision2 dynamic sections
declare the same four video groups. `qcsmmu8180.sys` and `SMMC.bin` are copied
and hash-checked too; neither was executed.

| INF VM/context-bank labels | Candidate SID/mask from literal bytes | Covered retained IORT SIDs |
| --- | --- | --- |
| VM4 / CB10 `S1_VIDEO_HLOS` | `0x2300 / 0x60` | `2300,2320,2340` |
| VM16 / CB11 `S1_VIDEO_CP_P` | `0x2303 / 0x20` | `2303,2323` |
| VM8 / CB12 `S1_VIDEO_CP_B` | `0x2301 / 0x04` | `2301,2305` |
| VM64 / CB13 `S1_VIDEO_INT` | `0x2304 / 0x60` | `2304,2324,2344` |

The interpretation of each five-byte literal agrees with all ten retained video
IORT output mappings and the INF's own stream/mask comments. Mask`0x60` also
matches fourth aliases`2360`/`2364`, absent from those three-entry IORT groups.
This narrows the nonsecure Linux DT candidate to `<0x2300 0x60>` using
device-specific evidence. It does not establish live security/context-bank
assignment or the unexplained fifth `VideoSecurePT4` relationship.

The examined miniport interface requests ARID information for client4, then copies
returned24-byte records into72-byte engine records by context type. It also copies
CBID information. **Input-ID packing is delegated beyond these copy routines and
has not been proved.** The IORT inputs`0403xxxx` are not interpreted as literal
CB10 IDs or a Linux SID encoding. INF labels describe the retained configuration;
they are not observations of the current Linux SMMU.

## Independent native check

The [reviewer](verify_startup.py) rehashes the inventory, re-decodes all ten ranges
and45 contracts, rejects three changed queue-size/architecture/wrong-SoC-SID
fixtures, and compiles three **verbatim Linux C bodies**:
`venus_set_qhdr_defaults`, `venus_interface_queues_init`, `pkt_sys_init`.

On this ARM64 host, two call-free original instruction fragments run inside
explicit AAPCS wrappers with synthetic context/table/packet RAM. No Windows
service, miniport startup, SMMU, codec register or firmware operation runs.
Six queue cases exercise factors1/32/50 with zero and poison initialization.
Both factor50 cases agree with every Linux table word except the intentional
debug `rx_req` policy. SYS_INIT's value-2 packet matches Linux's builder with
argument2 byte for byte. ASan/UBSan cover the C scaffolding and Linux bodies;
the original assembly has explicit table/packet sentinel checks and is not
sanitizer-instrumented. This is a bounded constructor check, not full firmware
ABI or hardware acceptance.

The first audit stopped at an incorrectly transcribed source register in an
instruction assertion. Its original partial files/stderr remain preserved.
The first review stopped before compilation because the copied auditor derived
the repository from a path with too few parents; the corrected auditor can be
imported from sealed evidence. Intermediate successful versions are also kept.
No failed native result is relabelled as a pass.

## Next integration work and evidence

Reconcile the remaining Iris1 wrapper interrupts, UC allocation policy and
MMCX/GDSC/GCC AXI/reset transitions. Resolve the authenticated five-MiB firmware
reservation independently of UC virtual addresses. Then prepare a dedicated
SC8180X Venus binding/resource/DT/config candidate with the demonstrated
architecture-value contract and candidate nonsecure stream group. Build/archive
the complete candidate and select a fresh trial once. First hardware checks must
record firmware/HFI startup and advertised formats before actual decoded-output,
encoding, sustained playback, idle/resume and combined regressions. D03 stays open.

- `/var/tmp/spx-video-startup-20261003-v4`:20 files, manifest
  `9196bea5634ff8df0491ba656e525f15cedc03f64acdea4f6f9ea81a3d0d023a`.
- `/var/tmp/spx-video-startup-review-20261003-v3`:15 files, manifest
  `4941bc70e310486fcbecf52a072036f3c5fd3f5c4b38a3d6314990e291facbde`.
- Durable AX `offline-video-startup-20261003` retains these inputs/review,
  intermediate and failed work, discovery indexes and disassemblies. Its sealed
  state records fresh actual boot/recovery/source checks and no pending selection.
  All151 files verify; manifest
  `fefc722d86a44b86c59b02826d182b22b5355569704eac98fe6ebdb13c2b216a`.
  Prior98 video files, AX518 preparation/499 build/208 installed files,
  34 helpers/three payloads, all5183 known-good records and nine corrected-clock/
  power-audit sources verify unchanged on actual known-good boot
  `b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release`6.18.3-1-surface+`.
  The sealed archive carries the pre-seal README; the reconciled records are
  frozen separately in AX `post-video-startup-records`.

The preceding [device-resource/firmware inventory](../video-integration-20261003/README.md)
remains unchanged. All47 feature acceptance boxes remain open. Automatic recovery
across EFI/early-kernel hangs remains unvalidated.
