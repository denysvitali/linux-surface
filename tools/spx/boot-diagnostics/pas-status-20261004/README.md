# BB PAS status and retained memory-call ABI

Targets open D03. Actual BB raw status `0xffcfffba` remains unidentified.
The reviewed evidence establishes the call ABI, not an acceptable address or
the reason QSEE rejected this request. No compiled kernel, memory allocation,
firmware authentication policy or live device was changed by this review.

[BB actual result](../RESULT-20261004bb.md) observes init-image success followed
by memory-call failure, with PAS9/startfe500000/size500000 and raw a0
signed32-3145798. Linux's default SCM errno mapping yields -EINVAL.

The retained Qualcomm PIL driver has SHA256
0821cba482219b0aac2c0c47c4149d06a385013a4ebfa30211ed653f5b8ea242.
Its .pdata-bounded function bd60..c568 selects command02000202 and calls the
request constructor9370..9afc. The actual jump table selects its memory branch;
23 instruction pins verify descriptor3, sign-extended processor from context28,
64-bit physical address from contexte8 and 32-bit length from contextf0.
The producer7e20..85c8 copies descriptor40 to contexte8 and descriptor28 to
contextf0; release85c8..8830 clears the physical field. These two functions
and their bytes are also preserved. Length rounds upward to4096, with zero
replaced by4096. BB's existing five-MiB
length satisfies that rounding. This static code does not establish actual
Windows arguments or allocation success. The matching call ABI does not
justify changing memory placement or interpreting the raw status.

The retained SCM/TrEE/PIL binaries contain neither the four-byte raw status
literal nor its positive magnitude. This limited scan does not exclude
computed status handling or a definition in secure firmware. Full original
binaries, exact function bytes, .pdata-aware reader, disassembly and review
are retained by audit_vendor.py; no vendor code was executed.

The public Qualcomm-copyright BSD interface header, pinned at
edk2-porting/edk2-msm commit e1952621f419f8db60ed28271264e1b5184c571d,
defines this PIL call with three UINT64 fields and the same parameter
descriptor. Its description places memory-region/ELF compatibility checks
at this call, but it supplies no definition for BB's encoded error. This is
generic interface evidence, not a device-specific memory acceptance rule.
[Pinned interface source](https://github.com/edk2-porting/edk2-msm/blob/e1952621f419f8db60ed28271264e1b5184c571d/Silicon/Qualcomm/QcomPkg/Include/Protocol/scm_sip_interface.h).
Retrieved bytes/hashes and provenance are retained under upstream/.

The durable35-file capsule is BB/offline-pas-status-20261004, manifest
84dde500628ff25e0d4ca39f928b46711fa8d04e1e65241b9d4f4f0c3b190447.
It independently rehashes both vendor review versions and the primary-source
review. Six GNU disassembly operand checks agree with the request constructor.
The original check's decimal/hex formatting failure is preserved separately;
numeric operand comparison passes without changing vendor or kernel bytes.

The subsequent [memory-area audit](audit_memarea.py) follows nine actual
.pdata functions and35 instruction pins. Command02000209 has descriptor1
and a zero spare argument. Its wrapper checks completion and copies the
returned start/end (truncated to32 bits) into globals235a0/23598. The dynamic
reservation branch passes those globals as lower/upper bounds into the
allocator. With alignment0 or4096, it directly calls the bounded
MmAllocatePagesForMdlEx wrapper (flags25), then maps the allocated pages and
obtains their physical address. Other alignments use a physical-range scan.
The generic query response definition describes inclusive start/exclusive end;
the retained Windows code does not establish actual device values or Linux's
raw result-register mapping. These remain unobserved.

Durable20-file BB/offline-pas-memarea-20261004 independently rehashes all
input/function bytes, with eight GNU operand checks; manifest
9ca2204079845aa6d555c9b6bb9862298c6103366a9bb5010d4165ddc8a617eb.
The next experiment should observe this query's transport and all raw result
words on a fresh diagnostic candidate before altering the reservation. Keep
the query default-off/read-only and bounded to one PAS9-triggered invocation;
retain existing init/memory arguments and return behavior. Interpret bounds
only after valid completion/register-layout evidence. No suitable address,
encoded-error definition or allocation-policy fix has been established.
Preserve all47 acceptance gaps.

The actual [BC result](../RESULT-20261004bc.md) now supplies a successful
query: raw0/8b700000/9ab00000/0. The subsequent audit_response.py correlates52
retained TrEE instruction pins and11 independent GNU operands across five
.pdata functions/two assembly SMC thunks. In the64-bit leaf1080..10d8,
SMC returnx1/x2/x3 are stored into the caller's payload buffer. The17300..1781c
wrapper selects the64-bit call with bit30, checks zero status, inserts
abstract completion1, and copies payload words to response8/16/24. The32-bit
path has the same generated completion/payload ordering. Initialization stores
the selected wrapper pointer; dispatcher calls it with its response buffer.
No Windows or vendor code was executed. The thunks precede.pdata-covered C
functions; their bounds are instruction/return based and explicitly distinct.

The pinned primary header places inclusive start/exclusive end at8/16 after
the completion field; frozen Linux SCM maps a1/a2/a3 toresult0/1/2. Thus BC
reports8b700000..9ab00000 exclusive (244MiB). The currentfe500000 five-MiB
reservation is outside that aperture. A narrower alloc-ranges property is now
justified; keep existing size/alignment/no-map and let memblock exclude existing
reservations. This is a proposed correction, not PAS memory/authentication/HFI
or media acceptance. The encoded status remains unidentified. The failed GNU
comparison with an objdump inline-comment annotation is preserved; stripping
that annotation/numerically normalizing operands passes without byte changes.
