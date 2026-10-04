# Prepared SPX text-target diagnostic trial — 2026-09-22

## Verified result

Trial `20260922a` completed its three-minute text-target test and returned
through orderly shutdown to known-good 6.18. See
[RESULT-20260922a.md](RESULT-20260922a.md) for boot IDs, archived evidence,
component failures and the next comparison. No graphical, audio or Wi-Fi
pass is claimed. The preparation and deployment sections below are historical.

## Deployment update after explicit authorization

The user accepted possible manual power-cycle recovery: "Yes. Proceed. Don't
ask." The verified payload, all 185 matching modules, early logger and GRUB
entry are now installed. The permanent archive is
`/var/lib/spx-boot-diagnostics/attempts/20260922a/`, including a full copy of
the build directory, installed-artifact hashes, `authorization.json` and the
previous boot files/configuration. Three unreferenced obsolete test files were
hash-verified into that archive before their space on `/boot` was reclaimed.
All known-good kernel/DTB/initramfs hashes are unchanged.

Read-only preflight, active GRUB custom-file inclusion, GRUB syntax, installed
module dependencies and service enablement passed. The planned trial still
uses the text target, watchdog node, early logging and 180-second return timer.
A one-time Happy session continuation is configured for the subsequent
known-good boot. Current selection/request/result state is in the permanent
`attempt.json`, `reboot-requested` marker and boot logs. Never repeat a reboot
from this historical preparation note without checking those files and boot ID.

## Original offline preparation record

State: built and checked offline; not installed or queued. No hardware trial
has run. The user requested a reboot/verify loop, but clarification is pending
on whether the existing mandatory pre-kernel recovery requirement is lifted.
Do not infer that permission from this prepared payload or the rendered entry.

Archive: `/var/tmp/spx-mainline-trial-20260922a.2nv_pgpl/`.
Release: `7.3.0-rc2-spx-mainline-20260922a+`.
Source: `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b` plus the archived
worktree diff, including the MSM `FBINFO_VIRTFB` correction.
The config differs from the preceding build only in `CONFIG_LOCALVERSION`.

## Test to perform once the recovery constraint is resolved

The planned command line uses `systemd.unit=multi-user.target` to exclude
the graphical login, with the existing DTB and its watchdog node retained.
This separates desktop startup from the unexplained loss of progress near
27–29 seconds. It does not isolate every kernel or driver variable.

The diagnostic marker remains `spx_diag=20260913` to match the installed
return timer and collector. `spx_attempt=20260922a` identifies this trial.
`panic=20 oops=panic` requests a restart after a handled oops/panic; it does
not provide protection before the kernel runs or during an unhandled hang.
The existing three-minute diagnostic timer provides a bounded userspace test.

The previous `/usr/local/sbin/spx-next-verify` waits until after
`multi-user.target`, then sleeps 20 seconds; its output missed both failed
boots. The periodic diagnostic collector starts at 30 seconds, also later
than either retained journal. The new `early-log.service` starts before
`sysinit.target` and preserves immediate, then two-second kernel snapshots
for three minutes. Its script and unit are staged under `logging/`; they
have not been installed into the host. They must be installed and enabled
for a future authorized trial.

The initramfs includes the existing EFI-partition logger, enabled under
`initrd.target.wants`. This hook was absent from the prior 7.3 payload.

## Verification

- Image, SPX DTB and all 185 modules built successfully with the distinct release.
- Staged module dependencies pass `depmod -ae -F System.map` without diagnostics.
- All 42 diagnostic tests pass, including three new tests for early-log
  exclusion on ordinary boots, bounded retention across service restarts,
  and preservation of completed snapshots after a failed capture.
- Shell syntax, systemd service verification and the rendered GRUB entry pass.
- The initramfs contains the byte-identical rebuilt MSM module, executable
  initramfs logger, exact service, and its enablement symlink.
- The Image's embedded config matches the archived config. The compressed
  kernel decompresses exactly to the archived Image.
- The initramfs build reports the expected skipped ARM64 microcode hook and
  missing optional privacy-screen provider. An initial build with an incorrect
  hook search path failed; its log and incomplete image are separately retained.
  The corrected build succeeded and passed the content checks above.

| Artifact | SHA-256 |
| --- | --- |
| `vmlinuz` | `89a78639a4101d5e9f9d2c03f7850bbb0831bb48859995d592b1e525ab8a88ff` |
| `initramfs.img` | `957c2200728b0ab91d842dea87f362463966a622eda172253a1d6c8939f691e9` |
| SPX DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

The manifest, planned command line/entry, source/config snapshots, module tree
and all build/test logs are in the archive. The initramfs is access-restricted
because it includes this installation's existing root-unlock material.

## Deployment still outstanding

Nothing in `/boot`, the installed module trees or the active logging services
was replaced. The compressed kernel and initramfs total about 40 MiB, while
`/boot` has about 15 MiB free. A future authorized deployment must archive and
verify obsolete test-slot files before reclaiming space, and preserve every
known-good artifact. Install the distinct module tree and early logging unit,
then validate the exact installed payload before selecting it once.

The current boot is still `adf0c7a4-aeea-4ee4-bedd-4a82e60a3545`, running
known-good 6.18. `saved_entry=spx-known-good`; `next_entry` is empty. The
deployed boot artifact and GRUB hashes match the pre-work snapshot.
Neither EFI-handoff recovery nor the mainline freeze has been resolved.
