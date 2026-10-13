boxes closed: 3 of 47; newly closed: none.

# Venus shared-memory trial: startup still fails

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** user explicitly authorized parallel testing while camera-front
holds the device/build locks. Reloaded only the unbound, unused venus_core
module with `spx_uc_shared_alloc=1 spx_hfi_startup_diag=1`. Used the installed
module with matching vermagic. No kernel edits, rebuild, reboot, browser
flags or camera operation. Camera locks were left intact.

**Observed at 01:18:48–49 CEST:** authenticated-reset API returned 0;
remote-state resume returned 0. Queue address 0xbfc00000, queue size 2461696,
declared/backed UC size 3145728, SFR 0xbfe59000/4096 (inside UC region).
Startup poll returned -110 after 100 iterations, status 0, mask 0x1e2,
wrapper version 0x5010002f. Cleanup remote-state suspend returned 0.
Driver remained unbound; no Venus encoder/decoder nodes appeared.

**Meaning:** full UC backing and SFR containment are insufficient to repair
startup. This tests the previously untried BF hypothesis; do not repeat it.
Successful secure API returns do not establish firmware execution. Previous
binding/reserved-memory corrections and this allocation correction still
leave firmware/core readiness unresolved. The 6.18 board/chipset DTS has no
Venus node providing a known-working implementation to port.

**Cleanup:** reloaded the original module with default parameters; both
trial options read N. Boot unchanged, no persistent settings modified.

**Next / stop:** need new evidence on firmware startup/address-space
requirements to justify another code change. Existing findings do not justify
guessing secure stream IDs, fixed IOVAs or register writes. No further live
hypothesis identified. Hardware decode/encode remain unavailable; Chromium
integration requires functional codec nodes first. D03 remains open.
