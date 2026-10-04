# Independent L artifact review, 2026-09-22

The completed staged L artifacts and permanent build archive passed this
read-only review before deployment. K remains the live boot. This review
does not establish that L boots successfully or recovers touch input.

Stage: `/var/tmp/spx-mainline-trial-20260922l.pp84cyjo`.
Release: `7.3.0-rc2-spx-mainline-20260922l+`.
Base commit: `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b`.
Permanent archive:
`/var/lib/spx-boot-diagnostics/attempts/20260922l/build/`.

## Source and configuration

The frozen SPI-HID source hashes match `source-ready.json`, the tested
evidence copies and the workspace:

| File | SHA-256 |
| --- | --- |
| `spi-hid-core.c` | `fc0dd9640a3b99376f3ef2f73621df2ed742181b9a42751e03d8549b382d687a` |
| `spi-hid-core.h` | `31c5fcc5cfe847112101d06c7f7b77819a4173a1be20158e0d5daf63f65ccaa0` |

The staged `source.diff` exactly matches `git diff --binary HEAD`, with SHA-256
`9f53a9aeddbe2ea13f59bbe909cb54a5de3a03aef9af6f040ceb77d70067a101`.
Comparing K and L snapshots, the only changed kernel sources are those two
SPI-HID files; the diagnostic README and component status also changed.

The K-to-L driver delta adds startup metadata calls/counters and moves lock
initialization before the first diagnostic call. `startup_diag` defaults to
false and is declared with permissions **0444**. Independent parsing of the
compiled module's ELF symbols and parameter record confirms both the zero
default and those read-only permissions, rather than relying only on source
text or `modinfo` description.

The diagnostic records software state and results of existing calls. It adds
no hardware reads/writes, GPIO probes, protocol requests or reset operations,
and changes no explicit sleep or polling policy. In particular,
`descriptor-request` labels the existing reset-response path; L does **not**
send a speculative descriptor request after failed polls. Logging can still
perturb timing. Output is capped at four windows of at most 48 lines per
device instance, with a reserved terminal line if an existing terminal event
is reached. It contains metadata rather than report payloads. See
[the implementation review](TOUCH-K-REVIEW-20260922.md).

The L configuration is byte-for-byte K after replacing only `LOCALVERSION`.
Its SHA-256 is
`bea8bf7cacc344e79bff81fb8993ac9934a813f9b213cab5157e39fe68d43e04`.
SPI-HID remains modular and cameras remain disabled. The intended command
line enables the diagnostic with `spi_hid.startup_diag=1` and retains audio
stage 4; deployment must verify those arguments separately.

## Image, modules and actual initramfs bytes

An independent `extract-ikconfig` invocation on the staged raw Image produces
the exact staged and active configuration. Decompressing `vmlinuz` produces
that exact Image, with gzip timestamp zero. The DTB is unchanged from K/G.

Exactly **187 unique module artifacts** match `modules.order`. Every module's
independently read vermagic names L, and every staged installed module matches
its corresponding build artifact byte-for-byte. All **202 regular files** in
`module-sha256.json` match, with exact regular-file coverage. The strict depmod
log is empty.

An independent in-memory parser read the actual early CPIO archive and the
gzip-compressed main CPIO, rather than trusting an extraction listing. It
found 8 early and 661 main entries. All **54 actual module payloads** match
the staged module tree and extracted copies, including MSM. The exact logger
script, service and `initrd.target.wants` symlink match their intended inputs.
SPI-HID is absent from the actual archive; L must load it from the newly
installed root module tree.

The stage and extraction directories are mode 0700 and the initramfs is 0600.
No unlock-key contents were printed or included in this report. The independent
checker is `/var/tmp/spx-review-l-artifacts.py`; it performs no installation,
module loading or runtime changes.

| Artifact | SHA-256 |
| --- | --- |
| `vmlinuz` | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| `initramfs.img` | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| SPX DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| `msm.ko` | `2612459305dfa82bbee150afcf5a4be0c02502e5de5fe2f80e45dfda74800db3` |
| `spi-hid.ko` | `b9e0dddfdeaaef93279c9346060ec95c3d94f06a8ec3a3dd23b108b7a5d95607` |
| `uinput.ko` | `2d8e151aecf08c2705f06d9bce351aff59507357672fe1395a0a651ad7c56fe2` |
| `cmac.ko` | `963696cbccb2d785e7ad66248b497941b45e38015f89649b800832367067fcbc` |

## Permanent archive and deployment boundary

All **937 regular files** in the permanent build independently match
`build-sha256.json`, with exact coverage and matching staged contents. All
**272 symlinks** match the stage without following them. Attempt/build and
extraction directories remain 0700, and the archived initramfs remains 0600.
The copied evidence manifests independently verify 19 startup-diagnostic,
3 protocol, 4 K-investigation and 16 inherited startup-fix files.

At this review, `archive-result.json` records deployment and boot selection
as false; no L attempt manifest, deployment result or reboot request exists.
The root workflow must still install and verify L's complete module tree,
preserve/hash K before reclaiming its consumed boot slot, check deployed
payload/recovery hashes, retain `spx-known-good` as persistent default, and
recheck boot identity and pending selection before selecting L once.

The diagnostic is a new observation of the failed input startup, not a
hardware recovery claim. No live input intervention, display rebind,
audio-stage change, pinned-module unload or remoteproc restart was performed
for this review. Audio remains stage 4 for the planned fresh boot.
