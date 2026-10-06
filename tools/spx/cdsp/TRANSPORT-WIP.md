# Surface CDSP capability transport (WIP)

The board FastRPC node stays disabled. Its compatible selects a narrow transport
only on Microsoft Surface Pro X, SoC ID 340, CDSP domain 3. One nonzero session
uses the retained IORT/INF class+2 stream ID 0x1441, mask 0; Linux chooses the
hardware context bank. Windows CB 33 is not declared as a DSP ABI requirement.

The retained Windows allocator exception uses base 0x80000000 and size
0x7fffffff without the generic session<<32 tag. That is an inclusive end of
0xfffffffe. The GLINK edge's identity dma-ranges excludes the final incomplete
4 KiB page: effective bus_dma_limit must be 0xffffefff. Context probe requires
that exact inherited range, a single matching IOMMU firmware ID, a translated
DMA domain and active IOMMU DMA operations before publishing a session. Both
streaming and coherent masks are set to 32 bits.

Linux DMA-IOMMU uses bus_dma_limit as an upper allocation limit, but its
non-PCI initialization does not reserve the lower excluded range. This patch
therefore rejects allocations below 0x80000000, without retries or modifying
domain geometry. Rejected allocations are freed before any remote send.
Every accepted allocation, invocation header and transmitted page interval is
checked against the complete firmware window; imported mappings are prohibited.
All query allocation remains on the nonzero session's context-bank device.
Flat IOVAs are passed unchanged back to DMA APIs on cleanup. Other channels
retain their existing session offsets, stripping, heaps and process release.

Only the secure misc node is exposed, mode 0600, with CAP_SYS_ADMIN required
at open. Every ioctl except GET_DSP_INFO is rejected. At most one remote fetch
is attempted per channel lifetime; successful results may then be read from
cache. The remote message itself must be kernel handle 2, method 0, one input
and one output buffer. File close sends no process release RPC because this
transport cannot create or attach a PD. Existing pending-context references
retain possibly DSP-owned DMA after timeout; there is no forced reclamation.

This establishes neither live stream-routing permission nor a working query.
No VMIDs, memory ownership assignment, process creation, unsigned module loading
or workload invocation are added. The coordinator must build and perform a
bounded capability-only trial. B07 remains open.

Implementation evidence: drivers/of/device.c (of_dma_configure_id),
drivers/of/address.c (of_dma_get_range), drivers/iommu/dma-iommu.c
(iommu_dma_init_domain and iommu_dma_alloc_iova), and
RESULT-20261006cdsp.md for the retained Windows exception and SoC identity.

CU rejected the context before any capability fetch. Its first failure is OF
DMA translation at the GLINK edge. The CDSP remoteproc ancestor had no explicit
#address-cells: of_bus_default_match requires that property, so
__of_translate_address cannot select its parent bus. Add explicit 2/2 cells;
missing ancestor dma-ranges already means identity translation and is unchanged.
The exact guard fields are now logged if another mismatch remains. A rejected
context leaves the diagnostic RPMSG channel bound without any misc node, stopping
the probe-failure GLINK CLOSE/remote-OPEN recreation loop. Removal still releases
its children and channel reference. This correction remains untested on hardware.
