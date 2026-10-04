# Camera-only v23 extraction — offline review

**2026-10-03 update:** the CCI binding addition has been applied separately;
rear supply ordering is fixed and verified offline. CAMSS schema and all camera
nodes remain drafts/disabled. See the
[camera power audit](../camera-power-20261003/README.md) for firmware rail findings
and the remaining provider/integration requirements.

Completed bounded review, 2026-09-22. This directory is an offline review artifact;
it is not wired into the kernel DTS build, a boot entry, an overlay loader, or
an installed service. Do not deploy it or enable its camera nodes.

Reference:
`/home/dvitali/Documents/git/linux-surface-kernel/docs/camdtb/v23.dts`
SHA-256: `e69f2637abc57ec2eca28925ce9b3e5c984e1d0085f06c0f45d6148fb92899d7`.
The associated raw capture archive was verified in
`../CAMERA-STATUS-20260922.md`.

The extraction retains only CCI0, its three sensors, the necessary pinctrl
states and CAMSS graph/resources. Nodes remain disabled. The old fixed supply
placeholders are deliberately excluded: the working experiment depended on
separate direct SPMI writes to LDO14_A/LDO17_A/LDO1_A. A correct provider and
power sequence is unresolved; omitting those supplies does not make automatic
sensor probing safe. No hardware probing, module loading or runtime writes
are part of this work.

`CONFIG-REVIEW.md` records the isolated configuration/build. All 16 explicit
camera/support module targets pass strict modpost and linking after adding
`select VIDEOBUF2_DMA_CONTIG` only in the disposable source snapshot. The
unapplied patch is `camss-dma-contig-kconfig.patch`. The unmodified local CAMSS
Kconfig fails strict linking because it selects only the scatter-gather
allocator while local code also uses the contiguous allocator. All 47 active
input hashes were verified unchanged, including `.config`, `vmlinux.o` and
camera sources. No modules or DTBs were installed.

## Topology extraction and verification

`spx-camera-v23-disabled.dtsi` uses current symbolic clock, power-domain,
GPIO, interrupt and interconnect definitions. Clock/reset/power-domain IDs
occupy separate namespaces in the provider headers; the extractor checks them
separately and rejects duplicates within each namespace. It retains the v23
register ranges, interrupts, clocks, interconnect paths/tags, IOMMU SID/mask,
sensor rates/lanes, graph links and pinctrl states without inventing values.
Unused CCI controllers, unrelated historical board changes and experimental
power helper nodes are excluded.

`spx-camera-review.dts` includes the current board tree and the disabled
extraction. `verify_topology.py` compiles both this wrapper and the unchanged
current board tree. It compares the extracted graph/resources with v23 using
canonical provider paths in place of renumbered phandles. The result is:

- 26 nodes and 124 properties equal; no unexpected differences.
- Five camera/controller nodes explicitly disabled and nine historical
  placeholder supply properties omitted, as recorded in the manifest.
- Review and base DTC warning logs are byte-for-byte identical. Existing base
  warnings remain; this is not a claim that the whole board is warning-free.
- Current clock/reset/domain symbols checked independently of numeric DTB
  equivalence.

Reproduce from the repository root with system Python/libfdt, cpp and dtc:

```sh
python3 tools/spx/boot-diagnostics/camera-offline/extract_v23.py
python3 tools/spx/boot-diagnostics/camera-offline/verify_topology.py
```

Outputs live in `/var/tmp/spx-camera-offline-20260922`; the manifest,
comparison result and all DTC logs are preserved here. The comparison is to
a prior working experimental topology, not proof that the next kernel has
safe power sequencing or hardware capture compatibility.

## Schema review and next work

A subsequent isolated controller-binding draft is now documented in
`BINDING-DRAFT-REVIEW.md`. The two-line CCI addition and separate provisional
SC8180X CAMSS schema pass meta-schema checks; negative validation verifies
clock/register/endpoint constraints and preserves the missing-supply blocker.
These patches remain unapplied, and the original sensor diagnostics below
still apply. See that note for the unresolved CAMSS IOMMU/supply scope.

Focused current-schema validation completed with diagnostics, recorded in
`SCHEMA-REVIEW.md` and `schema-focused.log`. SC8180X CCI compatible coverage,
SC8180X CAMSS and OV13858 bindings, and OV7251 lane/property representation
remain unresolved. The full schema-directory scan reached its 60-second
bound; a focused six-schema subset completed in 1.425 seconds. Neither schema
exit code zero nor disabled nodes establish a deployable camera description.

The next offline work is to review the small Kconfig dependency patch for the
intended branch, describe SC8180X resources in bindings, and resolve the actual
rail provider/ownership and sequencing from existing evidence. The historical
fixed supplies are not an implementation of that power path. Keep this
extraction disabled until those dependencies are addressed and a complete,
distinct camera candidate can be built and archived for a later trial.

This phase is finished and no build/validation process remains. The active
`.config`, core sources/DTS, boot files, installed modules and runtime were
not modified. All changes from this phase are review artifacts in this
directory or disposable files under `/var/tmp`.
