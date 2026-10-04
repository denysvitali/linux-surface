# SQ2 Iris1 power and firmware-memory candidate, 2026-10-03

The subsequent [dedicated resource/DT integration](INTEGRATION.md) connects
this power/IRQ source to a fresh AY candidate, adds SYS_INIT2 and a dynamic
firmware reservation, and verifies38 additional native cases plus the binding
and AX-relative boot tree. Its preparation is distinct from the sealed offline
power evidence below; neither establishes hardware video acceptance.

D03 remains **missing board integration / untested on hardware**. The new
Iris1 PM path powers all three video GDSCs before firmware startup, pulses both
bridge resets together, enables all seven clocks, then hands the two MVS domains
to hardware control. On suspend it takes control back before disabling clocks
and domains. MVS1 is the CVP block; session acquisition does not power it as a
second encoder. No OF resource selects Iris1 yet, and no board DT, installed
configuration, firmware load or boot selection changed. Latest actual mainline
result remains [terminal AX](../RESULT-20261003ax.md).

The candidate changes [pm_helpers.c](../../../../drivers/media/platform/qcom/venus/pm_helpers.c),
[pm_helpers.h](../../../../drivers/media/platform/qcom/venus/pm_helpers.h) and
[core.c](../../../../drivers/media/platform/qcom/venus/core.c). Existing PM bodies
and the other-generation HFI-version dispatch remain unchanged. The previous
[IRQ candidate](../video-iris1-20261003/README.md) and camera-clock corrections
are preserved. Failed hardware-mode acquisition on suspend leaves clocks and
votes in place. A failed final OPP-vote drop is logged and may leave a high vote;
it does not pretend the powered-down device is still active.

## Device contracts and sequencing

[audit_power.py](audit_power.py) rechecks the pinned original `qcpep8180.sys`
(`751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde`),
the sealed SQ2 ASL inventory, seven clock branches and three GDSC descriptions.
Retained G4MD component4 F1/F2 exits enable MMCX and MVSC/MVS0/MVS1, issue clock
operations14/15 for AXIC and MVSC, enable the seven branches, then hand MVS0/MVS1
to hardware. Its operation-name table calls14/15 `RESETCLOCK_BRANCH_ASSERT` and
`RESETCLOCK_BRANCH_DEASSERT`; the complete execution dispatcher is not traced.
GCC branch addresses are `0x10b02c/0x10b024/0x10b028`, and VIDEOCC branches are
`0xab008f4/0xab00850/0xab00890/0xab008d0`. GDSCs are
`0xab00814/0xab00874/0xab008b4`, sharing the retained MMCX rail description.

The pinned Qualcomm reference explicitly sets bit2 in both bridge branches,
waits150–250us, clears both and then enables clocks. Linux uses the reset and
clock bulk APIs; bulk reset deassertion releases the pair in reverse order.
Reference: [Qualcomm Venus power sequence at commit28cc5c5](https://android.googlesource.com/kernel/msm/+/28cc5c521b21f92fa6f8a5a6be16960100f70a7a/drivers/media/platform/msm/vidc/venus_hfi.c).
This is an experimental power policy, with hardware behavior still unobserved.
The initial PEP frequency plan includes conditional records and raw corners;
these have not been translated into a validated Linux OPP table. Linux already
has the corresponding branch/reset/GDSC providers.

## Firmware memory

The guarded known-good `/proc/iomem` reserves `0x8b700000..0x9aafffff`, including
the old board comment's “free for image loader” area. Do not turn that comment
into a guessed fixed carveout. The recorded boot is
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release`6.18.3-1-surface+`,
saved default`spx-known-good`, empty next entry/noEFI BootNext. The actual RAM
map, live FDT and memory-related boot messages are retained; no video MMIO occurs.

A future candidate can request an early dynamically allocated `no-map` region
of5MiB, aligned to1MiB and constrained below4GiB. Linux's reserved-memory scan
reserves static regions first, then allocates dynamic regions from free memblock
memory. The current kernel's implementation and the
[reserved-memory schema](https://www.kernel.org/doc/Documentation/devicetree/bindings/reserved-memory/reserved-memory.yaml)
support `size`, `alignment`, `alloc-ranges` and `no-map`. This is an allocation
policy to test, not an observed Windows firmware address or secure-loader pass.

[verify_relocation.py](verify_relocation.py) executes eight actual Linux MDT
bodies, including metadata construction, PAS initialization flow and segment
relocation, on all three retained firmware versions. Each image passes11 checks:
three synthetic physical destinations, exact loaded bytes/zero-fill, metadata
layout, mocked PAS failures, undersized memory rejection, direct no-init loading
and invalid-input rejection. ASan/UBSan remain clean. All images occupy5MiB and
produce7020 metadata bytes. PAS leaf calls are mocks; no SCM call, authentication,
firmware reset or live RAM allocation is performed.

## Validation and artifacts

[verify_power.py](verify_power.py) extracts the actual PM bodies and actual Linux
bulk clock/reset helpers. With Iris disabled/enabled it passes118/110 checks,
including64 power cycles per build,27 startup failure/retry points, three suspend
failure cases, every available VPU generation's selector and session ownership.
Clock-order, missing-domain-unwind and single-reset mutations fail as intended.
Leaf OPP/genpd/clock/reset operations and the existing core-choice algorithm are
synthetic. Failed runtime-domain puts and failed rollback leaf calls are outside
this harness; live power transitions remain unvalidated.

[build_venus.py](build_venus.py) verifies all96937 frozen AX source records, adds
exactly seven deltas (two camera, two IRQ and three PM files), and compiles/links
the Venus aggregate AArch64 objects with GCC16.1.1. The private config has the
same seven Venus/mem2mem/buffer-helper changes as the prior IRQ build. No full
kernel or loadable module is linked or deployed. Strict source checkpatch passes
with commit-message/signoff checks excluded; whitespace is clean.

- Power contracts:27 files, manifest
  `fbfe593f080e644e9e4b047de35bd05c1febbe956b8eb5521f5afe906ed86dfb`.
- Power native review v2:44 files, manifest
  `09548e112e96856d3db3fd112c90973653e1e58b4d8906f29118e3bf0c09e20a`.
  The earlier v1 review remains preserved.
- Relocation native review:25 files, manifest
  `f75981bf6603351c15603206d67631a34b4e67c72f9c96650ffe79a7e592a5fc`.
- Private aggregate build:32 files, manifest
  `d23aadc2fd7deb01e09c19b96040196498ff3a374a259469a20a00dac031eb5c`.
  Fresh private source/output trees are retained.
- AX `offline-video-power-20261003`:252 files, manifest
  `303ead2e01c2aa46e5befc815c1b77df531ac7a75e0bbda8b90cede28dce80fb`.
  All96937 final private-source records and seven deltas independently verify.
  Native, intermediate, firmware, memory-map, Kbuild and discovery artifacts
  are sealed. Prior183 IRQ files, nine corrected clock/power sources, reference
  pins and frozen AX/known-good boot artifacts verify unchanged. The archive's
  README is the pre-seal version; reconciled records are frozen separately.

Next complete the dedicated SC8180X resource, binding, DT/configuration and
firmware-specific SYS_INIT2 choice; reconcile the nonsecure SID2300/mask60 and
UC allocation policy. Build and fully archive a fresh candidate before a one-use
boot, then record authenticated firmware/HFI startup and advertised formats.
Real decoded/encoded output, sustained media, runtime/system PM and combined
regressions are still required. Never re-arm terminal AX. All47 hardware
acceptance boxes remain open.
