# Independent K artifact review, 2026-09-22

The completed staged K artifacts passed this read-only review before deployment.
This does not establish successful boot or recovery of the intermittent touch
startup failure. J remains the live boot during this review.

Stage: `/var/tmp/spx-mainline-trial-20260922k.mtag_esc`.
Release: `7.3.0-rc2-spx-mainline-20260922k+`.
Base commit: `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b`.

## Source and configuration

The staged `source.diff` exactly matches `git diff --binary HEAD`; its SHA-256 is
`0df56b307cc2e4989e91ec64e8080b4fd553fd97a3115d56a44aca3d4df60026`.
The active SPI-HID C and header match the frozen, tested source hashes in
[the implementation record](TOUCH-KERNEL-FIX-20260922.md). All 16 files in the
copied touch-fix evidence manifest independently pass their hashes.

The K configuration is byte-for-byte the G configuration after replacing only
the `LOCALVERSION` string. Its SHA-256 is
`e4b274603711c18713957d1b374b47ca05a9e583c60ff7dad6d2d6e6703ddf10`.
SPI-HID remains a module. VIDEO_DEV, VIDEO_QCOM_CAMSS and I2C_QCOM_CCI remain
disabled, so the additional CAMSS Kconfig dependency change does not enable
cameras in this build.

## Image, modules and initramfs

An independent `extract-ikconfig` invocation on the archived raw Image produces
the exact archived and active configuration. Decompressing staged `vmlinuz`
produces that exact Image, and the gzip timestamp is zero. The DTB is unchanged
from G.

There are exactly 187 unique module artifacts matching `modules.order`. Every
module's independently read vermagic names the K release. All staged installed
modules are byte-identical to the corresponding build artifacts, and all 202
files in `module-sha256.json` match. The staged depmod log is empty. The SPI-HID
module matches the freshly linked workspace artifact and contains the new
bounded-startup timeout diagnostic.

The extracted initramfs contains 54 modules; all match the staged module tree
byte-for-byte and carry K vermagic. A separate in-memory parser of the actual
early CPIO archive and gzip-compressed main CPIO independently confirms all 54
module payloads, including MSM, and the exact logger script, service and
`initrd.target.wants` symlink. SPI-HID is absent from both the actual archive and
the extracted tree; it must load from the installed K root module tree.

The stage and extraction directories are mode 0700 and the staged initramfs is
0600. No unlock-key contents were printed or copied into this review.

| Artifact | SHA-256 |
| --- | --- |
| `vmlinuz` | `053216e305f6770971b8f7c973ae56da92a7886d8015b60ac202a6cde189a4c9` |
| `initramfs.img` | `555795038e8c53999007fe5c97bc7b3c042d47641110a7706e5b440fdb75da18` |
| SPX DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| `msm.ko` | `c92f42c911a78118b1fa1502e2666e59e8c358e91a7bc93192b66fbbfde9f25a` |
| `spi-hid.ko` | `6ed068ba2900fed2a4532dc19d7f61375a765d115f851ff460b0843e7556b5bc` |
| `uinput.ko` | `b773ce85ad1ca9a7042beb17e04554b859bbd6a8444885186ccfff82d4fca862` |
| `cmac.ko` | `5a2963d1d12db80c02c892cfffed3ceda9cc5d3e59bbdd7852f04b9c097d4483` |

## Deployment boundary

At the initial review, all three G trial boot files and all three known-good
recovery files still matched their recorded hashes. This reviewer made no
build, module installation, service, boot selection or runtime changes.

Before reboot, the root workflow still must archive and hash K, preserve and
hash-check G before reclaiming its boot slot, install and verify the complete K
module tree, check deployed payload hashes, preserve the known-good default,
and recheck boot identity and pending selection. The intended K audio stage is
still 4; this artifact review does not authorize or imply a live stage change.
Hardware startup, finite touch polling behavior and physical touch/pen remain
unverified until the new boot is observed.

## Permanent archive follow-up

After the root workflow finalized
`/var/lib/spx-boot-diagnostics/attempts/20260922k/build`, this reviewer
independently recomputed all 902 regular-file hashes. They exactly match
`build-sha256.json` and the staged files. All 272 archived symlinks match the
stage without following them. The attempt/build directories remain mode 0700,
the initramfs 0600 and its extraction directory 0700. At this check,
`archive-result.json` records deployment and boot selection as false.

The archived copy of this document predates this follow-up; the build manifest
is intentionally unchanged. The subsequently completed deployment-script and
installed-file review is recorded in
[the deployment review](DEPLOYMENT-REVIEW-20260922k.md).
