# Verified Iris1 startup diagnostic

Terminal BE accepted PAS9 memory setup at8d300000/5MiB, then timed out in
`venus_boot_core` before HFI SYS_INIT. Its strict baseline and actual901s
return are verified. All47 hardware acceptance items remain open.

The candidate changes only Venus hfi_venus.c, firmware.c and firmware.h.
Preimages/source-change hashes are retained in
`/var/tmp/spx-venus-startup-diag-20261004`; each preimage matches BE's full
candidate source manifest. All other compiled paths/config were checked before
editing. The live source now deliberately differs from frozen BE; do not call
BE guard.source expecting equality. BE remains terminal and must not be re-armed.

`venus_core.spx_hfi_startup_diag=1` will enable a default-off/read-only0400
Iris1-only diagnostic, capped to32 messages across both translation units.
It captures raw auth-reset/remote-state API returns, queue/SFR DMA addresses/
sizes/UC size and final existing control poll count/status/mask. One additional
wrapper hardware-version read occurs only with diagnostics enabled, in the
already powered core-startup path. Existing control writes, poll timing,
allocation addresses/sizes, secure-loader policy and errors remain unchanged.
Native actual-body disabled/enabled/scoped/cap controls pass79,296 before/after
comparisons under both Iris configurations, including poll100 nonzero timeouts
and raw remote-state errors before fallback. Six candidate corruptions are
rejected.16,000 concurrent helper calls per configuration admit32 messages.
ASan/UBSan output is clean. Native manifest761a8949…3919a.

All14 actual AArch64 Venus constituents compile and link; the shared gate is
defined once. Loadable-module identity `venus_core`, the unprefixed parameter
record and bool metadata verify. Full96938-record private source and84669
live compiled paths allow only the three insertions; configurations remain
exact. Compiler manifest81af3918…3e72e. Preserve original native control
compile failure204970b7…5c205 and incorrect built-in-prefix assertion with the
corrected module check. No kernel-source correction or repeated compilation
was required for the latter. `review_compile.py` records that boundary.

No runtime parameter, component binding, firmware reload, installed kernel,
boot payload or selection has been changed. Root cause, actual live diagnostic
values and HFI/media operation are unobserved. A fresh BF candidate must archive
the complete source/config/kernel/modules/DTB/initramfs and verified recovery,
use the same static DTB policy, preserve strict regression/900s return and be
independently reviewed before selection once.

Verified housekeeping10c8822e…a13b2 frees41,299,968 bytes by removing only BB's
three terminal, unreferenced duplicate boot files. Durable BB archives and
additional exact restore copies remain. All12 old BB units are inactive and
gated to its absent attempt; their content/state is preserved. Recovery and
active BE payloads rehash; persistent known-good and empty selection verify.
Now63,590,400 bytes are free in /boot, enough for one fresh40MiB slot.

BF's full Image/DTB and202 modules now compile/link and independently verify.
All202 vermagic strings/embedded config/default-zero Venus diagnostics pass;
raw and retained DTBs remain byte-exact BE. Source/config/private build archive
243 files, manifest0faf4fa9…cf7e/review2b35e937…cd81, preserve original stale
provider-path review failure. Initramfs/runtime/deployment/selection are next;
no actual diagnostic/HFI/media result follows.
[BF full build record](../PREPARED-20261004bf.md).
