# CDSP: v66 workload prepared; live address contract unresolved

Preparation on recovery boot `bde03752-0ef8-4bad-a2cb-488536f52bc1`,
kernel `6.18.3-1-surface+`. No CDSP invocation or new boot was performed.

**Changed:** add `tools/spx/cdsp/` with a freestanding v66 FastRPC skeleton,
reproducible Makefile and independent host arithmetic checks. Its two methods
compute a wrapping uint32 sum and a 64-element signed dot product modulo 2^64.
Privately extracted clang/lld23.1.1 packages have valid trusted Arch Linux ARM
signatures; system packages were not changed.

**Observed:** a fresh output-directory build passes. The DSP library is
ELF32 little-endian DSP6, flags0x66, exporting `spx_workload_skel_invoke`,
without undefined runtime symbols, dynamic dependencies or relocations.
Host checks pass overflow, vector arithmetic, unaligned buffers, rejection
and output canaries. These establish a usable build input, not DSP execution.

**Session evidence:** retained `qcadsprpc8180.inf` lists hardware CB indices
0x21..0x28 and stream IDs0x1441..0x1448. SQ2 IORT groups six stream classes per
ordinary session; the five active CDSP ARID bases select sessions1–5, with
base+2 corresponding to0x1441..0x1445. Those values are distinct from the
Linux FastRPC session `reg`, which the default driver encodes in bits32+.

Retained `qcadsprpc8180.sys` at0x14000be1c special-cases cached platform340
and domain3: allocator base remains0x80000000, bypassing the generic session
field shift at0x14000be90; the allocation size is0x7fffffff. The enclosing
domain loop and CDSP string records support the domain attribution. The driver
reads the second uint32 of the ACPI `SOSI` structure; Linux's socinfo likewise
reads the ID from the second uint32 of SMEM item137. Public sysfs on this
Surface reports SoC ID340, machine `Microsoft Surface Pro X (SQ2)`, revision2.1.
This corroborates the exception without reading an arbitrary physical address.
The complete address translation and firmware process authorization remain unresolved.
Linux `unsigned_support=true` is host policy and does not establish the
retained firmware's permission. Neither speculative `reg=1` nor `reg=0`
is declared: the latter also interacts with physical-DMA selection.

**Meaning/next:** B07 remains open. A matching v66 workload is now available;
resolve the Surface address translation and process-creation contract before
adding a live context bank or invoking it. Keep physical/battery deferrals,
known-good default and current CT candidate. No sound or capture occurred.
