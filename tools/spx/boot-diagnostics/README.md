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
