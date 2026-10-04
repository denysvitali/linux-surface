# SPX startup metadata diagnostic L — 2026-09-22

L is being prepared as a distinct build with bounded SPI-HID startup logging,
enabled by the read-only boot parameter `spi_hid.startup_diag=1`. It retains
K's audio stage 4, DTB and runtime policies. The intended configuration change
is LOCALVERSION only. This document is a preparation record; the permanent
build, deployment and request manifests determine which steps have actually
completed.

The Image, DTB, 187 modules and initramfs build completed. The embedded config
is exact, strict depmod is clean, and all 202 staged module-tree files have
recorded hashes. The diagnostic parameter is default-off and mode 0444; its
four-window, 192-line limit passed actual-function UBSan tests. Independent
source/locking review and target compile/style checks passed. The artifact
review is recorded separately before deployment.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| SPI-HID module | `b9e0dddfdeaaef93279c9346060ec95c3d94f06a8ec3a3dd23b108b7a5d95607` |
| Configuration | `bea8bf7cacc344e79bff81fb8993ac9934a813f9b213cab5157e39fe68d43e04` |

[K's completed result](RESULT-20260922k.md) covers 605.12 seconds with the
expected audio register values, working desktop/EGL FD680, Wi-Fi and remote
processors. Its 279 archived result files were independently verified before
retaining mainline. No recovery return occurred. Touch still failed: three
bounded startup polls returned zero headers, the deadline expired, and no
HID/IPTSD device appeared. The touch IRQ count remained zero. SPI statistics
showed three completed messages, six transfers, no transport error and no
descriptor-request write.

L will record software startup ordering and existing completion metadata
without adding hardware reads, protocol messages, sleeps, power transitions
or interrupt-policy changes. This can distinguish software sequencing and
gating failures; it cannot measure physical voltage or SPI waveforms. Logging
itself can change timing, so a successful boot alone would not establish a
fix. Raw touch and pen payloads are outside this diagnostic.

A possible descriptor request without a preceding reset response was reviewed
and deferred. It could race with an interrupt-driven header/body transaction;
serializing output alone would not prevent that. L does not issue such a
request or enable the shared EC hard-reset escalation.

The intended release is `7.3.0-rc2-spx-mainline-20260922l+`, with artifacts in
`/var/lib/spx-boot-diagnostics/attempts/20260922l/` and boot files in
`/boot/spx-trial-20260922l/`. SPI-HID loads from the matching installed root
module tree. The K trial slot must be archived and hash-checked before its
space is reclaimed. Keep K's modules and the unchanged known-good recovery
files; `spx-known-good` remains the persistent default.

Preboot is retained K, ID `58d2ebe1-1b3d-4b75-aa1e-d0ff2d8b9562`. Its immutable
result SHA-256 is
`f4b1ad653528f7737ee91267f6b0187ec39c475cdcda1893ebb84a6a62299617`.
Before selecting L once, verify the final source/config, installed modules,
payload and recovery hashes, native continuation, boot identity and empty
GRUB/EFI pending selections. Never replay an issued request.

After reboot, inspect identity, uptime and return timers first. To extend the
600-second window, arm a replacement fallback at least 20 minutes away before
stopping the original timer. Preserve the complete startup chronology,
effective diagnostic parameter, loaded-module build ID, HID/IPTSD state,
audio guards and system evidence. Observe at least 600 seconds and hash the
archive before stopping the fallback or choosing another experiment.

No live display rebind, audio stage change, forced NGD runtime resume, pinned
module unload or ADSP restart. Pre-kernel automatic recovery is still
unvalidated. Stage 5 audio remains a separate later experiment.
