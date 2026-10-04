# Independent M preparation review, 2026-09-22

**M's prepared state passed independent read-only review.** Checks ran at
**1550.30–1551.85 seconds** of live L boot
`90f1a5fc-5a70-4bd5-8d7d-99e45039b007`. No M boot had been selected, and no
M hardware result was available. The reviewer made no boot-selection,
service, module or device-state changes.

M is a logging-disabled control using the **exact L artifacts** and release
`7.3.0-rc2-spx-mainline-20260922l+`. The ordered command line differs from L
in exactly two tokens: `spx_attempt=20260922l` becomes `spx_attempt=20260922m`,
and `spi_hid.startup_diag=1` becomes `spi_hid.startup_diag=0`. Audio remains
stage 4 with pin-after-QMI 1 and the 600-second observation window. Each
critical token occurs exactly once. L's live diagnostic parameter remained
Y during review; this change applies to the future boot.

## Artifact and proof checks

The copied build manifest equals L's. All **937 regular build files** match
their recorded hashes, with exact coverage; all **272 symlinks** equal L's
without following them. This includes L's source diff, configuration, Image,
DTB, modules, initramfs and original verification evidence. M does not claim
a new build. Current README/component-status updates are separately recorded
documentation changes, not changes to the reused kernel source snapshot.

All **202 installed module-tree files**, including **187 modules**, match the
copied L manifest with exact regular-file coverage. The three installed boot
payloads match both L's and M's manifests:

| Payload | SHA-256 |
| --- | --- |
| Kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

They remain in `/boot/spx-trial-20260922l/`; there is no separate M payload
slot. No module installation or slot reclamation was performed for M.
[L's artifact review](ARTIFACT-REVIEW-20260922l.md) already independently
examined the embedded configuration and actual initramfs contents. Their
identical bytes establish reuse without another extraction. SPI-HID remains
absent from the initramfs and will load from the installed L module tree.

The copied attempt/build/extraction directories are private, and the archived
initramfs is 0600. Deployed boot-file modes are governed by the existing VFAT
mount mask; this review makes no 0600 claim for that filesystem.

All **three recovery files** and **eleven runtime files** match the unchanged
L manifests. `/boot/grub/grub.cfg` is byte-identical to its pre-preparation
snapshot and retains `spx-known-good` as persistent default.

Global and M attempt manifests are equal. Their validated-preboot proof names
the current L boot/release and pins the completed **629.82-second** result:

```
4f7c265f10b586e65c7836d376c4a3c8c081a61b68e0bcc2000cb873c228625d
```

The result identity, hash, duration and explicit absence of a recovery return
were independently checked. The prepared preflight contains the same proof.
[L's final result](RESULT-20260922l.md) records successful input enumeration
while leaving physical input and intermittent-failure resolution open.

## Preparation and one-shot boundary

The final preparation helper's SHA-256 is:

```
9675972d7762763c68813b17715845352d4f918587351b78d02e2384bcdf89be
```

Its reviewed checks pin the live L identity, baseline proof, full build
manifest, configuration and queue template. They permit only the two stated
command-line substitutions and known README/component-status drift in the
working-tree comparison. The helper copies and verifies the archive, retains
the installed L artifacts, writes the M entry/manifests, and runs preflight.
It does not select a boot. The final small guard correction accepts systemd
exit code 4 for an already garbage-collected transient fallback; persistent
return timers still require inactive exit code 3. This does not permit an
active fallback timer.

Regenerating the GRUB entry from M's manifest exactly reproduces `entry.cfg`.
The custom file contains that single entry referencing L's payloads. Both
installed GRUB files pass `grub-script-check`. The early logger, return timers
and boot evidence service are enabled. Origin return timers are inactive,
and periodic evidence collection remains active.

The prepared queue compiles and retains L's reviewed checks: read-only
preflight, artifact/module/recovery/runtime hashes, validated origin identity,
native continuation, persistent default, empty pending selection, an exclusive
flushed request marker, one-time selection, another selection/boot-ID check,
sync, and a delayed reboot. It additionally requires release L and unique M,
diagnostic-disabled, stage-4 and pin-after-QMI tokens. On failure it clears its
own pending entry and retains the request marker for inspection. The reviewer
did not execute it.

An independent live Happy query confirmed the intended session/thread,
`resumeOnDaemonStart=true`, message `continue`, workspace and live host-process
arguments. Raw session metadata was neither printed nor retained. The copied
L continuation acknowledgment equals its source record.

At the final check, `saved_entry=spx-known-good`, GRUB `next_entry` was empty,
EFI `BootNext` was absent, and M had no `reboot-requested` marker. Root must
preserve the final L snapshot and repeat immediate identity/pending-selection
checks before selecting M once. This review establishes preparation, not M
startup reliability, complete port functionality or automatic recovery across
an early hang.

The independent checker is `/var/tmp/spx-review-m-preparation.py`. Its initial
run stopped on an incorrect assumption about VFAT permissions; the corrected
checker verifies private archive permissions and exact deployed bytes. No
payload discrepancy was found.
