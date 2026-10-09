boxes closed: 3 of 47; newly closed: none.

# Venus firmware comparison and missing VA initialization

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Firmware trials:** selected original qcvss8180.mbn from the user's
`~/Documents/drivers/FileRepository` via a temporary firmware lookup path,
one Venus reload per version, diagnostics on and default queue allocation.
2022 build 00061 at 01:22:10 and 2020 build 00040 at 01:22:21 both returned
auth/reset=0, remote-resume=0, startup=-110/status=0. No codec nodes.
Lookup restored, temporary files removed, installed 00042 and original module
parameters restored. No reboot or camera operation; user authorized parallel
Venus work. Firmware swaps alone are insufficient.

**New evidence:** original 2020 qcdxkm8180.sys (package
qcdx8180.inf_arm64_80e19250e112d800) has two constructors logging
`Sending TZ_MEM_PROTECT_VIDEO_VAR`, at RVAs 0x36aac0 and 0x371140.
At 0x3711bc/0x3711c0 the latter constructs call ID 0x02000c08, matching
Linux's SIP/MP/VIDEO_VAR API. Argument loads at 0x3711c8/0x3711dc read table
header +8/+12; 0x3711ec/0x3711f4 read the type-4 record's start/size.
Venus510 table RVA 0x1b56b0 yields exactly
`0, 0x25800000, 0x01000000, 0x24800000`. Both retained CB/ARID tables agree.
Static argument loads and patch constants checked directly against vendor
bytes. This establishes a vendor configuration contract, not Windows runtime
execution or a proven cause of the Linux failure.

**Patch:** SC8180X's resource table previously left all four fields zero,
skipping the existing native secure-call path in venus_boot(). Populate them
from the vendor table; log the native call result through the existing bounded
diagnostic. No new firmware, SID, physical carveout or hand-written secure call.

**Next / limitation:** WIP, not compiled or live-tested yet. Camera-front owns
the shared build directory; requested its release after the camera build.
Compile the Venus module and test this single change with installed 00042 and
default allocation. Hardware video decode/encode remain unavailable.
