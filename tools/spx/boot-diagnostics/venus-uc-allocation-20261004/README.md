# SC8180X shared UC allocation experiment

BF's actual queue atbfc00000 occupies2461696 bytes, while UC declares3MiB.
SFR isbfbff000/4096, immediately below and outside UC. The retained original
miniport places SFR after queue data inside its startup allocation. Ownership
tracing distinguishes its nonsecure context0/CB10 from internal context4/CB13
and the caller's alignment4 argument. The timeout cause and firmware's UC
containment requirement remain unproven. See [BF's actual result](../RESULT-20261004bf.md).

The experimental [driver](../../../../drivers/media/platform/qcom/venus/hfi_venus.c)
adds default-off0400 `venus_core.spx_uc_shared_alloc`. Only SC8180X+Iris1
uses it. The enabled path allocates Linux's computed `SHARED_QSIZE` once,
zeros that backing, stores a distinct allocation owner, and retains the same
queue layout/size. SFR is a borrowed view after `ALIGNED_QUEUE_SIZE`, inside
the owner. Cleanup frees the owner once, then clears all views. The disabled
and other-resource paths retain separate allocations. No Windows IOVA,
internal SID, PAS reservation or firmware change is introduced.

[Native verification](verify.py) extracts verbatim allocator/free/defaults/
queue-init/queue-release/reinit functions, actual types/macros and the preserved
BF oracle. Mock DMA, OF, mutex and barriers touch synthetic process RAM.
With the Iris driver configuration enabled and disabled,744 unchanged-path
comparisons and24 shared-path cases pass under ASan/UBSan. Cases cover four
arbitrary IOVAs, board/generation/parameter gates, allocation failures,
reinitialization, parameter changes before cleanup and repeated cleanup.
Six deliberately corrupted candidates are rejected. Queue packet layout and
DMA sizes/attributes/free traces are checked independently of the candidate.
BF create/destroy/reinit bodies remain byte-exact. The inherited optional-SFR
failure's NULL-SFR reinit is not exercised; no hardware acceptance follows.

Original reinit-fixture and unused-mock negative-control failures are retained
separately. The fixture was corrected to preserve BF's firmware packet-drop
counter semantics; only the mock helper gains an unused annotation to exercise
the corrupted board gate. A first compiler producer failed before any work
because an ELF library was unavailable; standard-library ELF checks replace it.
The driver is unchanged by those verifier corrections.

[AArch64 compilation](build_venus.py) creates a private full BF source snapshot,
allows only the one driver delta, checks96938 records and84669 live compiled
paths, retains exact configuration, and compiles/independently links all14
Venus core constituents. The actual ELF parameter's0400 permission and zero
BSS storage are checked alongside module identity. This is a scoped compile,
not a full fresh kernel build or hardware startup result.

[Archival](archive_candidate.py) preserves the complete source tar stream and
configuration, native bodies/binaries/negative controls, object/link/parameter
proof, original failures and known-good recovery evidence. A full distinct
kernel/modules/DTB/private-initramfs build and independent runtime/deployment
review must precede the next one-use trial. Known-good remains the default;
no experimental image is selected. All47 hardware acceptance items stay open.

192-file source/native/object capsule:
`0cec64d92caef49bf0570da4a733f55711981f606f502d5a4e7a53bea2499dec`.
All96938 source tar records/1,647,574,472 file bytes are streamed and verified;
source archive`bb53363af151e49d1b903479650c462a91f8925d9aefba8ad4706922231dbe01`.
Candidate driver`baada5ccc9e08dd9267451cbfa32a23bf2b8eba064a63bf8250ba0f1f9c209ee`.

[Final module review](review_module.py) also compiles/links Venus core/decoder/
encoder through the supported isolated external-module output path, using the
exact frozen BF configuration and complete dependency symbols. Strict modpost
passes, with empty stderr and no missing-symbol bypass. The actual core module
again has a zero-default/0400 parameter. Module proof:
`2d2d1213b6456c6ad2b51622134400c2af13a1c9b681d357b5e91077e95c52a5`.
Core module`f6a13e032e5776fb505522b4f9f7a7968ed3afa8b10029b53327f4e266582b8f`.
The preceding single in-tree module target's modpost failure omitted exports
from peer V4L2/vb2/MDT modules. Its producer/command/stdout/stderr are separately
sealed; dependency context is corrected with the supported build mode. These
modules are scoped compile evidence with BF vermagic, remain uninstalled, and
are not substitutes for the full distinct next trial kernel.
