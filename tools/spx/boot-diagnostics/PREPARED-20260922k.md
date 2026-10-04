# SPX SPI-HID startup recovery trial K — 2026-09-22

K is a distinct build, `7.3.0-rc2-spx-mainline-20260922k+`, containing the
[bounded SPI-HID startup fix](TOUCH-KERNEL-FIX-20260922.md). Audio stays at
stage 4 with pin-after-QMI enabled and every existing guard unchanged. The
DTB and runtime policies are unchanged. The configuration differs from G
only in LOCALVERSION; the included CAMSS allocator dependency is inactive
because cameras remain disabled. The command-line change from J is only
the attempt marker.

J completed 644.15 seconds of audio stage 4, graphics, Wi-Fi and remoteproc
observation, with 274 result files hash-verified. Its touch probe stalled
before publishing a HID device after an invalid startup header. IPTSD could
not start, so its userspace retry policy was never exercised. No live
SPI-HID intervention was attempted. See [J's result](RESULT-20260922j.md).

K rearms startup polling within the existing two-second window, avoids
overlapping SPI transfers and drains asynchronous callbacks during teardown.
It leaves the shared EC reset escalation disabled. The eight source-function
tests, target compilation and independent code review passed; hardware
recovery and physical touch/pen remain unverified. The underlying reason for
invalid startup headers remains unresolved.

The completed build contains 187 modules and a 202-file installed-module
manifest. All 902 permanent build files were independently verified. The
actual initramfs contains 54 matching K modules and the expected logger.
SPI-HID is absent from the initramfs and must load from K's installed root
module tree. See [artifact review](ARTIFACT-REVIEW-20260922k.md).

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `053216e305f6770971b8f7c973ae56da92a7886d8015b60ac202a6cde189a4c9` |
| Initramfs | `555795038e8c53999007fe5c97bc7b3c042d47641110a7706e5b440fdb75da18` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| SPI-HID module | `6ed068ba2900fed2a4532dc19d7f61375a765d115f851ff460b0843e7556b5bc` |

Boot artifacts are installed under `/boot/spx-trial-20260922k/`, modules under
`/usr/lib/modules/7.3.0-rc2-spx-mainline-20260922k+/`, and the build under
`/var/lib/spx-boot-diagnostics/attempts/20260922k/build/`. Deployment is recorded
separately in `deployment-result.json`; this preparation document alone does
not establish deployment or boot success. To fit the EFI partition, the
consumed G trial slot is archived and hash-checked under K's
`retired-boot-slots/` before retirement. G's installed modules stay available.
The known-good kernel, initramfs and DTB retain their verified hashes.

Preboot is J, boot ID `6a9377c7-dcd8-463c-823e-c29710eb5e96`; its immutable
baseline result hash is
`f0b8353f913b645d36c256b29e447301e902f59a5be5b089a6fc60a996f27fdd`.
Recheck identity, pending GRUB/EFI selection, recovery and all installed
payload/module/runtime hashes before queuing K once. `spx-known-good` stays
the persistent default. Native Happy resumes the same Codex thread.

After reboot, inspect identity, uptime and return timers first. If extending
the original 600-second window, arm a replacement fallback at least 20 minutes
away before stopping the original timer. Preserve periodic evidence. Observe
at least 600 seconds, then hash the collected result before retaining mainline
or selecting another experiment.

Record touch separately: clean enumeration, recovery after a logged invalid
header, or continued failure. Check the actual loaded module, HID publication,
IPTSD startup/restarts and virtual touch/pen devices. One successful boot
cannot establish that this intermittent failure is fixed. Do not live
unbind/rebind display, raise audio stages, force audio runtime resume, unload
pinned audio or restart ADSP. Pre-kernel automatic recovery is still unproven.
The separately reviewed stage 5 audio test remains a later fresh-boot task.
