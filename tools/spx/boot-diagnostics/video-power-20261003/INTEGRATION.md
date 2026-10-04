# SC8180X Iris1 integration candidate, 2026-10-03

Latest actual startup is now [BA](../RESULT-20261004ba.md): corrected ICC tags
pass full actual provider parsing, and Venus reaches normal firmware loading.
It fails-22 at qcom_pas_mem_setup with early5MiB reservationfe500000..fe9fffff.
PAS initialization's zero return is inferred from exact compiled control flow;
authentication/reset/HFI/media remain unvalidated. The180s media gate skips.
SCM result origin is unresolved; this running config disables event tracing.
Pinned retained Surface PIL declaration reserves5MiB with alignment0 and no
fixed address, which does not prove secure-service acceptance of the Linux
reservation. Both prior malformed AZ source/tree artifacts remain unchanged.

Latest actual startup is [AZ](../RESULT-20261003az.md): VIDEOCC now binds,
but Venus probe fails before PAS/HFI because all four interconnect endpoint
tuples omit the tag required by `#interconnect-cells = <2>`. The original
fixed-stride offline verifier asserted the malformed list; its archived pass
does not establish this provider contract. Actual provider phandles resolve
correctly, but Linux's arity-based parsing consumes the next phandle as a tag
and then encounters GIC phandle1. Preserve original checks/evidence and validate
provider-declared argument widths on both source and actual boot DT before the
next fresh candidate. The media gate skipped. The620.52s inherited baseline passes; guarded900.50s
return reaches independently verified known-good19cfd105, with shutdown logs
through913.658393s and exact frozen baseline replay. AZ is terminal. All47
acceptance boxes stay open.

The fresh BA correction adds a zero tag at each of the four ICC endpoints;
the Qualcomm aggregation code maps an unspecified zero tag to its normal
always-vote policy. [video_dt_contract.py](video_dt_contract.py) now walks
references using provider-declared argument counts and verifies exact physical
providers/arguments for ICC, clocks, resets, power domains, IOMMU, memory and
OPPs. Seven malformed ICC fixtures reject, including the original missing-tag
list; the full source verifier retains four binding and three native controls.
Fresh source-v2 has66 files, manifest
`97f0deb7392b8289fc07c619e3055a298a84abbb8ea0c9d5d3e342534c32d6b5`.
The actual retained boot DT must pass this same contract before deployment;
the old source-only/fixed-stride check is superseded for fresh candidates.

D03 is **candidate implemented / media hardware untested**. The historical
boot remains [terminal AX](../RESULT-20261003ax.md). AY is a fresh private source
and build candidate; no new firmware boot, format query or media operation is
established by these offline results. All47 hardware acceptance boxes stay open.

The dedicated `qcom,sc8180x-venus` resource selects HFI4xx and Iris1, the prior
all-domain power and IRQ paths, and SYS_INIT architecture2 for the retained
SQ2 firmware ABI. Other existing resource records leave the new policy field
zero, preserving architecture1. MVS1 remains powered for firmware startup but
is CVP, so the scheduler exposes one video codec core. Dynamic decoder/encoder
children use the existing normal Venus drivers.

The SoC node describes seven audited clocks, MVSC/MVS0/MVS1 domains plus MMCX,
the paired GCC AXIC/VIDEOCC MVSC bridge resets and the video-P0/CPU-config
interconnect paths. Its six OPP rates match retained SQ2 PMCL and the Linux
VIDEOCC plan. The required corner values match the pinned PEP plan's revision2
branch. The initial200MHz OPP votes64 rather than the plan's48, retaining the
G4MD startup's minimum64; this conservative choice and all rate transitions
still require actual hardware/power validation. The initial DDR vote is the
retained G4MD200MB/s. Runtime media bandwidth currently borrows the SDM845 HFI4xx
table as a provisional candidate. SQ2 calibration, adequate bandwidth across
formats/concurrency and idle/power behavior remain required work.

The MMIO window is the nonoverlapping lower one MiB of the retained two-MiB
ACPI range, covering Venus registers while leaving VIDEOCC's independently
owned range intact. SPI174 carries the ordinary HFI interrupt. The fitted
separate watchdog SPI175 is still unrouted; the in-band watchdog bit handling
does not prove independent watchdog delivery or recovery.

The board enables this consumer with the retained nonsecure SID2300/mask60
candidate. The DMA mask excludes the retained secure IOVA ranges at/above
c0000000. Neither proves actual SMMU context-bank assignments, firmware UC
mapping or secure policy. The board requests the installed00042 firmware via
the normal PAS9/MDT path. No secure context, guessed content-protection range
or forced non-TZ loader is introduced. Actual PAS authentication/reset and
the generic three-MiB HFI queue/UC allocation remain unvalidated.

Firmware memory is a dynamic five-MiB `no-map` reservation aligned one MiB in
actual free early RAM below4GiB. All static/UEFI reservations must remain
excluded by memblock. The firmware relocation checks previously passed exact
bytes/zero-fill at three synthetic destinations for all three retained images;
they did not authenticate or allocate physical memory on this device.

Probe failures after successful Iris1 power-up quiesce the IRQ and release
power/bandwidth votes. Iris1 runtime-resume failures unwind successful earlier
steps. Original firmware load/boot error codes are preserved and logged. Failed
leaf shutdown/domain-put operations remain potential cleanup limits, recorded
by the prior power tests; the new native tests mock those leaf calls.

[verify_integration.py](verify_integration.py) validates the exact compiled
consumer and all providers/OPPs/reservation references, the dedicated binding
meta-schema, four invalid DT fixtures and three actual Linux C bodies. Under
ASan/UBSan,10 resume cases,12 SYS_INIT cases and16 firmware cases pass. Three
changed candidates lose the architecture policy, resume unwind or firmware
errno and all abort on the independent checks. This is38 offline cases,
not a firmware or media acceptance result. Final v5 has51 files, manifest
`9a666dd668abe162c2cb30dd9e33d39afb9082203560330d1e230e42212f62e8`.
Earlier v1 failed on unavailable Python-libfdt `subnodes`; v2 failed because a
mock warning macro did not consume `dev`. Their source/logs stay preserved.
v3/v4 positives and the original rejected DT comparison are also retained.

[prepare_dtb.py](prepare_dtb.py) extracts the added nodes from frozen AY source
and combines them with AX's reviewed camera/privacy DTS. Every existing property
value and memory-reservation entry remains exact; only nine new nodes and new
`phandle` properties on VIDEOCC/the turbo OPP are permitted. Existing rear
status, rails, privacy LED, reset, pinctrl and touch timing remain exact.
The initial stricter comparison rejected those two necessary new references;
its tree/log/diff is preserved, then the explicit scoped comparison passes.

[build-ay.py](../build-ay.py) verifies the96937-record frozen base, applies
exactly13 source changes (including the two prior camera clocks), seals a
96938-record source archive and checks each streamed tar member. It builds
a distinct AY Image, board DTB and201 modules with seven media config additions
plus the release change. RTC settings stay exact. The original AX output,
known-good files and live kernel configuration are preserved.
[assemble-ay.py](../assemble-ay.py) stages the private modules/initramfs and
checks module vermagic, depmod, embedded payloads and the provider DTB.
Build/assembly status and durable artifact receipts must be read before boot.

The full build completes at2026-10-03T19:52:24.910833Z with201 modules. Its
source manifest is`d615df71827c76b05bf1db0619b9660eb8f3d993088486a4d869e8d94a205308`,
stream-verified source archive`ca9735d4ed70e537bd9cb04d0a3331f575bacb88c32fb8f468baa5e2c2750721`,
effective config`75665e3df65b248ad1eb9bc85d0d1900574081bbfb70e2a0bc8cd7583e0c4cd5`,
and Image`52858cae48a259581af830530c08ec5600ddbae9a955c3c5bcd5cba0cca5b674`.
Private assembly verifies216 module-tree files,201 vermagic strings, clean
depmod,54 embedded exact modules and the private initramfs logger.
No installed release, boot payload or selection is changed by these steps.

Subsequent actual deployment installs only the sealed AY release/payloads and
fresh startup helpers. The build archive contains794 files/272 links and
preparation209 files; independent checks verify84669 live source paths and
all5183 known-good recovery files/links. The prepared selector remains empty
at the last deployment review. Read [AY preparation](../PREPARED-20261003ay.md)
and the eventual actual boot record before drawing hardware conclusions.

Code and binding patches pass separate strict checkpatch checks with0 errors,
warnings or checks. The initial combined review retained the expected binding
split warning and missing optional Python `ply`; final `--no-tree` checks do
not claim SPDX-parser validation. Binding meta-schema and SPDX identifiers
were separately reviewed. Existing base DTC warnings remain preserved, so
these focused checks do not establish a clean full-board schema.

AY has subsequently booted once. Its actual startup is blocked before Venus
probe by unbound VIDEOCC: CONFIG_SM_VIDEOCC_8150 is disabled in the frozen
configuration, although the DT's SM8150 fallback matches that existing provider.
Early five-MiB physical reservation is observed atfe500000..fe9fffff. No PAS/HFI
or video formats result follows. The620.17s inherited scoped baseline passes
independent311-file review/taint0; guarded900.67s return reaches independently
verified known-good57b50440. Complete shutdown logs reach909.571263s and frozen
baseline replay is exact. Read [actual AY result](../RESULT-20261003ay.md) and
never re-arm AY. A fresh candidate must enable and verify the clock supplier
before testing PAS/HFI/firmware version, formats and resource/idle/error state.
Real decoded output, encoding, sustained media, suspend/resume and one final
combined regression candidate remain required.
