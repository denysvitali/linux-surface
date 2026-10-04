# PIL aperture correction for Surface Pro X SQ2 video

Open checklist ID: D03. BC's successful PIL area query reports an inclusive
start0x8b700000/exclusive end0x9ab00000,244MiB. The actual reservation at
0xfe500000..0xfe9fffff is outside it. Original PAS memory setup returns raw
0xffcfffba/errno-22; its encoded vendor meaning remains unresolved.
[Actual BC result](RESULT-20261004bc.md).

The response correlation is independently pinned to retained TrEE bytes,
52 instructions/11 GNU operand comparisons, the primary Qualcomm interface
header and frozen Linux SCM source. The wrapper generates abstract completion1
before copying raw x1/x2/x3. Start/end map to Linux result0/1. The durable55-file
BC/offline-pil-response-20261004 capsule has manifest
`e0404039eab2daa54769841f30c0fb45ff82e18ebce0f272a5be6ef289246b57`.
This proves the response layout/reporting, not PAS acceptance at a new address.

The sole source change from BC replaces Venus alloc-ranges:

```
before: <0 0x80000000 0 0x80000000>
after:  <0 0x8b700000 0 0x0f400000>
```

The range size is end minus start; its end is0x9ab00000. Five-MiB size,
one-MiB alignment, no-map and dynamic allocation remain exact. The existing
OF reserved-memory implementation reads range start and length, adds them to
form the exclusive end and uses memblock_phys_alloc_range; existing reserved
memory is excluded by that allocator. No fixed address or secure firmware
policy is introduced. Actual availability/base/PAS acceptance must be observed
on the next candidate; no base is predicted as accepted.

verify-pil-allocation-20261004.py checks84669 compiled-source paths against
BC's frozen manifest, allowing only this exact board-line delta, plus unchanged
live config. Both source and retained boot DTBs compile. Independent flattening
compares all642 source-tree nodes and657 retained-tree nodes: exactly one
alloc-ranges property changes; all other values, phandles and explicit memory
reservations match. Recompiled original retained DTB is byte-exact BC.
Actual provider argument contracts pass. Candidate raw DTB:
`98d242d6fad92f0587e2671067cc989eb7a55473b395bad2e1e142ebb227b5d7`.
Candidate retained boot DTB:
`4205df02a7ad7b0827eff3816d50446123442ff10b9eec16203e564018f4e812`.
The30-file scoped proof is preserved at
BC/offline-pil-allocation-20261004, with inner compile manifest
`2fdcbeea98a96d7cf13bd7ec034dc19f5ed5d17b9abd070614bf0472383f9c58`.

Nothing is installed or selected by this scoped verification. Preserve BC's
terminal result and known-good default. The next distinct trial needs complete
source/config/kernel/modules/DTB/initramfs provenance and adapted startup/media
review which can record PAS memory success or the next failure, rather than
requiring the old error. Actual decode/encode reference checks and sustained
media remain required; all47 hardware acceptance boxes stay open.

The durable90-file allocation capsule rehashes both the scoped build and the
preserved first archive/style-metadata failure, plus sources and documentation.
Manifest:
`7ea8cd629539bcb698e62a093442ae12ae0df7d1abaa42730fcb4e1250c2ba18`.
Code checkpatch reports zero errors/warnings; commit-message checks are excluded
because this is an uncommitted scoped patch. The original missing-description
warning is preserved. Known-good remains active/default; next empty/BootNext
absent. The correction is ready for complete candidate packaging and hardware
validation; no boot was selected by this work.
