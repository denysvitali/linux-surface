# Surface Pro X boot diagnostics

These helpers capture a bounded diagnostic boot and its subsequent recovery boot.
They are device-specific: the initramfs logger uses this machine's EFI partition
PARTUUID. They must not be installed unchanged on other systems.

## Evidence requirements

Use a unique attempt manifest under `/var/lib/spx-boot-diagnostics/attempt.json`.
Record the source commit and diff, config, build log, kernel/DTB/initramfs SHA256,
System.map, vmlinux, selected entry and pre-reboot boot ID. Preserve evidence from
both the attempted boot and recovery under `boots/<boot-id>`.

Both kernels must use the same reserved region and layout:

```
ramoops.mem_address=0x9a480000 ramoops.mem_size=0x100000
ramoops.record_size=0x40000 ramoops.console_size=0x20000
ramoops.pmsg_size=0 ramoops.ftrace_size=0
```

Reserve that physical range in both DTBs. Use either the command-line-created
ramoops device or a DT-compatible device, without duplicate registrations.
Build the diagnostic kernel with `diagnostic.config`. Its built-in ramoops
registers at postcore init and replays the available printk ring into persistent
console storage. Recovery loads ramoops via `/etc/modules-load.d/ramoops.conf`.

The initramfs service must be included and linked into `initrd.target.wants`.
It runs whenever `spx_diag` is present; the historical logger was skipped by the
latest minimal boot because it required an unrelated old EFI-trace marker.
It snapshots dmesg to the EFI partition once storage is available. The root
collector runs on recovery too, copies pstore and initramfs logs without erasing
them, and records the current journal and hardware enumeration.

`return.timer` only matches `spx_diag=20260913`. After three minutes of a test
that reaches real userspace, it collects evidence and requests one reboot into
the persistent recovery default. It checks boot ID, uptime and pending GRUB
selection first. Never enable a loop that re-arms a failed test.

## Limits

`panic=20` permits recovery after a panic when the kernel restart path works.
A built-in watchdog restart driver does not by itself arm a watchdog before
userspace. Systemd's runtime watchdog covers failures after systemd opens it.
Neither mechanism guarantees recovery from an earlier firmware or CPU lockup.
Ramoops cannot capture failures before its initialization, and firmware or a
power cycle may erase reserved RAM. EFI trace values without a per-attempt
marker are stale evidence, not proof of where the current attempt failed.
A missing log must never be classified as a specific driver crash. If the new
attempt still leaves no early evidence, collect the last visible screen or an
external console and continue the existing source bisection.

## 2026-09-13 baseline

Recovery boot `e6350355-2f1d-4c98-80e3-25d82f4c57ac` runs 6.18.3-1-surface+.
Prior test entry used panic=0 and a mismatched recovery console layout. The last
recorded preceding boot was also 6.18 and shut down normally. No panic record
survived the reported mainline failure. RPMh skip-readback is a carried,
unverified workaround; the failed boot's root cause is not yet established.
Mainline audio, GPU, USB Alt Mode and modem remain unvalidated.

## Attempt 20260913-01 result

Recovery `a3e915fa-8a35-40e3-87db-3564a6a9db0d` has the intended ramoops
layout, but no pstore record, test journal, or `/boot/spx-diagnostics` log was
found. The diagnostic boot therefore has not established userspace reachability.
Its panic/restart location is unknown; the recovery method needs eyewitness
confirmation. Do not repeat that image unchanged or call the port working.

The latest archived bisect03 image decompresses exactly to the retained worktree
Image built at 2026-09-11 02:47:38. The worktree reflog was at `90ae888a3729`
from 02:18:40 until 02:51:42, when it moved to `6cc37b86f809` **after** the
successful boot began at 02:49:16. The journal for boot
`83670324-b53a-434f-9aeb-19497c9a362b` confirms `/init` and the guarded
userspace return at 02:52:17. This supports `90ae888a3729` as the latest good
source. The older bisect03 JSON manifests describe a previously replaced image;
they must not be used as provenance for that final successful run.

Next source candidate: `6cc37b86f809`, with the preserved three boot workarounds
(clock lookup errors, PCIe GDSCs kept on, EFI ResetSystem disabled), unique
`-spx-bisect04` release, matching diagnostic logger and built-in watchdog driver.
This is boot regression isolation, not a claim that this intermediate tree has
the full Surface port or passes component tests.

`grub-entry.py` renders literal-only test entries that save `spx_diag_attempt`
and `spx_diag_stage` to grubenv at each loader checkpoint. `handoff-ready` is
written only after fdt module, DTB, kernel and initramfs commands all succeed.
A failure records its stage and returns to the recovery menu. These disk markers
survive loss of RAM logs. They establish GRUB loader progress, not that the EFI
stub or Linux successfully executed after handoff. The collector archives grubenv.

Attempt `20260913-02` is staged as `7.1.0-spx-bisect04+` from
`6cc37b86f80985774809aba82283fe0d564d870f`. Image verification, the required
module set, clean `depmod -ae`, initramfs generation/content checks, GRUB syntax,
artifact hashes and 12 mocked reboot-guard tests passed. Its entry uses the
GRUB disk checkpoints. The result is recorded below.

Build note: invoke `make Image` separately from the set of `.ko` targets. Mixing
those goals makes this Kbuild version process targets individually, losing
cross-module exports at modpost (seen with the CAAM dependency set). Building
all required `.ko` targets together resolves that build invocation issue.

## Attempt 20260913-02 result

Recovery boot `427dcd47-72db-40f0-a8e1-9ef9ae98bfce` runs the known-good
6.18 kernel. GRUB persisted `spx_diag_attempt=20260913-02` and
`spx_diag_stage=handoff-ready`: loading the DTB, kernel and initramfs succeeded.
No pstore, initramfs disk log or test userspace journal survived. This narrows
the observed failure to after successful GRUB loading, but does not establish
whether the EFI stub or Linux ran. The recovery method remains unknown.
The complete result and recovery evidence are archived locally under
`/var/lib/spx-boot-diagnostics`.

The next source candidate is `d0bcd488c33d6673fe83b9533d6366ad84d2ec0d`,
the first parent of the PCI 7.2 merge. This keeps the three existing boot
workarounds and uses release `-spx-bisect05`. The interval includes Qualcomm
PCIe changes, but none is yet a demonstrated cause. Testing immediately before
the PCI merge separates that merge and the subsequent four merges from the
earlier interval. Runtime validation is pending.

Extracting IKCONFIG directly from the archived successful bisect03 kernel
confirms that bisect05 differs in configuration only by its release name,
`QCOM_WDT=m -> y`, and a new disabled Wacom touchscreen option. The built-in
watchdog remains a diagnostic variable relative to the historical good boot;
a failure here must not be used to blame a source commit without checking that
variable against the successful baseline. The extracted config is archived
locally as `last-good-extracted.config`.

Attempt `20260914-03` is staged as `7.1.0-spx-bisect05+`. The Image build,
matching boot-module build, separate Image verification, clean module dependency
check, initramfs generation/content checks and preflight passed. All 12 mocked
reboot-guard tests passed. The previous attempt's installed files match its
archived hashes, and the recovery kernel, initramfs and DTB match the original
recovery archive. No diagnostic reboot was queued during preparation.
The new manifest, complete build artifacts and logs are stored locally under
`attempts/20260914-03`; only the diagnostic slot was replaced.
