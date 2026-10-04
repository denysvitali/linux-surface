# Independent L deployment review, 2026-09-22

The prepared L deployment passed independent read-only review while K remained
live as boot `58d2ebe1-1b3d-4b75-aa1e-d0ff2d8b9562`. Checks ran at
**2332.90–2334.95 seconds** of K uptime. L was not queued or booted at the
final check.

## Provenance and recovery

The permanent L build contains 937 independently verified regular files and
272 matching symlinks, with private archive/initramfs permissions intact.
[The artifact review](ARTIFACT-REVIEW-20260922l.md) records the exact source,
configuration, Image, module and actual compressed-initramfs checks. It also
verifies the compiled SPI-HID diagnostic parameter's zero default and 0444
permissions. This is metadata logging, with no speculative descriptor request.

The deployment helper was reviewed before execution. It checks live K identity,
empty pending boot selections, the pinned K baseline, the complete L archive
and existing payload/recovery/runtime hashes. It installs L's distinct module
tree, archives and verifies K's three consumed boot files, syncs the copy, then
rechecks identity and recovery before reclaiming only K's boot slot.

After execution, this reviewer independently rehashed all three retired K
files under L's `retired-boot-slots/20260922k/`; all match K's recorded hashes.
The archived K initramfs is 0600. The consumed K boot directory is absent,
while K's installed module tree remains. All three known-good recovery files
still match their fixed expected hashes. `/boot/grub/grub.cfg` is byte-identical
to its pre-deployment snapshot and retains `spx-known-good` as persistent default.

## Installed candidate and boot entry

All **202 regular files** under
`/usr/lib/modules/7.3.0-rc2-spx-mainline-20260922l+/` match the archived module
manifest, with exact regular-file coverage. There are **187 modules** and every
independently read vermagic names L. The installed strict-depmod log is empty.
SPI-HID will load from this installed tree; it is absent from L's initramfs.

All **three deployed L payloads** match both the attempt manifest and verified
build artifacts. All **eleven runtime files** match their unchanged K hashes.
Global and per-attempt manifests are equal. The pinned K baseline result hash is:

```
f4b1ad653528f7737ee91267f6b0187ec39c475cdcda1893ebb84a6a62299617
```

That result names the live K boot/release, records 605.12 seconds and explicitly
records no recovery return. The completed preflight uses the same proof.
Its scoped audio/graphical pass does not erase K's failed touch enumeration.

The candidate command line equals K's command line with exactly the attempt
marker replaced by `20260922l` and `spi_hid.startup_diag=1` appended. The
diagnostic flag, stage 4, pin-after-QMI 1 and 600-second window each occur
exactly once. No other stage or policy change was introduced.

Regenerating the GRUB entry from the manifest produces the exact archived
entry. The installed custom file contains that single entry and references
only L payload paths. Both GRUB files pass `grub-script-check`.

The early logger, return timers and boot evidence service are enabled. The
600-second marker still suppresses the ordinary short return timer and selects
the long timer. All origin return timers are inactive; periodic evidence
collection remains active.

## One-shot queue boundary

The generated queue script compiles and preserves the reviewed one-shot
sequence: preflight, payload/module/recovery/runtime checks, native continuation
validation, saved/pending-selection and boot-ID checks, exclusive flushed
request marker, one-time selection, selection/identity recheck, sync and delayed
reboot. It specifically requires `spi_hid.startup_diag=1` and audio stage 4.
A failure clears its own pending entry and retains the request marker for
inspection. This reviewer did not execute the queue.

An independent live Happy check confirmed the expected session/thread,
`resumeOnDaemonStart=true`, message `continue`, workspace and live process
arguments. Only required metadata fields were inspected; no raw session
metadata was printed or retained. The copied K continuation acknowledgment
matches its source record.

At the final check, `saved_entry=spx-known-good`, GRUB `next_entry` was empty,
EFI `BootNext` was absent, and L had no `reboot-requested` marker. The root
workflow must preserve final K evidence and repeat the immediate pre-reboot
checks before selecting L once. This review establishes prepared deployment,
not L hardware behavior or automatic recovery from an early hang.

The independent checker is `/var/tmp/spx-review-l-deployment.py`. No services,
boot selection, modules or runtime device state were changed by this review.
