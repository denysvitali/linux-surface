# Surface CDSP capability transport (WIP)

The board FastRPC node stays disabled. Its compatible selects a narrow transport
only on Microsoft Surface Pro X, SoC ID 340, CDSP domain 3. One session uses
`reg=1`, retained IORT/INF stream ID 0x1441, mask 0; Linux chooses the hardware
context bank. Windows CB 33 is not declared as a DSP ABI requirement.

## Host allocation and wire encoding

The retained Windows allocator exception uses base 0x80000000 and size 0x7fffffff
without the generic session<<32 allocator base. This is a **host allocation**
exception, not a flat FastRPC wire address. The GLINK edge's identity dma-ranges
excludes the final incomplete 4 KiB page: bus_dma_limit is 0xffffefff. Context probe
requires that exact inherited range, one matching IOMMU firmware ID, a translated
DMA domain and active IOMMU DMA operations. Streaming/coherent masks remain 32 bits.
Lower allocations are rejected without retries or changing domain geometry.

Retained `qcadsprpc8180.sys` gives the missing wire contract:

- Registry parser 0x14000b8ec–b914 reads SidInfo's low nibble into the session
  field at domain+0x120. The first CDSP SID 0x1441 supplies tag 1. Session allocation
  at 0x140009918 points the file's session to domain+0x110.
- Allocator 0x14000be1c–be24 skips the generic shifted base for SoC 340/domain 3.
- Mapped-address builder 0x14000cd14–cd58 takes the 340/domain 3 branch to cd4c,
  reads session+0x10, and ORs its tag<<32 into the allocator-derived address.
- Header builder 0x140002d14 calls d868, then cbd8, with message+0x18 as its address
  destination. Argument-page builder 0x140002b2c calls the same cbd8 helper.

Thus host IOVA 0xffffe000 is wire address 0x1ffffe000. Default sid_pos=32 tagging and
stripping now apply: host DMA APIs receive the low IOVA on cleanup, while the
header and pages receive tag 1. Every transmitted interval requires exact high
word 1 and a valid low interval ending at or below 0xffffefff. Bounds checks reject
zero size and crossing the low window, so a page cannot roll into the next tag.
Imported mappings remain prohibited. The one query logs host/wire header and page
addresses. No high alias mapping or ownership assignment is introduced.

## Trial scope

Only the secure misc node is exposed, mode 0600, with CAP_SYS_ADMIN required at
open. Every ioctl except GET_DSP_INFO is rejected. At most one remote fetch is
attempted per channel lifetime; successful results may then be read from cache.
The message must be kernel handle 2, method 0, one input and one output buffer.
File close sends no process-release RPC because no PD can be created or attached.
Existing pending references protect DMA while a remote context remains outstanding.

CU rejected DMA translation before sending; explicit remoteproc parent bus cells
corrected that failure. Rejected sessions retain a bound diagnostic channel without
a misc node, preventing GLINK reprobe storms. CV passed the translated-domain
guard but sent an untagged query and CDSP watchdoged; this wire correction is
unverified on hardware. It neither proves the watchdog's cause nor firmware process
authorization. B07 remains open. Keep the same session, DMA window and one query
for the changed trial; no SID, CB, VMID, unsigned-PD or workload guess is justified.
