# Independent K deployment review, 2026-09-22

The prepared K deployment passed independent read-only review while J remained
live as boot `6a9377c7-dcd8-463c-823e-c29710eb5e96`. The last boot-selection check
was at 2655.89 seconds of J uptime. K was not queued or booted at that check.

## Preserved provenance and recovery

The permanent K build archive contains 902 regular files whose independently
recomputed hashes exactly match its manifest and the verified staging tree.
Its 272 symlinks match the stage without following them. Private archive,
initramfs and extraction permissions are intact. See
[the artifact review](ARTIFACT-REVIEW-20260922k.md) for source, configuration,
Image, module and actual compressed-initramfs verification.

The deployment script was reviewed before execution. It checks the current J
boot, empty pending selections, pinned J baseline, complete K archive and
existing boot/recovery/runtime hashes before deployment. It installs the
distinct K module tree, archives and verifies all three consumed G boot files,
syncs the copy, and rechecks boot identity and recovery before reclaiming G's
boot slot. The archived G initramfs is mode 0600; G's installed modules remain.

After execution, this reviewer independently verified all three retired G
files against the recorded hashes. All three known-good recovery files still
match their unchanged hashes. `/boot/grub/grub.cfg` is byte-identical to its
preparation snapshot and retains `spx-known-good` as the persistent default.

## Installed candidate

All 202 regular files under
`/usr/lib/modules/7.3.0-rc2-spx-mainline-20260922k+/` exactly match the archived
module manifest. There are 187 modules and every independently read vermagic
names K. The installed depmod log is empty. SPI-HID is supplied by this exact
installed tree; it is absent from the initramfs.

All three deployed K payloads match the verified build hashes, and all eleven
runtime files match the manifest. Global and per-attempt manifests are equal.
The pinned J result hash is
`f0b8353f913b645d36c256b29e447301e902f59a5be5b089a6fc60a996f27fdd`.
The completed read-only preflight records that same validated J origin. Its
scoped graphical/audio result does not erase J's documented input failure.

The candidate command line is exactly J's command line with only the attempt
marker changed to `20260922k`; audio remains at stage 4. The new entry references
only K boot payloads. Both GRUB files pass `grub-script-check`, and the custom
file contains exactly the archived K entry.

The early logger, return timers and boot evidence service are enabled; the
600-second marker still suppresses the short timer and selects the long timer.
All origin return timers are inactive and the periodic evidence timer remains
active. The collector's recorded exit status is zero.

## One-shot queue boundary

The queue script was reviewed but not executed by this reviewer. It reruns
preflight, checks installed/payload/recovery/runtime hashes, verifies native
Happy continuation and its live session process, checks saved and pending boot
selection, and rechecks boot identity before creating an exclusive, flushed
request marker. It then selects K once, rechecks selection and identity, syncs,
and schedules a reboot. A queue failure clears its own pending entry and keeps
the request marker for inspection.

Independent live checks confirmed native continuation uses the expected
session/thread and `continue` message. Only whitelisted values were inspected;
no raw session metadata was printed or retained by this review.

At the final check, `saved_entry=spx-known-good`, GRUB `next_entry` was empty,
EFI `BootNext` was absent, and K had no `reboot-requested` marker. The root
workflow must still collect its final J logs and perform the immediate
pre-reboot queue checks. This review is preparation evidence, not hardware
validation of the SPI-HID fix or automatic pre-kernel recovery.
