# Experimental static Venus reservation after BD

Open checklist ID D03. BD's actual boot could not dynamically allocate 5 MiB
inside the SCM aperture because the entire aperture is NOMAP. The strict
baseline and actual guarded return passed; BD remains terminal. See
[BD result](RESULT-20261004bd.md). A new static board reservation is compiled
offline; its physical availability, PAS acceptance and media behavior require
a distinct hardware trial.

Retained PIL initialization is now traced from PGCM registry values to a
linked list at RVA23510. BaseAddress/Size seed the list; firmware requests
consume aligned spans and enqueue prefix/suffix leftovers. The nonzero
DoNotReturnMemoryToHLOS option bypasses memory addition. Otherwise, the remaining
nodes pass their physical base/length fields by address to the imported
MmAddPhysicalMemory routine. Microsoft documents that this makes physical
memory available to subsequent OS allocations.
[Microsoft API contract](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddk/nf-ntddk-wdm-mmaddphysicalmemory).
This is a static retained-code path, not observed Windows execution.

The audit pins 87 reachable instructions and independently compares all 87
GNU operands over 11 .pdata functions. The exact vendor binary, original INF,
Unicode descriptors and two pinned Microsoft WDF tables are sealed in
BD/offline-pil-pgcm, manifest
`189bf7f17c2220a9dde2a186380501949e50ee47f67f97575fe5c7774dd0c57d`.
The original incorrect base-register pin at RVA11804 is preserved separately,
manifest `64592a08a47da6a38026b5594fadf12d1d477938258eb311512deac2fffc6637`.

A scan hashes all 526 retained INFs and records all six files declaring PGCM,
physical firmware addresses/reservations or the memory-return switch. The
Surface extension requests Venus5MiB; modem/ADSP/CDSP/SLPI sizes agree with
the recorded Linux reservations for the corresponding MSM variant. The
retained APQ modem variant requests less memory, but the candidate preserves
the full existing MSM region. IPA and SPSS each request1MiB with no fixed
retained address; their actual placement and Linux acceptance remain open.

PGCM is8bd80000..9a500000-exclusive. Subtracting every recorded DT reservation
and the primary ACPI cameraVFE0/WLAN/QSM claims leaves a single interval large
enough for video:8bd80000..8d800000. Selecting its highest1MiB-aligned5MiB span
gives8d300000..8d800000-exclusive, immediately below the unchanged modem
reservation. This computation uses the retained pool and actual reservations;
the historical board comment is not its evidence. The remaining prefix has
21.5MiB; this capacity calculation does not validate other firmware placement.
The policy capsule is BD/offline-pil-reservation-policy, manifest
`cd27a2636b9e3c86d20aae50d39dcecde044ab75f5e9beb6105ced45e9dbf687`.
Its preliminary version remains separately preserved, manifest
`3497f5f064e258cba26c48087192864821f84858e64cfa83b4d56fe2622ef8b6`.

The sole compiled-source change from BD is:

```dts
venus_mem: video-firmware@8d300000 {
        reg = <0 0x8d300000 0 0x500000>;
        no-map;
};
```

It replaces the dynamic size/alignment/alloc-ranges node. The standard OF
static-reg path marks the chosen range NOMAP and records it for the Venus
memory-region consumer; ordinary allocation and the generic memblock allocator
are untouched. No part of the firmware pool is released into ordinary RAM.
The generic binding supports static reg/no-map with a unit address.
[Pinned dt-schema source](https://github.com/devicetree-org/dt-schema/blob/5687115902ba74c1cd80bdab4772cc2cdfa75778/dtschema/schemas/reserved-memory/reserved-memory.yaml).
Absence of every unrecorded owner is not established. This is an experimental
Linux reservation, not an observed Windows Venus address. Original EFI
descriptor types remain unobserved. The separate existing ramoops/QSM512KiB
overlap remains preserved and open.

Both source and retained boot DTBs compile. Full642/657-node comparisons allow
only the node rename and replacement of the three dynamic constraints with
reg; all other values, phandles, provider arguments and FDT reservation entries
are exact.84669 compiled paths permit only this board change, and the live
config remains exact. Source SHA:
`0edc078ca14ca2818c4c26313baf79d121c6e05cafb1ab93ac68d3a1629f9912`.
Raw DTB SHA:
`0b86a7f1d18f19f281cf880c5cf5159ff2711116b1f51fe56aa5ad361ecd8928`.
Retained DTB SHA:
`2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252`.
Compilation capsule BD/offline-video-static-reservation manifest:
`db344ac87ca686ed6c7ea644ed6e5ae3d1bd15fc3997142b6c2071b9fb8fd873`.
The first verifier reached all DT/provider checks, then failed because the
generic schema moved out of the kernel tree. That run is sealed separately:
`139cef2926b73c89177613d4ffd4dead26f84bb0f57cc563e70194bbb3a3db02`.
The corrected check pins the primary schema's commit and bytes. Scoped
checkpatch passes with zero errors/warnings.

BE's exact BC executable artifacts, full96938-record source and sole external
DT change are now archived and independently rehashed. See
[prepared BE archive](PREPARED-20261004be.md). Next adapt and verify its
reservation/PAS startup collectors, strict baseline and
guarded return, then install and select BE once. BD must not be re-armed.
Actual reservation, firmware load/authentication, HFI, advertised formats,
decode/encode outputs, sustained media and combined regressions remain open.
All47 acceptance boxes remain open.
