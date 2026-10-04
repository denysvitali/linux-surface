# CAMSS buffer allocator dependency correction

The active source now selects `VIDEOBUF2_DMA_CONTIG` from
`VIDEO_QCOM_CAMSS`. The local CAMSS video code references
`vb2_dma_contig_memops` both when preparing buffers and when selecting an
allocator for a device without an IOMMU mapping. Its previous Kconfig selected
only the scatter-gather allocator, so enabling the camera drivers produced an
undefined-symbol error during strict modpost.

The one-line change exactly matches the isolated Kconfig used in the successful
16-module strict link documented in
[camera-offline/CONFIG-REVIEW.md](camera-offline/CONFIG-REVIEW.md). The failed
unpatched build, successful patched build and exact module/config hashes are
preserved there. A fragment setting alone was discarded because this allocator
symbol has no prompt; selecting the actual dependency fixes the configuration
at its source.

After applying the correction, the active Kconfig was byte-compared with that
tested isolated file and `git diff --check` passed. The active `.config` remains
SHA-256 `bce9cd54b597a55c58e2264a94d25a877bf358dcc26f357d4673753471264bc2`.
No installed module, kernel, DTB or boot entry changed. I still runs the exact
G artifacts; the corrected source is for a later camera-enabled build.

The earlier offline review and its hash manifest remain an immutable record
of the phase before applying this source correction. This change does not
resolve camera bindings, rail ownership or capture validation.
