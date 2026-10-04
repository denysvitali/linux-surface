# P installed deployment review — 2026-09-22

**Independent read-only deployment verification passed at O uptime
2992.54–2995.85 seconds.** P is installed and prepared; no P boot was selected
during this review. The running boot remained O,
`2e177f51-cc3c-482f-9203-faf678e0529c`, release
`7.3.0-rc2-spx-mainline-20260922l+`.

The target is `7.3.0-rc2-spx-mainline-20260922p+`. All **202 installed
module-tree files**, including **187 modules** with P vermagic, match the
archived build. Installed module symlinks also match. All **985 immutable
build files** were rehashed with exact manifest coverage. The pinned
[independent artifact review](ARTIFACT-REVIEW-20260922p.md) matches the
installed payload hashes and source/configuration provenance.

| Installed payload | SHA-256 |
| --- | --- |
| `/boot/spx-trial-20260922p/vmlinuz` | `dd6428bb9627b5bbff130b4b537663c7550ad1ce9a353caa6381aefa3fcd4d65` |
| `/boot/spx-trial-20260922p/initramfs.img` | `ed82fa0ed659fd1163682114f6be5f45c37fadec63b6da873f4402c557736f68` |
| `/boot/spx-trial-20260922p/spx.dtb` | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

P NGD build ID is `9d798dbb17629e682c22a58b87a4e2049623c410`; P SPI-HID
build ID is `a553336c86ec10a580b2842baf01be15e2c31d4c`. These installed P
modules have not been loaded by this review.

All three consumed L boot payloads match their preserved copies under
`attempts/20260922p/retired-boot-slots/20260922l/`. That directory is mode
0700 and its initramfs is mode 0600. The former L boot slot is absent;
all **202 installed L module files** remain present and hash-correct.
The three known-good recovery files retain their pinned hashes. All eleven
runtime-policy files match O's manifest.

The global and per-attempt manifests agree. The ordered command line
changes O's attempt to P, stage 5 to 7 and stage-5 step 2 to 0, then appends
stage-7 step 6, PIO 1 and proactive capability retries 0 exactly once.
All other tokens remain unchanged, including startup diagnostics 0,
pinning 1 and the 600-second observation window. The generated GRUB entry
matches these selectors and P payload paths; both GRUB files pass syntax
checks. The main GRUB configuration is byte-identical to its pre-deployment
copy. `spx-known-good` remains the persistent default, `next_entry` is empty,
EFI BootNext is absent, and P has no reboot-requested marker.

The validated origin is O's 611.87-second result, SHA-256
`14e612628f5d590ed590a108e78357d9cfa744f6599a89aecce11e66d01952e8`,
with no recovery return. Read-only preflight pins the same proof. Native
Happy continuation settings and the matching live session process were
independently checked without preserving raw metadata. Required logging and
return units are enabled; return timers are inactive after O's completed
result, while periodic evidence collection remains active.

The running NGD and SPI-HID build-ID notes still match L. Audio remains
stage 5, step 2, PIO N, pinned/refcount 1, child runtime-suspended with active
time zero. GDM, iwd, NetworkManager and IPTSD are active; touch is ready,
Wi-Fi is connected, all three remote processors are running and taint is
zero. The reviewer changed no boot selection, timer or live device state.

The deployed helper SHA-256 is
`581966aca40cf945681ccebfea81a57f3ec4ed1ae903c8d77b778842ca03b9a3`;
generated queue SHA-256 is
`d04581b0aba99e37649412a896561a92cfba8df261c2e0ef67bba1b5af1e13c1`.
Both match the independently reviewed versions and saved queue provenance.

The checker is `/var/tmp/spx-review-p-deployment.py`, SHA-256
`77d7e8b6b8ab3e39735680c0bc8765f27559cac36ad81e7057be7731df452502`.
Successful report `/var/tmp/spx-p-deployment-review.json` and its identical
archived copy under P's `independent-deployment-review/` have SHA-256
`18832ddd572bdb1b5606385370f0239b86718ed85becb7d97f1ce396af59473d`.
Evidence is separate from the immutable build. P's hardware result remains
unknown; the next step is the final O evidence snapshot and one-shot boot.
