# P source and artifact review — 2026-09-22

**Independent offline artifact verification passed.** All **985 archived
regular files** match the completed staging tree and its manifest, with
exact coverage; all **272 symlinks** have identical paths and targets.
The review verified **187 modules**, **202 module-tree files** and **54
modules parsed from the actual initramfs**. This establishes artifact
provenance, not a P hardware result. The reviewer performed no deployment,
boot selection, timer change or live device mutation.

The reviewed release is `7.3.0-rc2-spx-mainline-20260922p+`, built from
commit `907fc689af98a2ae9e7b74d10a74a33f8d4f9e5b`. Review ran while O boot
`2e177f51-cc3c-482f-9203-faf678e0529c` was still running the L release.
The completed staging tree is
`/var/tmp/spx-mainline-trial-20260922p.lj4adqfk`; the permanent build is
`/var/lib/spx-boot-diagnostics/attempts/20260922p/build/`.

## Source and configuration

Compared with L's archived tracked diff, the only changed kernel-source
section is `drivers/slimbus/qcom-ngd-ctrl.c`; the other two changed sections
are the diagnostic README and COMPONENTS documents. The NGD source exactly
matches the independently reviewed candidate, SHA-256
`364357cf6f2097185b66808dc59497cf6e6ed349fbdd9e8e679530581d298b0b`.
Its two changes restore `txn.rl=8` before every capability-response attempt
and correct the stage-7 step-6 message to describe RX and reactive capability
traffic with no proactive TX. The worker's retry contract passed eight
source-based harness cases and independent review; this does not establish
FIFO behavior, concurrency or hardware safety. See the
[PIO scope and retry review](AUDIO-PIO-STAGE7-STEP6-20260922.md).

The candidate's difflib patch SHA-256 is
`062b76f30c15e89858afd9dd1038d42f152eb41388d8620c011190b6817075f4`.
The working-tree Git diff SHA-256 is
`12d89695dfd9f194e06f07fec042d4be4b2f1e2f460ca133cb45e24f7aada31f`.
They use different headers and alignment for the moved assignment. The
candidate patch was recreated exactly from its saved baseline/candidate,
and both read-only reverse-apply checks passed against the applied source.
These are two serializations of the same source transformation.

SPI-HID core/header remain byte-identical to the reviewed L source. P's
source-ready hashes, source commit, complete tracked diff and reviewed
candidate copy were independently checked. The build's tracked-source and
configuration freeze checks passed.

The configuration differs from L only in `CONFIG_LOCALVERSION`, changing
`-spx-mainline-20260922l` to `-spx-mainline-20260922p`. P config SHA-256 is
`ae2115043d59097edb445500fbd0eac81e92279afc76ab6de223bea253640fcb`.
The configuration extracted from Image matches the archived configuration
byte-for-byte. The vmlinux banner contains the P release. Kernel gzip mtime
is zero and its decompressed bytes exactly equal the archived Image.

Build command records show successful olddefconfig, prepare, Image/DTB and
module steps. Image/DTB took 141.86 seconds and modules 41.96 seconds.
Image/module logs contain no checked warning/error signatures; depmod output
is empty. The initramfs build retains L's two warnings: an unsupported
architecture hook is skipped, and the optional platform privacy-screen
symbol provider is absent. Their text matches L's archived build log.

## Modules and actual initramfs

Every one of the 187 modules listed by modules.order matches its staged
installed copy byte-for-byte and reports P vermagic. All 202 regular module
tree files match the module hash manifest, with exact coverage. No old
release module is substituted.

| Item | SHA-256 |
| --- | --- |
| Kernel gzip | `dd6428bb9627b5bbff130b4b537663c7550ad1ce9a353caa6381aefa3fcd4d65` |
| Initramfs | `ed82fa0ed659fd1163682114f6be5f45c37fadec63b6da873f4402c557736f68` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| NGD module | `e174c83da26a2909bfbc8aefa4891e51b53cf97d5c8b65ce02c31d88023d9e3a` |
| SPI-HID module | `1137075e1bc898a5408a7261e4b4bb8f3b996fa625c7da2e31c8a085e9010d03` |
| MSM module | `150ef9e9d8785f8deae2f73297ebbafca6d6f66105068fbb37575bd316a67dfc` |
| uinput module | `580c95983da63cfe31959a0333a5d124bac028263ee0a1aff6ac6a4815354f93` |
| CMAC module | `a6783fdce1a9aef1a3231b451b99a22463100aeebc75e59611db9d5b4fb39470` |

NGD GNU build ID is `9d798dbb17629e682c22a58b87a4e2049623c410`;
SPI-HID GNU build ID is `a553336c86ec10a580b2842baf01be15e2c31d4c`.
These identify P's built modules, not the modules loaded in the running O
session. NGD contains the corrected reactive-traffic message and lacks the
old misleading no-TX message. SPI-HID's compiled startup-diagnostic parameter
remains default false and mode 0444. The DTB is unchanged from L.

The checker parsed the actual early newc archive and gzip-compressed main
newc archive, with **8 early entries** and **661 main entries**. All 54
module payloads match the staged P modules and extracted copies exactly.
SPI-HID is absent from the initramfs and will load from the installed root
module tree. The initrd logger script, unit and relative target-wants symlink
match their staged sources. Initramfs bytes and private extraction contents
were inspected without printing secrets. Staging/permanent build and
extraction directories are mode 0700; private initramfs files are mode 0600.

## Preserved evidence and scope

The inherited touch evidence manifests were reverified: 19 diagnostic,
3 protocol, 4 K investigation and 16 bounded-fix files. P's 14 PIO review
files, 4 build-helper review files, 3 assembly/archive review files and
3 patch-serialization review files also passed their manifests with exact
coverage. Actual build artifacts and both reviewed NGD source copies match.

The complete build-manifest SHA-256 is
`84df0c3afb1e75bf374f8f5027285f412539d948c860648ee40541c8cb96447e`.
Successful machine-readable report is `/var/tmp/spx-p-artifacts-review.json`,
with a byte-identical copy at
`/var/lib/spx-boot-diagnostics/attempts/20260922p/independent-artifact-review/review.json`.
Its SHA-256 is
`f631bf1df91fe26a50b75696e5ae02f731a35204ec25a45dbca9edf602128e17`.
The independently maintained checker `/var/tmp/spx-review-p-artifacts.py`
is preserved alongside it; checker SHA-256 is
`f16ddf27e87cc51829e1dd7105a3b2622b224e0f85c08151904aa1a738fa984b`.

Private staging and permanent build were not modified by this review.
Deployment verification and a fresh P boot with the reviewed selectors and
observation window remain separate work. This review establishes no PIO
exchange, codec enumeration, functional audio, physical input reliability,
automatic early-hang recovery or complete mainline port.
